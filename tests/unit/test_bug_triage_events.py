"""Exercise local review events through the installed CLI surface."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
sys.path.insert(0, str(SCRIPTS))
from bugtriage.cli import main  # noqa: E402


def consume(tmp_path, event):
    source = tmp_path / "event.json"
    source.write_text(json.dumps(event))
    return main(["event", "--input", str(source), "--out", str(tmp_path / "run")])


def test_support_replay_conflict_and_recovery(tmp_path):
    event = dict(
        type="support.updated",
        key="RHDHSUPP-1",
        revision="r1",
        summary="Missing title",
        observed="Blank title",
        expected="Visible title",
        duplicateCheck="Compared the current title issues.",
    )
    assert consume(tmp_path, event) == 2
    event["sanitized"] = True
    assert consume(tmp_path, event) == 0
    assert consume(tmp_path, event) == 0
    assert consume(tmp_path, {**event, "expected": "Other"}) == 2
    drafts = list(tmp_path.rglob("BUG-DRAFT.md"))
    assert len(drafts) == 1 and "Visible title" in drafts[0].read_text()


@pytest.mark.parametrize(
    "kind,filename,executable,accepted",
    [
        (None, "title", False, True),
        ("docs", "guide.md", False, True),
        ("docs", "title.py", False, False),
        ("docs", "guide.md", True, False),
    ],
)
def test_patch_and_backport_check_without_changing_checkout(
    tmp_path, monkeypatch, kind, filename, executable, accepted
):
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    repo = tmp_path / "fixture"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()

    git("init", "-q")
    git("remote", "add", "origin", "https://github.com/example/fixture.git")
    (repo / filename).write_text("old\n")
    git("add", filename)
    git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    for branch in ("main", "stable"):
        git("update-ref", f"refs/remotes/origin/{branch}", base)
    (repo / filename).write_text("new\n")
    if executable:
        (repo / filename).chmod(0o755)
    patch = subprocess.check_output(["git", "-C", str(repo), "diff"])
    (tmp_path / "change.patch").write_bytes(patch)
    change = dict(
        base=base,
        patch="change.patch",
        patchHash=hashlib.sha256(patch).hexdigest(),
        verification="Title fixture checked",
    )
    event = dict(
        **change,
        type="fix.requested",
        key="RHDHBUGS-1",
        kind=kind,
        revision="1",
        checkout="fixture",
        repository="example/fixture",
        branch="main",
        branchEvidence="CONTRIBUTING",
        title="Restore title",
        body="Restore title rendering",
        docsImpact="No public interface change",
        maintenanceEvidence="stable supported",
        backports=[dict(**change, branch="stable", decision="propose", reason="Same component")],
    )
    audit = tmp_path / "review/01-triage/audit"
    audit.mkdir(parents=True)
    # Keep a legacy docs-folder fixture alongside the new shared PR queue.
    case = tmp_path / "review/02-fixes" / ("pull-requests" if kind else "docs") / "RHDHBUGS-1"
    case.mkdir(parents=True)
    (case / "PLAN.md").write_text("Restore title")
    (audit / "packets.json").write_text(
        json.dumps(
            {
                "packets": [
                    {
                        "key": "RHDHBUGS-1",
                        "verdict": "needs_repro" if kind else "still_valid",
                        "investigation": {"status": "blocked" if kind else "completed"},
                        "handoff": {"outcome": "docs" if kind else "pull_request"},
                        "fixPlan": {"areas": [{"repository": "example/fixture"}]},
                    }
                ]
            }
        )
    )
    event["triageRun"] = "review"
    status = git("status", "--porcelain")
    assert consume(tmp_path, {**event, "patchHash": "wrong"}) == 2
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "foreign.git"))
    assert consume(tmp_path, event) == (0 if accepted else 2)
    monkeypatch.delenv("GIT_DIR")
    assert len(list((tmp_path / "run").rglob("change.patch"))) == (2 if accepted else 0)
    assert git("status", "--porcelain") == status
    assert git("diff", "--cached") == ""


def test_bug_event_respects_updated_revision_and_exclusion(tmp_path):
    (tmp_path / "bug.json").write_text(
        json.dumps(
            [
                {
                    "key": "RHDHBUGS-7",
                    "fields": {
                        "status": {"name": "Done", "statusCategory": {"key": "done"}},
                        "updated": "2026-11-21",
                    },
                }
            ]
        )
    )
    event = dict(
        type="bug.updated",
        key="RHDHBUGS-7",
        revision="2026-11-20",
        export="bug.json",
        release="2.1.0",
        asOf="2026-11-21",
    )
    assert consume(tmp_path, event) == 2
    assert consume(tmp_path, {**event, "revision": "2026-11-21"}) == 0
    manifest = json.loads(next(tmp_path.rglob("sample.json")).read_text())
    assert manifest["excluded"][0]["key"] == "RHDHBUGS-7"


def test_inventory_batches_and_progress(tmp_path, monkeypatch, capsys):
    from bugtriage import cli

    keys = [f"RHDHBUGS-{number}" for number in range(1, 8)]
    monkeypatch.setattr(cli, "search_acli", lambda jql, fields: [{"key": k} for k in keys])
    fetched = []

    def fetch(jql, field_names):
        import re

        batch = re.findall(r"RHDHBUGS-\d+", jql)
        fetched.append(batch)
        return {"issues": [{"key": k} for k in batch], "provenance": {"jql": jql}}

    monkeypatch.setattr(cli, "export_from_acli", fetch)
    inventory = str(tmp_path / "inventory.json")
    assert main(["inventory", "--project", "RHDHBUGS", "--out", inventory]) == 0
    for batch in (1, 2):
        path = tmp_path / f"export-{batch}.json"
        assert (
            main(["fetch", "--inventory", inventory, "--batch", str(batch), "--out", str(path)])
            == 0
        )
        export = json.loads(path.read_text())
        assert (
            export["provenance"]["inventoryHash"]
            == hashlib.sha256(Path(inventory).read_bytes()).hexdigest()
        )
    assert fetched == [keys[:5], keys[5:]]
    audit = tmp_path / "review/01-triage/audit"
    audit.mkdir(parents=True)
    (audit / "selection.json").write_text(json.dumps({"excluded": [{"key": keys[1]}]}))
    (audit / "packets.json").write_text(
        json.dumps(
            {
                "meta": {"coverage": export["provenance"]},
                "packets": [{"key": keys[0], "investigation": {"status": "completed"}}],
            }
        )
    )
    capsys.readouterr()
    args = ["progress", "--inventory", inventory, "--run", str(tmp_path / "review")]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        "completed": keys[:1],
        "excluded": keys[1:2],
        "blocked": [],
        "pending": keys[2:],
    }
    assert main(args + args[-2:]) == 2


def test_webhook_replay_retains_only_routing_fields(tmp_path):
    source = tmp_path / "incoming.json"
    source.write_text(
        json.dumps(
            {
                "webhookEvent": "jira:issue_updated",
                "issue": {
                    "key": "RHDHSUPP-2",
                    "fields": {"updated": "revision-1", "description": "private sentinel"},
                },
            }
        )
    )
    args = ["trigger", "--input", str(source), "--out", str(tmp_path / "run")]
    assert main(args) == main(args) == 0
    requests = list(tmp_path.rglob("request.json"))
    assert len(requests) == 1
    assert json.loads(requests[0].read_text()) == {
        "type": "support.updated",
        "key": "RHDHSUPP-2",
        "revision": "revision-1",
    }
