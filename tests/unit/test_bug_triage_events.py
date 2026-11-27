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
    if kind == "docs":
        template = repo / ".github/pull_request_template.md"
        template.parent.mkdir()
        template.write_text("## Description\n\n## Verification\n\n- [ ] Docs reviewed\n")
        git("add", ".github")
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
        testCommands=["git diff --check"],
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
        backports=[
            dict(
                **change,
                branch="stable",
                decision="assess",
                reason="Same component",
                impact="moderate",
                workaround="costly",
                supportStatus="supported",
                supportSource="https://example.org/release-policy",
                compatibility="compatible",
                compatibilityEvidence="The previous configuration and defaults passed on stable.",
                impactEvidence="Rebuilding the affected component interrupts service.",
            )
        ],
    )
    issue = {
        "key": event["key"],
        "fields": {
            "comment": {"total": 1, "comments": [{"id": "9", "body": "Startup fails on stable."}]}
        },
    }
    (tmp_path / "issue.json").write_text(json.dumps([issue]))
    event["commentExport"] = "issue.json"
    event["commentReview"] = [
        {
            "id": "9",
            "excerpt": "Startup fails",
            "scope": "stable",
            "observation": "Startup failure reproduced on stable.",
            "impact": "moderate",
        }
    ]
    if kind == "docs":
        event["body"] = (
            "## Description\n\nExplain the new title.\n\n## Verification\n\n"
            "<!-- triage-verification -->\n\n- [ ] Docs reviewed"
        )
        event["verificationLog"] = "main output: </details>"
        event["backports"][0]["verificationLog"] = "stable output"
        checks = {}
        for field in ("behaviorCheck", "docsCheck"):
            path = tmp_path / f"{field}.log"
            path.write_text(f"Passed {field}")
            checks[field] = {
                "base": base,
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        event["backports"][0]["guidance"] = {
            "status": "verified_gap",
            "basis": "Verified the affected behavior and missing guidance on stable.",
            **checks,
        }
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
    if accepted:
        drafts = list((tmp_path / "run").rglob("PROPOSAL.md"))
        assert len(drafts) == 2
        for draft in drafts:
            body = draft.read_text()
            if kind == "docs":
                assert body.index("## Description") < body.index("## Verification")
                assert body.index("Title fixture checked") < body.index("<details>")
                assert body.index("</details>") < body.index("- [ ] Docs reviewed")
                assert "### How this was tested" not in body
                assert "<!-- triage-verification -->" not in body
                log = (
                    "stable output"
                    if "backports" in draft.parts
                    else "main output: &lt;/details&gt;"
                )
                assert f"<pre>{log}</pre>" in body
            else:
                assert "### How this was tested\n\n```bash\ngit diff --check\n```" in body
                assert "<details>" not in body
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


@pytest.mark.parametrize(
    ("impact", "workaround", "expected"),
    [
        ("low", "easy_verified", "skip"),
        ("moderate", "easy_verified", "skip"),
        ("moderate", "costly", "propose"),
        ("high", "none_verified", "propose"),
        ("high", "easy_verified", "undetermined"),
        ("unknown", "unknown", "undetermined"),
    ],
)
def test_branch_backport_decision(impact, workaround, expected):
    from bugtriage.events import backport_decision

    record = dict(
        decision="assess",
        reason="Maintained affected branch",
        impact=impact,
        workaround=workaround,
        impactEvidence="Recorded scope and mitigation check",
    )
    assert backport_decision(record)[0] == expected
    assert backport_decision({**record, "decision": "skip"})[0] == "skip"
    assert backport_decision({**record, "impactEvidence": ""})[0] == "undetermined"


def test_comment_review_requires_full_thread_and_grounded_excerpts(tmp_path):
    from bugtriage.events import evidenced_backport, reviewed_comments

    path = tmp_path / "issue.json"
    key = "RHDHBUGS-1"
    thread = {"total": 1, "comments": [{"id": "7", "body": "It blocks startup on stable."}]}
    path.write_text(json.dumps([{"key": key, "fields": {"comment": thread}}]))
    row = {
        "id": "7",
        "scope": "stable",
        "excerpt": "blocks startup",
        "observation": "Blocks startup.",
        "impact": "high",
    }
    event = {"commentExport": "issue.json", "commentReview": [row]}
    seen = reviewed_comments(event, key, tmp_path)
    record = {
        "decision": "assess",
        "branch": "stable",
        "reason": "Supported and affected.",
        "supportStatus": "supported",
        "supportSource": "https://example.org/release-policy",
        "compatibility": "compatible",
        "compatibilityEvidence": "Existing configurations still pass.",
        "impact": "unknown",
        "workaround": "costly",
    }
    assert evidenced_backport(record, seen, False, tmp_path)[0] == "propose"
    for override, expected in [
        ({"supportStatus": "unsupported"}, "skip"),
        ({"supportSource": ""}, "human_review"),
        ({"compatibility": "breaking"}, "skip"),
        ({"compatibilityEvidence": ""}, "human_review"),
    ]:
        for docs in (False, True):
            assert evidenced_backport({**record, **override}, seen, docs, tmp_path)[0] == expected
    assert (
        evidenced_backport(record, [{**row, "scope": "older"}], False, tmp_path)[0]
        == "human_review"
    )
    assert evidenced_backport(record, seen, True, tmp_path)[0] == "human_review"
    assert (
        reviewed_comments(
            {**event, "commentReview": [{**row, "excerpt": "confirmed workaround"}]}, key, tmp_path
        )
        is None
    )
    thread["total"] = 2
    path.write_text(json.dumps([{"key": key, "fields": {"comment": thread}}]))
    assert reviewed_comments(event, key, tmp_path) is None
    assert evidenced_backport(record, None, False, tmp_path)[0] == "human_review"


@pytest.mark.parametrize("done_case", [False, True])
def test_next_resumes_until_finish_then_advances(tmp_path, monkeypatch, capsys, done_case):
    from bugtriage import cycle

    keys = [f"RHDHBUGS-{i}" for i in range(1, 11)]
    monkeypatch.setattr(cycle, "search_acli", lambda *a, **kw: [{"key": k} for k in keys])
    fetched = []

    def fetch(jql, **kwargs):
        batch = jql.split("(", 1)[1].split(")", 1)[0].split(", ")
        fetched.append(batch)
        return {
            "provenance": {},
            "issues": [
                {
                    "key": k,
                    "fields": {
                        "summary": "Fixture",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Closed" if done_case and k == keys[-1] else "Open"},
                        "labels": [],
                        "issuelinks": [],
                    },
                }
                for k in batch
            ],
        }

    monkeypatch.setattr(cycle, "export_from_acli", fetch)
    args = ["next", "--root", str(tmp_path), "--current-release", "2.1.0"]

    def advance():
        assert main(args) == 0
        return json.loads(capsys.readouterr().out)

    def finish(batch, legacy=False):
        review = Path(batch["review"])
        audit = review / "01-triage/audit"
        audit.mkdir(parents=True)
        sample = json.loads(Path(batch["sample"]).read_bytes())
        ordered = [row["key"] for row in sample["tickets"]]
        assert set(ordered) | {item["key"] for item in sample["excluded"]} == set(batch["keys"])
        digest = hashlib.sha256((tmp_path / "private/bugs.json").read_bytes()).hexdigest()
        coverage = {} if legacy else {"inventoryHash": digest}
        (audit / "selection.json").write_text(json.dumps(sample))
        (audit / "packets.json").write_text(
            json.dumps(
                {
                    "currentRelease": "2.1.0",
                    "meta": {"coverage": coverage},
                    "packets": [
                        {"key": k, "summary": "Fixture", "investigation": {"status": "completed"}}
                        for k in ordered
                    ],
                }
            )
        )
        (review / "run.json").write_text("{}")
        if not legacy:
            assert advance()["batch"] == batch["batch"]
        (tmp_path / "proof.md").write_text("checked")
        rows = [
            dict(
                key=k,
                stage="blocked",
                finding="Needs reproduction.",
                verification="Checked.",
                next="Supply fixture.",
                evidence="proof.md",
                blocker="Missing fixture.",
            )
            for k in ordered
        ]
        source = tmp_path / "results.json"
        source.write_text(json.dumps(rows))
        finish_args = ["finish", "--input", str(source), "--out", str(review)]
        assert main(finish_args) == 0
        return finish_args

    first = advance()
    assert first["batch"] == 1 and first["keys"] == keys[:5]
    assert advance()["state"] == "resume"
    finish(first, legacy=True)
    assert main(args) == 2
    inventory = tmp_path / "private/bugs.json"
    source = tmp_path / "original.json"
    source.write_bytes(inventory.read_bytes())
    inventory.unlink()
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({**json.loads(source.read_bytes()), "keys": keys[::-1]}))
    assert main([*args, "--inventory", str(wrong)]) == 2
    assert not inventory.exists()
    assert main([*args, "--inventory", str(source)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["batch"] == 2 and second["keys"] == keys[5:]
    assert advance()["batch"] == 2
    finish_args = finish(second)
    index = tmp_path / "START-HERE.md"
    original = index.read_bytes()
    assert f"{10 - int(done_case)} issues reviewed across 2 completed batches" in index.read_text()
    for page in [index, Path(second["review"]) / "START-HERE.md"]:
        assert ("Excluded after screening" in page.read_text()) == done_case
        if done_case:
            assert (
                f"[{keys[-1]}](https://redhat.atlassian.net/browse/{keys[-1]})" in page.read_text()
            )
            assert "done" in page.read_text().lower()
    assert "0 of 10 inventory entries remain" in index.read_text()
    for key in keys:
        assert index.read_text().count(f"[{key}]") == 1
    assert main(finish_args) == 0
    assert index.read_bytes() == original
    assert advance() == advance() == {"state": "complete", "accounted": 10}
    assert fetched == [keys[:5], keys[5:]]
    assert (
        main(
            [
                "progress",
                "--inventory",
                str(inventory),
                "--run",
                first["review"],
                "--run",
                second["review"],
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["pending"] == []
