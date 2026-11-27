"""Exact read-only verification acquisition, including adverse provenance cases."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import Request

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage.forge import ForgeAdapterError  # noqa: E402
from bugtriage.model import load_export  # noqa: E402
from bugtriage.policy import evaluate, parse_assessment  # noqa: E402
from bugtriage.verification import (  # noqa: E402
    Collector,
    _Redirect,
    collect_verification,
    load_verification,
    public_url,
    validate_plan,
)

TARGET = "a" * 40
MERGE = "b" * 40
REPO = "owner/repo"


def file_payload(path="src/main.ts", body=b"corrective source"):
    return {
        "type": "file",
        "path": path,
        "size": len(body),
        "sha": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
        "encoding": "base64",
        "content": base64.b64encode(body).decode(),
    }


def plan():
    return {
        "release": {"version": "2.1.0", "url": "https://access.redhat.com/errata/example"},
        "issues": [
            {
                "key": "RHDHBUGS-2",
                "requirements": ["Default scenario works; not only an opt-in path"],
                "repositories": [
                    {
                        "repository": REPO,
                        "ref": "tags/2.1.0",
                        "paths": ["src/main.ts"],
                        "pullRequests": [7],
                    }
                ],
            }
        ],
    }


def api(path):
    if "/git/ref/" in path:
        return {"object": {"type": "commit", "sha": TARGET}}
    if "/contents/" in path:
        return file_payload()
    if "/pulls/" in path:
        return {
            "state": "closed",
            "merged": True,
            "merged_at": "2026-01-01",
            "merge_commit_sha": MERGE,
        }
    if "/compare/" in path:
        return {
            "status": "ahead",
            "base_commit": {"sha": MERGE},
            "merge_base_commit": {"sha": MERGE},
        }
    raise AssertionError(path)


def install_read_mocks(monkeypatch):
    monkeypatch.setattr(
        "bugtriage.verification.read_public",
        lambda url: b"Red Hat Developer Hub 2.1.0 has been released",
    )
    monkeypatch.setattr("bugtriage.verification.read_api", api)
    monkeypatch.setattr(
        "bugtriage.verification.read_diff", lambda repo, number: "-old behavior\n+new behavior"
    )


def test_collect_reads_final_source_diff_ancestry_and_keeps_acceptance_unassessed(
    tmp_path, monkeypatch
):
    install_read_mocks(monkeypatch)
    input_path = tmp_path / "plan.json"
    input_path.write_text(json.dumps(plan()))
    result = collect_verification(str(input_path), str(tmp_path / "verification"))
    packets = load_verification(str(tmp_path / "verification"), ["RHDHBUGS-2"], "2.1.0")
    packet = packets["RHDHBUGS-2"]
    repo = packet["repositories"][0]
    assert repo["revision"] == TARGET
    assert repo["files"][0]["status"] == "read"
    assert TARGET in repo["files"][0]["ref"]
    assert repo["pullRequests"][0]["containment"] == "contained"
    assert "new behavior" in repo["pullRequests"][0]["diff"]
    assert packet["requirements"][0]["coverage"] == "requires_agent_inspection"
    assert packet["status"] == "incomplete"  # No binary artifact supplied, not magically fixed.
    assert result["sourceSystemWrites"] == []


@pytest.mark.parametrize("kind", ["raw", "packet", "plan"])
def test_changed_saved_evidence_is_rejected(tmp_path, monkeypatch, kind):
    install_read_mocks(monkeypatch)
    input_path = tmp_path / "plan.json"
    input_path.write_text(json.dumps(plan()))
    root = tmp_path / "verification"
    index = collect_verification(str(input_path), str(root))
    path = root / (
        index["reads"][0]["path"]
        if kind == "raw"
        else "RHDHBUGS-2.json"
        if kind == "packet"
        else "plan.json"
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="integrity|changed"):
        load_verification(str(root), ["RHDHBUGS-2"], "2.1.0")


def test_wrong_reviewed_release_is_rejected(tmp_path, monkeypatch):
    install_read_mocks(monkeypatch)
    input_path = tmp_path / "plan.json"
    input_path.write_text(json.dumps(plan()))
    collect_verification(str(input_path), str(tmp_path / "verification"))
    with pytest.raises(ValueError, match="different reviewed release"):
        load_verification(str(tmp_path / "verification"), ["RHDHBUGS-2"], "2.2.0")


def test_annotated_tag_is_peeled_and_wrong_literal_commit_is_not_accepted(tmp_path, monkeypatch):
    def annotated(path):
        return (
            {"object": {"type": "tag", "sha": MERGE}}
            if "/git/ref/" in path
            else {"object": {"type": "commit", "sha": TARGET}}
        )

    monkeypatch.setattr("bugtriage.verification.read_api", annotated)
    collector = Collector(tmp_path)
    assert collector.resolve(REPO, "tags/2.1.0") == TARGET
    assert len(collector.reads) == 2
    monkeypatch.setattr("bugtriage.verification.read_api", lambda path: {"sha": TARGET})
    assert collector.resolve(REPO, MERGE) == ""


def test_bad_source_bytes_or_wrong_path_are_not_validated(tmp_path, monkeypatch):
    bad = file_payload()
    bad["sha"] = "0" * 40
    monkeypatch.setattr("bugtriage.verification.read_api", lambda path: bad)
    assert Collector(tmp_path).source(REPO, TARGET, "src/main.ts")["status"] == "invalid"
    monkeypatch.setattr("bugtriage.verification.read_api", lambda path: file_payload("wrong.ts"))
    assert Collector(tmp_path).source(REPO, TARGET, "src/main.ts")["status"] == "unavailable"


@pytest.mark.parametrize("tampered", [False, True])
def test_large_lockfile_uses_exact_named_blob_and_checks_original_identity(
    tmp_path, monkeypatch, tampered
):
    contents = file_payload("yarn.lock", b"pinned dependency data")
    blob = dict(contents)
    contents.update(encoding="none", content="")
    if tampered:
        blob = file_payload("yarn.lock", b"different dependency data")
    calls = []

    def read(path):
        calls.append(path)
        if "/contents/" in path:
            return contents
        assert path == f"repos/{REPO}/git/blobs/{contents['sha']}"
        return blob

    monkeypatch.setattr("bugtriage.verification.read_api", read)
    result = Collector(tmp_path).source(REPO, TARGET, "yarn.lock")
    assert result["status"] == ("invalid" if tampered else "read")
    assert len(calls) == 2


@pytest.mark.parametrize("state", ["diverged", "behind"])
def test_unincorporated_merge_is_not_treated_as_released(tmp_path, monkeypatch, state):
    install_read_mocks(monkeypatch)
    monkeypatch.setattr(
        "bugtriage.verification.read_api",
        lambda path: (
            {"status": state, "base_commit": {"sha": MERGE}, "merge_base_commit": {"sha": "c" * 40}}
            if "/compare/" in path
            else api(path)
        ),
    )
    repo = Collector(tmp_path).repository(plan()["issues"][0]["repositories"][0])
    assert repo["pullRequests"][0]["containment"] == "absent"


def test_closed_unmerged_pull_is_not_a_fix_and_failed_diff_is_not_empty(tmp_path, monkeypatch):
    install_read_mocks(monkeypatch)
    monkeypatch.setattr(
        "bugtriage.verification.read_api",
        lambda path: (
            {"state": "closed", "merged": False, "merged_at": None}
            if "/pulls/" in path
            else api(path)
        ),
    )

    def fail(*args):
        raise ForgeAdapterError("permission denied")

    monkeypatch.setattr("bugtriage.verification.read_diff", fail)
    collector = Collector(tmp_path)
    repo = collector.repository(plan()["issues"][0]["repositories"][0])
    assert repo["pullRequests"][0]["containment"] == "not_a_merged_fix"
    assert repo["pullRequests"][0]["diff"] is None
    assert any(read["status"] == "failed" for read in collector.reads)


@pytest.mark.parametrize(
    "url",
    [
        "http://access.redhat.com/a",
        "https://user:secret@access.redhat.com/a",
        "https://access.redhat.com/a?token=secret",
        "https://127.0.0.1/a",
        "https://access.redhat.com.attacker.invalid/a",
    ],
)
def test_public_reads_do_not_accept_credentials_or_arbitrary_hosts(url):
    with pytest.raises(ValueError, match="credential-free"):
        public_url(url)


def test_registry_redirect_capabilities_are_adapter_only_not_valid_plan_urls():
    url = "https://cdn01.quay.io/blob?X-Amz-Signature=example-temporary-capability"
    request = Request("https://registry.access.redhat.com/v2/image/blobs/sha256:digest")
    redirect = _Redirect().redirect_request(request, None, 302, "Found", {}, url)
    assert redirect.full_url == url
    with pytest.raises(ValueError):
        public_url(url)
    with pytest.raises(ValueError):
        _Redirect().redirect_request(
            request, None, 302, "Found", {}, "https://attacker.invalid/blob?token=example"
        )


def artifact_fixture(with_source=True):
    def encode(data):
        return json.dumps(data, separators=(",", ":")).encode()

    def digest(raw):
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    labels = {"vcs-ref": TARGET}
    if with_source:
        labels["vcs-url"] = "https://github.com/owner/repo.git"
    config = encode({"config": {"Labels": labels}})
    image = encode({"config": {"digest": digest(config)}})
    index = encode(
        {
            "manifests": [
                {"platform": {"os": "linux", "architecture": "amd64"}, "digest": digest(image)}
            ]
        }
    )
    objects = {digest(config): config, digest(image): image, digest(index): index}
    request = {
        "registry": "registry.access.redhat.com",
        "repository": "rhdh/image",
        "digest": digest(index),
        "releaseReference": f"registry.redhat.io/rhdh/image@{digest(index)}",
    }
    return request, objects


def test_oci_provenance_checks_all_digest_edges_and_source_identity(tmp_path, monkeypatch):
    request, objects = artifact_fixture()
    monkeypatch.setattr(
        "bugtriage.verification.read_public", lambda url: objects[url.rsplit("/", 1)[1]]
    )
    result = Collector(tmp_path).artifact(
        request, request["releaseReference"].encode(), [{"repository": REPO, "revision": TARGET}]
    )
    assert len(result["objects"]) == 3
    assert all(obj["digestMatches"] for obj in result["objects"])
    assert result["sourceBinding"] == "declared_source_matches"
    assert "not an independent build attestation" in result["bindingLimit"]


def test_revision_without_repository_is_looked_up_but_not_promoted_to_provenance(
    tmp_path, monkeypatch
):
    request, objects = artifact_fixture(with_source=False)
    monkeypatch.setattr(
        "bugtriage.verification.read_public", lambda url: objects[url.rsplit("/", 1)[1]]
    )
    monkeypatch.setattr("bugtriage.verification.read_api", lambda path: {"sha": MERGE})
    result = Collector(tmp_path).artifact(
        request, request["releaseReference"].encode(), [{"repository": REPO, "revision": TARGET}]
    )
    assert result["sourceBinding"] == "not_established"
    assert result["revisionLookups"][0]["resolved"] is False


@pytest.mark.parametrize("failure", ["digest", "release_reference", "source_revision"])
def test_oci_lookalikes_do_not_prove_release_source_binding(tmp_path, monkeypatch, failure):
    request, objects = artifact_fixture()
    monkeypatch.setattr(
        "bugtriage.verification.read_public",
        lambda url: b"{}" if failure == "digest" else objects[url.rsplit("/", 1)[1]],
    )
    result = Collector(tmp_path).artifact(
        request,
        b"another artifact"
        if failure == "release_reference"
        else request["releaseReference"].encode(),
        [{"repository": REPO, "revision": MERGE if failure == "source_revision" else TARGET}],
    )
    assert result["sourceBinding"] == "not_established"
    assert result["gaps"]


def test_mismatching_release_reference_and_path_traversal_are_rejected():
    value = plan()
    artifact, _ = artifact_fixture()
    artifact["releaseReference"] = "some text that occurs in an advisory"
    value["issues"][0]["artifacts"] = [artifact]
    with pytest.raises(ValueError, match="same repository and digest"):
        validate_plan(value)
    value = plan()
    value["issues"][0]["repositories"][0]["paths"] = ["../escape"]
    with pytest.raises(ValueError, match="invalid repository path"):
        validate_plan(value)


@pytest.mark.parametrize("containment", ["not_a_merged_fix", "absent", "unknown", "contained"])
def test_acquired_incorporation_checks_override_copied_positive_flags(containment):
    fixtures = Path(__file__).parent / "fixtures/bug_triage"
    key = "RHDHBUGS-1006"
    ticket = next(t for t in load_export(str(fixtures / "issues.json")) if t.key == key)
    assessment = parse_assessment(
        json.loads((fixtures / "assessments" / f"{key}.json").read_text())
    )
    assert evaluate(ticket, [], assessment, "2.1.0").action == "propose_close_fixed"
    receipt = {
        "repositories": [
            {
                "pullRequests": [
                    {
                        "ref": assessment.fix_pr,
                        "containment": containment,
                        "diff": "-wrong\n+correct",
                    }
                ]
            }
        ]
    }
    packet = evaluate(ticket, [], assessment, "2.1.0", verification=receipt)
    assert packet.action == (
        "propose_close_fixed" if containment == "contained" else "comment_only"
    )
