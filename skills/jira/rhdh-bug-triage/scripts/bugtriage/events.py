"""Consume one locally prepared event; atomically retain one receipt per issue revision."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .model import load_export
from .report import now_iso, write_json
from .run import build_sample_manifest, parse_as_of
from .selection import SelectionConfig


def required(record, field):
    if not isinstance(record, dict):
        raise ValueError("expected a JSON object")
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {field}")
    return value.strip()


def git(repo, *args, index=None):
    # Hook environments can point Git at the invoking worktree and index.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        env=env,
        timeout=60,
    )
    if result.returncode:
        raise ValueError(f"git {args[0]} failed while verifying the proposal")
    return result.stdout.decode().strip()


def proposal(event, dest, inputs, *, docs_only=False):
    repo = inputs / required(event, "checkout")
    repository = required(event, "repository")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("expected GitHub owner/repo")
    remote = git(repo, "remote", "get-url", "origin").removesuffix(".git")
    if remote not in {f"https://github.com/{repository}", f"git@github.com:{repository}"}:
        raise ValueError("checkout origin differs from the proposed repository")
    branch = required(event, "branch")
    git(repo, "check-ref-format", "--branch", branch)
    sha = required(event, "base")
    if (
        not re.fullmatch("[a-f0-9]{40}", sha)
        or git(repo, "rev-parse", f"refs/remotes/origin/{branch}") != sha
    ):
        raise ValueError("base does not match the recorded origin branch tip")
    patch = (inputs / required(event, "patch")).read_bytes()
    if hashlib.sha256(patch).hexdigest() != required(event, "patchHash"):
        raise ValueError("patch digest mismatch")
    if not patch.strip():
        raise ValueError("empty patch")
    patch_path = dest / "change.patch"
    patch_path.write_bytes(patch)
    with tempfile.TemporaryDirectory() as tmp:
        index = Path(tmp) / "index"
        git(repo, "read-tree", sha, index=index)
        git(repo, "apply", "--cached", str(patch_path.resolve()), index=index)
        if docs_only:
            names = git(
                repo, "diff", "--cached", "--name-only", "--no-renames", "-z", sha, index=index
            )
            if not all(
                Path(name).suffix.lower() in {".md", ".adoc", ".rst"}
                for name in names.rstrip("\0").split("\0")
            ):
                raise ValueError("scoped documentation proposal contains a non-documentation path")
            modes = git(repo, "diff", "--cached", "--raw", "--no-renames", sha, index=index)
            if any(
                mode not in {"000000", "100644"}
                for row in modes.splitlines()
                for mode in row.lstrip(":").split()[:2]
            ):
                raise ValueError("unexpected file mode in documentation proposal")
    verify = required(event, "verification")
    (dest / "VERIFY.md").write_text(f"Patch applies to {sha}.\n\n{verify}\n")
    return f"{required(event, 'repository')} {branch} at {sha}"


def dispatch(event, key, dest, inputs):
    kind = event["type"]
    if kind == "bug.updated":
        rows = load_export(str(inputs / required(event, "export")))
        if len(rows) != 1 or rows[0].key != key:
            raise ValueError("expected exactly one matching issue in the export")
        if rows[0].updated and rows[0].updated != event["revision"]:
            raise ValueError("event revision differs from issue update timestamp")
        sample = build_sample_manifest(
            rows,
            SelectionConfig(scope="all-open", current_release=required(event, "release")),
            parse_as_of(required(event, "asOf")),
            f"key = {key}",
        )
        write_json(dest / "sample.json", sample)
        return "investigate" if sample["tickets"] else "excluded"
    if kind == "support.updated":
        if event.get("sanitized") is not True:
            raise ValueError("support draft requires reviewed sanitized content")
        existing = event.get("existingBug")
        if existing and (
            not isinstance(existing, str) or not re.fullmatch(r"RHDHBUGS-\d+", existing)
        ):
            raise ValueError("invalid linked bug")
        review = required(event, "duplicateCheck")
        body = (
            f"Use {existing}"
            if existing
            else f"# {required(event, 'summary')}\n\n{required(event, 'observed')}\n\nExpected: {required(event, 'expected')}"
        )
        (dest / "BUG-DRAFT.md").write_text(f"{body}\n\nDuplicate check: {review}\n")
        return "existing_bug" if existing else "review_bug_draft"

    run = inputs / required(event, "triageRun")
    packets = json.loads((run / "01-triage/audit/packets.json").read_bytes())
    finding = next((row for row in packets["packets"] if row["key"] == key), {})
    docs_only = event.get("kind") == "docs"
    scoped_docs = (
        docs_only
        and finding.get("verdict") in {"needs_repro", "still_valid", "unclear"}
        and finding.get("handoff", {}).get("outcome") in {"docs", "documentation"}
        and not finding.get("verificationErrors")
        and event.get("repository")
        in {area.get("repository") for area in finding.get("fixPlan", {}).get("areas", [])}
    )
    if not scoped_docs and (
        finding.get("verdict") != "still_valid"
        or finding.get("investigation", {}).get("status") != "completed"
    ):
        raise ValueError("a completed still-valid triage finding is required")
    if not any(
        (run / "02-fixes" / outcome / key / "PLAN.md").is_file()
        for outcome in ("docs", "pull-requests")
    ):
        raise ValueError("no actionable fix handoff for this issue")
    base = proposal(event, dest, inputs, docs_only=docs_only)
    lines = [
        f"# {required(event, 'title')}",
        "",
        required(event, "body"),
        "",
        f"Base: {base}",
        required(event, "branchEvidence"),
        "",
        f"Documentation: {required(event, 'docsImpact')}",
        "",
        required(event, "maintenanceEvidence"),
    ]
    decisions = event.get("backports")
    if not isinstance(decisions, list):
        raise ValueError("expected per-branch backport decisions")
    seen = {event["branch"]}
    for number, decision in enumerate(decisions):
        branch = required(decision, "branch")
        action = required(decision, "decision")
        if branch in seen or action not in {"propose", "skip", "undetermined"}:
            raise ValueError("invalid or duplicate backport decision")
        seen.add(branch)
        lines.append(f"- {branch}: {action}. {required(decision, 'reason')}")
        if action == "propose":
            directory = dest / "backports" / str(number + 1)
            directory.mkdir(parents=True)
            lines.append(
                proposal(
                    {**decision, "checkout": event["checkout"], "repository": event["repository"]},
                    directory,
                    inputs,
                    docs_only=docs_only,
                )
            )
    write_json(
        dest / "proposal.json",
        {
            **{name: event.get(name) for name in ("repository", "branch", "kind", "title")},
            "backports": [
                {"branch": item["branch"], "decision": item["decision"]} for item in decisions
            ],
        },
    )
    (dest / "PROPOSAL.md").write_text("\n".join(lines) + "\n")
    return "review_patch"


def command_event(args):
    source = Path(args.input).resolve()
    event = json.loads(source.read_bytes())
    kind = required(event, "type")
    project = {
        "bug.updated": "RHDHBUGS",
        "support.updated": "RHDHSUPP",
        "fix.requested": "RHDHBUGS",
    }.get(kind)
    key = required(event, "key")
    if not project or not re.fullmatch(project + r"-\d+", key):
        raise ValueError("invalid event type or issue key")
    revision = required(event, "revision")
    group = {
        "bug.updated": "01-triage",
        "support.updated": "03-support-intake",
        "fix.requested": "02-fixes",
    }[kind]
    result = publish(
        args.out,
        group,
        key,
        revision,
        event,
        lambda dest: dispatch(event, key, dest, source.parent),
    )
    if kind == "fix.requested":
        from .layout import refresh_review

        refresh_review(Path(args.out))
    return result


def command_trigger(args):
    """Turn a delivered Jira notification into a private, one-item work request."""
    raw = json.loads(Path(args.input).read_bytes())
    name = required(raw, "webhookEvent")
    if name not in {"jira:issue_created", "jira:issue_updated"}:
        raise ValueError("expected a Jira issue created or updated notification")
    issue = raw.get("issue")
    key = required(issue, "key")
    if not re.fullmatch(r"(RHDHSUPP|RHDHBUGS)-\d+", key):
        raise ValueError("outside triage projects")
    revision = required(issue.get("fields"), "updated")
    support = key.startswith("RHDHSUPP-")
    event = {
        "type": "support.updated" if support else "bug.updated",
        "key": key,
        "revision": revision,
    }

    def enqueue(dest):
        write_json(dest / "request.json", event)
        return "prepare_support_draft" if support else "investigate_bug"

    return publish(args.out, "requests", key, revision, event, enqueue)


def publish(out, group, key, revision, event, produce):
    kind = event["type"]
    token = hashlib.sha256(revision.encode()).hexdigest()
    root = Path(out) / group / "events" / key
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / token
    digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()

    def replay():
        receipt = json.loads((target / "receipt.json").read_text())
        if receipt["inputHash"] != digest:
            raise ValueError("conflicting payload for the same revision")
        print(target)
        return 0

    if target.exists():
        return replay()
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir(mode=0o700)
        outcome = produce(stage)
        write_json(
            stage / "receipt.json",
            dict(
                type=kind,
                key=key,
                revision=revision,
                outcome=outcome,
                inputHash=digest,
                processedAt=now_iso(),
            ),
        )
        try:
            stage.rename(target)
        except OSError:
            if target.is_dir():
                return replay()
            raise
    print(target)
    return 0
