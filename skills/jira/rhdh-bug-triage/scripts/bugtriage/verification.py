"""Acquire exact source/release/artifact evidence; never infer acceptance from it.

This read adapter uses native gh authentication for GETs and anonymous HTTPS for
public release/OCI metadata. No product code, image layer or test is executed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .forge import ForgeAdapterError, read_api, read_diff
from .model import validate_issue_key
from .report import now_iso, write_json

SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
PUBLIC_HOSTS = {
    "access.redhat.com",
    "docs.redhat.com",
    "registry.redhat.io",
    "registry.access.redhat.com",
    "quay.io",
}
MAX_BYTES = 8 * 1024 * 1024
ACCEPT = "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json, application/json, text/html"


def _mapping(value):
    return value if isinstance(value, dict) else {}


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in PUBLIC_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "verification requires credential-free HTTPS URLs on approved public evidence hosts"
        )
    return url


class _Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Registry blob GETs use signed CDN redirects. Keep capabilities inside
        # this adapter; never record the redirect URL/query in plans or receipts.
        parsed = urlsplit(newurl)
        if parsed.hostname == "cdn01.quay.io" and urlsplit(
            req.full_url
        ).hostname in PUBLIC_HOSTS | {"cdn01.quay.io"}:
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
            ):
                raise ValueError("unsafe registry metadata redirect")
        else:
            public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_public(url: str) -> bytes:
    """Anonymous, allowlisted, size-bounded GET; no login or bearer-token repair."""
    public_url(url)
    request = Request(url, headers={"Accept": ACCEPT, "User-Agent": "rhdh-bug-triage/read-only"})
    with build_opener(_Redirect()).open(request, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("public evidence exceeds the metadata read limit")
    return body


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


class Collector:
    def __init__(self, output: Path):
        self.output = output
        self.reads = []

    def read(self, kind, target, operation):
        receipt = {"id": len(self.reads) + 1, "kind": kind, "target": target, "readAt": now_iso()}
        self.reads.append(receipt)
        try:
            value = operation()
            raw = (
                value
                if isinstance(value, bytes)
                else value.encode()
                if isinstance(value, str)
                else json.dumps(value, sort_keys=True).encode()
            )
            path = self.output / "raw" / f"{receipt['id']:04}.bin"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            receipt.update(
                status="read",
                bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                path=str(path.relative_to(self.output)),
            )
            return value
        except (ForgeAdapterError, OSError, ValueError) as error:
            receipt.update(status="failed", error=str(error))
            return None

    def api(self, path):
        return self.read("forge_get", path, lambda: read_api(path))

    def resolve(self, repository, ref):
        path = (
            f"repos/{repository}/git/commits/{ref}"
            if SHA.fullmatch(ref)
            else f"repos/{repository}/git/ref/{quote(ref, safe='/')}"
        )
        value = self.api(path)
        obj = (
            {"type": "commit", "sha": value.get("sha")}
            if isinstance(value, dict) and SHA.fullmatch(ref)
            else value.get("object", {})
            if isinstance(value, dict)
            else {}
        )
        if SHA.fullmatch(ref) and (not isinstance(value, dict) or value.get("sha") != ref):
            return ""
        for _ in range(4):
            if not isinstance(obj, dict):
                return ""
            revision = obj.get("sha", "")
            if not isinstance(revision, str) or not SHA.fullmatch(revision):
                return ""
            if obj.get("type") == "commit":
                return revision
            if obj.get("type") != "tag":
                return ""
            tag = self.api(f"repos/{repository}/git/tags/{revision}")
            obj = tag.get("object", {}) if isinstance(tag, dict) else {}
        return ""

    def source(self, repository, revision, path):
        ref = f"https://github.com/{repository}/blob/{revision}/{quote(path, safe='/')}"
        value = self.api(f"repos/{repository}/contents/{quote(path, safe='/')}?ref={revision}")
        result = {"path": path, "ref": ref, "status": "unavailable"}
        if not isinstance(value, dict) or value.get("type") != "file" or value.get("path") != path:
            return result
        expected_size, expected_blob = value.get("size"), value.get("sha")
        # GitHub omits inline contents for large files such as lockfiles. Fetch
        # only the exact blob named by the revision-scoped contents response.
        if (
            value.get("encoding") == "none"
            and isinstance(expected_blob, str)
            and SHA.fullmatch(expected_blob)
        ):
            value = self.api(f"repos/{repository}/git/blobs/{expected_blob}")
        if not isinstance(value, dict) or value.get("encoding") != "base64":
            return result
        try:
            raw = base64.b64decode("".join(value.get("content", "").split()), validate=True)
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if len(raw) != expected_size or blob != expected_blob or blob != value.get("sha"):
                raise ValueError("source size/blob identity does not match returned bytes")
            result.update(
                status="read",
                blobSha=blob,
                sha256=hashlib.sha256(raw).hexdigest(),
                text=raw.decode("utf-8"),
            )
        except (ValueError, UnicodeError) as error:
            result.update(status="invalid", error=str(error))
        return result

    def repository(self, plan):
        repository, ref = plan["repository"], plan["ref"]
        revision = self.resolve(repository, ref)
        result = {
            "repository": repository,
            "requestedRef": ref,
            "revision": revision,
            "files": [],
            "pullRequests": [],
            "scope": "source_only_not_product_artifact",
            "gaps": [],
        }
        if not revision:
            result["gaps"].append("source revision could not be resolved")
            return result
        for path in plan.get("paths", []):
            result["files"].append(self.source(repository, revision, path))
        for number in plan.get("pullRequests", []):
            pull = self.api(f"repos/{repository}/pulls/{number}")
            item = {
                "number": number,
                "ref": f"https://github.com/{repository}/pull/{number}",
                "containment": "unknown",
            }
            result["pullRequests"].append(item)
            if not isinstance(pull, dict):
                continue
            merge = pull.get("merge_commit_sha")
            item.update(
                state=pull.get("state"),
                merged=pull.get("merged") is True,
                mergedAt=pull.get("merged_at"),
                mergeCommit=merge,
                body=pull.get("body"),
                changedFiles=pull.get("changed_files"),
            )
            item["diff"] = self.read("pr_diff", item["ref"], lambda: read_diff(repository, number))
            if pull.get("merged") is not True or not pull.get("merged_at"):
                item["containment"] = "not_a_merged_fix"
                continue
            if not isinstance(merge, str) or not SHA.fullmatch(merge):
                continue
            comparison = self.api(f"repos/{repository}/compare/{merge}...{revision}")
            if isinstance(comparison, dict):
                item["comparisonRef"] = (
                    f"https://github.com/{repository}/compare/{merge}...{revision}"
                )
                item["containment"] = (
                    "contained"
                    if comparison.get("status") in ("ahead", "identical")
                    and _mapping(comparison.get("merge_base_commit")).get("sha") == merge
                    and _mapping(comparison.get("base_commit")).get("sha") == merge
                    else "absent"
                    if comparison.get("status") in ("ahead", "identical", "behind", "diverged")
                    else "unknown"
                )
        if any(file["status"] != "read" for file in result["files"]):
            result["gaps"].append(
                "one or more requested implementation/configuration/dependency paths were not read"
            )
        if any(
            pull.get("diff") is None or pull["containment"] == "unknown"
            for pull in result["pullRequests"]
        ):
            result["gaps"].append(
                "one or more corrective diffs/incorporation checks remain unavailable"
            )
        return result

    def artifact(self, plan, release_body, repositories):
        """Read only OCI index/manifest/config metadata, verifying digest edges."""
        expected = plan["digest"]
        result = {
            "releaseReference": plan["releaseReference"],
            "digest": expected,
            "releaseRecordContainsReference": plan["releaseReference"].encode() in release_body,
            "objects": [],
            "sourceBinding": "not_established",
            "gaps": [],
        }
        registries = list(
            dict.fromkeys([plan["registry"], plan["releaseReference"].split("/", 1)[0]])
        )

        def get_object(kind, digest):
            raw = None
            for registry in registries:
                url = f"https://{registry}/v2/{plan['repository']}/{kind}/{digest}"
                raw = self.read("oci_metadata", url, lambda: read_public(url))
                if raw is not None:
                    break
            if raw is None:
                result["gaps"].append(
                    f"metadata unavailable from requested registry and release origin: {kind}/{digest}"
                )
                return None
            actual = "sha256:" + hashlib.sha256(raw).hexdigest()
            result["objects"].append(
                {
                    "url": url,
                    "expectedDigest": digest,
                    "actualDigest": actual,
                    "digestMatches": actual == digest,
                }
            )
            if actual != digest:
                result["gaps"].append(
                    "OCI digest does not match the actual returned metadata bytes"
                )
                return None
            try:
                value = json.loads(raw)
            except ValueError:
                value = None
            if not isinstance(value, dict):
                result["gaps"].append("OCI metadata is not a JSON object")
                return None
            return value

        manifest = get_object("manifests", expected)
        if manifest and isinstance(manifest.get("manifests"), list):
            children = [
                child
                for child in manifest["manifests"]
                if isinstance(child, dict)
                and _mapping(child.get("platform")).get("os") == "linux"
                and _mapping(child.get("platform")).get("architecture")
                == plan.get("architecture", "amd64")
            ]
            if len(children) != 1:
                result["gaps"].append(
                    "requested OCI platform does not resolve to one child manifest"
                )
                manifest = None
            else:
                digest = children[0].get("digest", "")
                manifest = (
                    get_object("manifests", digest)
                    if isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                    else None
                )
        config = _mapping(manifest.get("config")).get("digest", "") if manifest else ""
        if not isinstance(config, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", config):
            result["gaps"].append("image config digest could not be established")
            return result
        metadata = get_object("blobs", config)
        labels = _mapping(metadata.get("config")).get("Labels", {}) if metadata else {}
        labels = labels if isinstance(labels, dict) else {}
        labels = {key: value for key, value in labels.items() if isinstance(value, str)}
        result["sourceLabels"] = {
            k: v
            for k, v in labels.items()
            if k
            in (
                "vcs-ref",
                "vcs-url",
                "org.opencontainers.image.revision",
                "org.opencontainers.image.source",
                "version",
                "release",
            )
        }
        revision = labels.get("org.opencontainers.image.revision") or labels.get("vcs-ref")
        source = (
            (labels.get("org.opencontainers.image.source") or labels.get("vcs-url") or "")
            .removesuffix(".git")
            .rstrip("/")
        )
        if not source and isinstance(revision, str) and SHA.fullmatch(revision):
            result["revisionLookups"] = [
                {
                    "repository": repo["repository"],
                    "revision": revision,
                    "resolved": self.resolve(repo["repository"], revision) == revision,
                }
                for repo in repositories
            ]
            result["gaps"].append(
                "image declares a revision without a source repository; candidate-repository lookups do not alone prove the product source mapping"
            )
        if result["releaseRecordContainsReference"] and not result["gaps"]:
            matching = [
                repo
                for repo in repositories
                if source == f"https://github.com/{repo['repository']}"
                and revision == repo["revision"]
            ]
            if matching:
                result["sourceBinding"] = "declared_source_matches"
                result["bindingLimit"] = (
                    "image metadata declares this source; not an independent build attestation or acceptance test"
                )
        if result["sourceBinding"] == "not_established":
            result["gaps"].append(
                "exact release artifact metadata does not establish the inspected repository/revision binding"
            )
        return result


def validate_plan(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("issues"), list) or not plan["issues"]:
        raise ValueError("verification plan needs a nonempty issues list")
    release = plan.get("release", {})
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(release.get("version", ""))):
        raise ValueError("verification plan needs an exact reviewed release")
    public_url(release.get("url", ""))
    keys = set()
    for issue in plan["issues"]:
        key = validate_issue_key(issue.get("key"))
        if key in keys:
            raise ValueError("duplicate verification issue")
        keys.add(key)
        requirements = issue.get("requirements")
        if (
            not isinstance(requirements, list)
            or not requirements
            or any(not isinstance(v, str) or not v.strip() for v in requirements)
        ):
            raise ValueError("verification needs explicit reported acceptance requirements")
        for repo in issue.get("repositories", []):
            if (
                not REPOSITORY.fullmatch(repo.get("repository", ""))
                or not isinstance(repo.get("ref"), str)
                or not (
                    SHA.fullmatch(repo["ref"])
                    or re.fullmatch(r"(?:tags|heads)/[A-Za-z0-9_./-]+", repo["ref"])
                )
            ):
                raise ValueError("verification requires an explicit repository and source ref")
            if not repo.get("paths"):
                raise ValueError("verification needs implementation/configuration paths to inspect")
            if any(
                not isinstance(path, str)
                or not path
                or path.startswith("/")
                or ".." in path.split("/")
                for path in repo["paths"]
            ):
                raise ValueError("invalid repository path")
            if any(
                type(number) is not int or number < 1 for number in repo.get("pullRequests", [])
            ):
                raise ValueError("invalid PR number")
        for artifact in issue.get("artifacts", []):
            if (
                artifact.get("registry")
                not in PUBLIC_HOSTS - {"access.redhat.com", "docs.redhat.com"}
                or not re.fullmatch(r"[a-z0-9_./-]+", artifact.get("repository", ""))
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest", ""))
            ):
                raise ValueError(
                    "OCI verification needs an approved registry, repository and exact sha256 digest"
                )
            if (
                not isinstance(artifact.get("releaseReference"), str)
                or not artifact["releaseReference"]
            ):
                raise ValueError(
                    "artifact needs its literal authoritative release-record reference"
                )
            allowed = [
                f"{host}/{artifact['repository']}@{artifact['digest']}"
                for host in ("registry.redhat.io", "registry.access.redhat.com", "quay.io")
            ]
            if artifact["releaseReference"] not in allowed:
                raise ValueError(
                    "release-record artifact reference must identify the same repository and digest"
                )


def collect_verification(plan_path: str, output_path: str) -> dict:
    raw_plan = Path(plan_path).read_bytes()
    plan = json.loads(raw_plan)
    validate_plan(plan)
    output = Path(output_path)
    output.mkdir(parents=True, exist_ok=False)
    collector = Collector(output)
    release = plan["release"]
    body = (
        collector.read("release_record", release["url"], lambda: read_public(release["url"])) or b""
    )
    text = _Text()
    text.feed(body.decode("utf-8", errors="replace"))
    mention = release["version"] in " ".join(text.parts)
    packets = []
    for issue in plan["issues"]:
        start = len(collector.reads)
        repositories = [collector.repository(repo) for repo in issue.get("repositories", [])]
        artifacts = [
            collector.artifact(artifact, body, repositories)
            for artifact in issue.get("artifacts", [])
        ]
        packet = {
            "key": issue["key"],
            "release": release,
            "releaseMentionObserved": mention,
            "requirements": [
                {"statement": statement, "coverage": "requires_agent_inspection"}
                for statement in issue["requirements"]
            ],
            "repositories": repositories,
            "artifacts": artifacts,
            "reads": collector.reads[start:],
            "scope": "acquired_evidence_not_an_automatic_fix_verdict",
            "gaps": [],
        }
        packet["gaps"] = [gap for repo in repositories for gap in repo["gaps"]] + [
            gap for artifact in artifacts for gap in artifact["gaps"]
        ]
        if not body or not mention:
            packet["gaps"].append(
                "authoritative release record was not read or does not mention the reviewed version"
            )
        if not artifacts:
            packet["gaps"].append(
                "no exact released artifact requested; source ancestry is not artifact-byte provenance"
            )
        if not repositories:
            packet["gaps"].append("no implementation/repository evidence requested")
        packet["status"] = "incomplete" if packet["gaps"] else "collected_requires_inspection"
        write_json(output / f"{issue['key']}.json", packet)
        packets.append(packet)
    result = {
        "schemaVersion": 1,
        "collectedAt": now_iso(),
        "planSha256": hashlib.sha256(raw_plan).hexdigest(),
        "release": release,
        "reads": collector.reads,
        "keys": [p["key"] for p in packets],
        "sourceSystemWrites": [],
    }
    result["packetSha256"] = {
        packet["key"]: hashlib.sha256((output / f"{packet['key']}.json").read_bytes()).hexdigest()
        for packet in packets
    }
    result["codeSha256"] = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("verification.py", "forge.py")
    }
    (output / "plan.json").write_bytes(raw_plan)
    write_json(output / "index.json", result)
    return result


def load_verification(directory: str, keys, release: str) -> dict:
    """Check artifact integrity and release identity before attaching receipts."""
    root = Path(directory).resolve()
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    if index.get("release", {}).get("version") != release:
        raise ValueError("verification evidence is for a different reviewed release")
    if hashlib.sha256((root / "plan.json").read_bytes()).hexdigest() != index.get("planSha256"):
        raise ValueError("verification plan integrity mismatch")
    for receipt in index.get("reads", []):
        if receipt.get("status") != "read":
            continue
        path = (root / receipt["path"]).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(
            path.read_bytes()
        ).hexdigest() != receipt.get("sha256"):
            raise ValueError("verification raw receipt is missing, escaped or changed")
    result = {}
    for key in keys:
        path = root / f"{key}.json"
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != index.get("packetSha256", {}).get(key):
            raise ValueError(f"verification packet integrity mismatch: {key}")
        packet = json.loads(raw)
        if packet.get("key") != key or packet.get("release", {}).get("version") != release:
            raise ValueError("verification packet does not match the seed/reviewed release")
        result[key] = packet
    return result
