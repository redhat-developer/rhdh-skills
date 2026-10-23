"""Behaviour tests for the overlay PR pipeline classifier."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "skills" / "plugins" / "rhdh-overlay" / "scripts" / "pr-pipeline.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("pr_pipeline", SCRIPT)
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)

HEAD = "2026-10-20T10:00:00Z"
BEFORE = "2026-10-19T10:00:00Z"
AFTER = "2026-10-20T11:00:00Z"
LATER = "2026-10-20T12:00:00Z"


def comment(login, body, at=AFTER, association="MEMBER", url=None):
    return {
        "author": {"login": login},
        "authorAssociation": association,
        "body": body,
        "createdAt": at,
        "url": url,
    }


def review(login, state, at=AFTER, body=""):
    return {"author": {"login": login}, "state": state, "submittedAt": at, "body": body}


def publish_report(ok=True, at=AFTER, starts_e2e=False):
    outcome = "completed with success" if ok else "completed with failure"
    trigger = "\nRunning e2e tests\n/test e2e-ocp-helm" if starts_e2e else ""
    return comment(
        "github-actions",
        f"[Publish workflow](https://github.com/o/r/actions/runs/1) has {outcome}.{trigger}",
        at=at,
        association="CONTRIBUTOR",
    )


def smoke_report(ok=True, at=AFTER):
    verdict = "passed" if ok else "failed"
    return comment(
        "github-actions",
        f":white_check_mark: [Smoke tests workflow](https://github.com/o/r/actions/runs/2) {verdict}.",
        at=at,
        association="CONTRIBUTOR",
    )


SONAR_URL = "https://github.com/o/r/pull/4444#issuecomment-1"
DIAGNOSIS_URL = "https://github.com/o/r/pull/4444#issuecomment-2"


def sonar_report(failed=True, at=AFTER):
    verdict = "Quality Gate failed" if failed else "Quality Gate passed"
    return comment(
        "sonarqubecloud",
        f"## **{verdict}**\nFailed conditions\n28.6% Duplication on New Code",
        at=at,
        association="NONE",
        url=SONAR_URL,
    )


def diagnosis_report(verdict="This is the PR's fault", at=AFTER, url=None, details="pr_regression"):
    return comment(
        "fullsend-ai-review",
        "<!-- ci-diagnose -->\n### \U0001f50d CI Diagnosis\n\n"
        f"**Verdict:** {verdict}\n\n"
        f"<details>\n<summary>\u274c <code>ci/prow/e2e-ocp-helm</code> \u2014 {details}</summary>\n"
        "</details>",
        at=at,
        association="CONTRIBUTOR",
        url=url or DIAGNOSIS_URL,
    )


def diagnosis_review(at=AFTER, body=None):
    """The review the diagnose agent raises when it wants its findings implemented."""
    return review(
        "fullsend-ai-review",
        "CHANGES_REQUESTED",
        at=at,
        body=body
        or (
            "CI diagnosis found PR-regression failures on `abc123`.\n\n"
            "These findings are caused by this PR. Implement each suggested fix."
        ),
    )


def e2e_report(passed=True, at=AFTER, counts=(7, 16, 0, 4)):
    heading = "✅ Passed E2E Tests (-w rbac)" if passed else "❌ Failed E2E Tests (-w rbac)"
    passed_count, failed, flaky, skipped = counts
    summary = f"Passed: {passed_count} | Failed: {failed} | Flaky: {flaky} | Skipped: {skipped}"
    return comment(
        "rhdh-test-bot",
        f"### {heading}\n{summary}",
        at=at,
        association="NONE",
    )


def fix_finished(ok=False, at=AFTER, run="39778417478", post_script=False):
    if post_script:
        body = (
            "\u26a0\ufe0f **Post-fix script failed** \u2014 Push rejected (exit code 1)\n\n"
            "**Workflow run:** https://github.com/o/r/actions/runs/" + run
        )
    else:
        marker = "\u2705 Success" if ok else "\u274c Failure"
        body = (
            f"\U0001f916 Finished Fix \u00b7 {marker}\n\n"
            f"**Workflow run:** https://github.com/o/r/actions/runs/{run}"
        )
    return comment("fullsend-ai-coder", body, at=at, association="CONTRIBUTOR")


def make_pr(**overrides):
    pr = {
        "number": 4444,
        "title": "fix(e2e): something",
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": "abc123",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "BLOCKED",
        "commits": [{"committedDate": HEAD}],
        "files": [{"path": "workspaces/rbac/e2e-tests/tests/specs/rbac.spec.ts"}],
        "comments": [],
        "reviews": [],
        "statusCheckRollup": [],
    }
    pr.update(overrides)
    return pr


# Every fixture is dated relative to HEAD, and the classifier compares against a
# clock to decide staleness. Pinning the clock one day after HEAD keeps the
# suite independent of the wall-clock date it runs on.
NOW = "2026-10-21T10:00:00Z"


def classify(pr, **kwargs):
    kwargs.setdefault("now", pipeline.parse_time(NOW))
    return pipeline.classify(pr, **kwargs)


def test_open_findings_need_a_fix_run():
    pr = make_pr(reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED")])

    assert classify(pr)["stage"] == "code"
    assert (
        classify(pr)["command"]
        == "/fs-fix can you address the review threads and rebase this PR branch"
    )


def fix_started(at=AFTER):
    return comment(
        "fullsend-ai-coder",
        "<!-- fullsend:agent-status:39770670549 -->\n"
        "\U0001f916 Fix \u00b7 Started 11:28 AM UTC\n\nCommit: `ce68fe8` \u00b7 "
        "[View workflow run \u2192](https://github.com/o/r/actions/runs/39770670549)",
        at=at,
        association="CONTRIBUTOR",
    )


def test_a_fix_run_in_flight_is_not_asked_for_again():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[
            comment("a-reviewer", "/fs-fix can you address the review threads", at=BEFORE),
            fix_started(),
        ],
    )

    result = classify(pr)
    assert result["stage"] == "fixing"
    assert result["command"] == "none"


def test_a_finished_fix_clears_the_in_flight_stage():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[
            fix_started(at=BEFORE),
            comment(
                "fullsend-ai-coder",
                "\U0001f916 Finished Fix \u00b7 \u2705 Success",
                at=AFTER,
                association="CONTRIBUTOR",
            ),
        ],
    )

    assert classify(pr)["stage"] == "gate"


def test_a_fix_that_started_after_the_findings_and_failed_reports_a_retry():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[
            fix_started(at=BEFORE),
            comment(
                "fullsend-ai-coder",
                "\U0001f916 Finished Fix \u00b7 \u274c Failure",
                at=AFTER,
                association="CONTRIBUTOR",
            ),
        ],
    )

    result = classify(pr)
    assert result["stage"] == "code"
    assert any("the last fix run failed" in note for note in result["notes"])


def test_a_fix_run_after_the_findings_clears_the_code_stage():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[
            comment(
                "fullsend-ai-coder",
                "🤖 Finished Fix · ✅ Success\nCommit: `abc123`",
                at=AFTER,
                association="CONTRIBUTOR",
            )
        ],
    )

    assert classify(pr)["stage"] == "gate"


def test_a_failed_fix_run_is_reported_not_treated_as_a_fix():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[
            comment(
                "fullsend-ai-coder",
                "🤖 Finished Fix · ❌ Failure (provider create failed)",
                at=AFTER,
                association="CONTRIBUTOR",
            )
        ],
    )

    result = classify(pr)
    assert result["stage"] == "code"
    assert any("the last fix run failed" in note for note in result["notes"])


def test_a_bot_cannot_satisfy_the_trusted_gate():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "APPROVED")],
        comments=[comment("fullsend-ai-coder", "/ok-to-test", association="CONTRIBUTOR")],
    )

    assert classify(pr)["stage"] == "gate"


def test_a_member_comment_satisfies_the_gate():
    pr = make_pr(comments=[comment("a-reviewer", "/ok-to-test")])

    assert classify(pr)["stage"] == "publish"


def test_a_missing_publish_for_the_head_asks_for_one():
    pr = make_pr(
        comments=[comment("a-reviewer", "/ok-to-test"), publish_report(ok=True, at=BEFORE)]
    )

    result = classify(pr)
    assert result["stage"] == "publish"
    assert result["command"] == "/publish"


def test_a_stale_head_asks_for_a_rebase_before_publishing():
    pr = make_pr(
        comments=[comment("a-reviewer", "/ok-to-test"), publish_report(ok=True, at=BEFORE)]
    )
    twenty_days_later = pipeline.parse_time(HEAD) + pipeline.timedelta(days=20)

    result = classify(pr, now=twenty_days_later)
    assert result["stage"] == "publish"
    assert result["command"] == pipeline.FIX_REQUEST
    assert any("20 days old" in note for note in result["notes"])
    assert any("still match main" in note for note in result["notes"])


def test_a_stale_head_asks_for_a_rebase_before_rerunning_the_tests():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=HEAD, starts_e2e=True),
            smoke_report(ok=True, at=AFTER),
            e2e_report(passed=False, at=AFTER),
            diagnosis_report(verdict="flake, unrelated to this PR", details="flake"),
        ]
    )
    twenty_days_later = pipeline.parse_time(HEAD) + pipeline.timedelta(days=20)

    result = classify(pr, now=twenty_days_later)
    assert result["command"] == pipeline.FIX_REQUEST


def test_a_recent_head_is_not_stale():
    pr = make_pr(
        comments=[comment("a-reviewer", "/ok-to-test"), publish_report(ok=True, at=BEFORE)]
    )

    result = classify(pr, now=pipeline.parse_time(HEAD) + pipeline.timedelta(days=2))
    assert result["command"] == "/publish"
    assert not any("days old" in note for note in result["notes"])


def test_a_stale_mergeable_head_is_flagged_but_still_mergeable():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=HEAD, starts_e2e=True),
            smoke_report(ok=True, at=AFTER),
            e2e_report(passed=True, at=AFTER),
        ],
        mergeStateStatus="CLEAN",
    )
    twenty_days_later = pipeline.parse_time(HEAD) + pipeline.timedelta(days=20)

    result = classify(pr, now=twenty_days_later)
    assert result["stage"] == "mergeable"
    assert result["command"] == "merge"
    assert any("20 days old" in note for note in result["notes"])


def test_a_running_publish_check_is_not_actionable():
    pr = make_pr(
        comments=[comment("a-reviewer", "/ok-to-test")],
        statusCheckRollup=[{"name": "publish", "state": "PENDING"}],
    )

    assert classify(pr)["stage"] == "publishing"
    assert classify(pr)["command"] == "none"


def test_a_head_that_passed_every_gate_is_mergeable():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=HEAD, starts_e2e=True),
            smoke_report(ok=True, at=AFTER),
            e2e_report(passed=True, at=AFTER),
        ],
        mergeStateStatus="CLEAN",
    )

    assert classify(pr)["stage"] == "mergeable"
    assert classify(pr)["command"] == "merge"


def test_a_passing_run_older_than_the_head_is_not_evidence():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=True, at=BEFORE),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "publish"
    assert result["command"] == "/publish"


def test_a_branch_with_no_changes_is_superseded():
    pr = make_pr(
        files=[],
        comments=[comment("a-reviewer", "/ok-to-test", at=BEFORE), e2e_report(passed=False)],
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
    )

    result = classify(pr)
    assert result["stage"] == "superseded"
    assert result["command"] == "none"
    assert any("nothing to merge" in note for note in result["notes"])


def test_a_test_rerun_after_the_failure_is_waited_on():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=False, at=AFTER),
            comment("a-reviewer", "/test e2e-ocp-helm", at=LATER),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "e2e"
    assert result["command"] == "none"


def test_a_rerun_requested_after_the_failure_is_waited_on():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=False, at=AFTER),
            comment("a-reviewer", "/publish", at=LATER),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "publishing"
    assert result["command"] == "none"


def test_a_ci_diagnosis_becomes_a_request_to_implement_its_findings():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=False, at=BEFORE),
            diagnosis_report(),
        ],
        reviews=[diagnosis_review()],
    )

    result = classify(pr)
    assert result["stage"] == "diagnosed"
    assert result["command"] == (
        f"/fs-fix can you incorporate the findings in {DIAGNOSIS_URL} to fix the e2e tests?"
    )


def test_a_flake_diagnosis_asks_for_a_re_run_instead_of_another_diagnosis():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=False, at=AFTER),
            diagnosis_report(verdict="Intermittent OIDC login flake. Re-running should pass."),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "e2e-failed"
    # A flake needs the tests run again, not the plugin images rebuilt.
    assert result["command"] == "/test e2e-ocp-helm"
    assert "the diagnosis expects a re-run to pass" in result["notes"]


def test_a_diagnosis_that_blames_something_else_is_left_alone():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=False, at=AFTER),
            diagnosis_report(
                verdict="Not this PR\u2019s fault \u2014 a pre-existing RHDH auth session issue.",
                details="pre_existing",
            ),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "e2e-failed"
    assert result["command"] == "none"
    assert "the diagnosis does not blame this PR" in " ".join(result["notes"])


def test_a_verdict_that_quotes_another_verdict_is_not_actionable():
    """A diagnosis mentions the other verdicts in its previous-diagnosis prose."""
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=True, at=BEFORE),
            diagnosis_report(
                verdict="All curated checks are now passing. No action needed.",
                details="pr_regression",
            ),
        ]
    )

    result = classify(pr)
    assert result["stage"] != "diagnosed"
    assert "incorporate the findings" not in result["command"]


def test_a_fix_run_after_the_diagnosis_answers_it():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            diagnosis_report(at=HEAD),
            fix_started(),
        ],
        reviews=[diagnosis_review(at=HEAD)],
    )

    assert classify(pr)["stage"] == "fixing"


def test_a_diagnosis_older_than_the_head_is_superseded():
    """A later commit supersedes the diagnosis, so the plain request is used."""
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            diagnosis_report(at=BEFORE),
        ],
        reviews=[diagnosis_review(at=BEFORE)],
    )

    result = classify(pr)
    assert result["stage"] == "code"
    assert (
        result["command"] == "/fs-fix can you address the review threads and rebase this PR branch"
    )


def test_a_failing_head_reports_e2e_failed_even_when_the_publish_is_stale():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=BEFORE),
            smoke_report(ok=True, at=BEFORE),
            e2e_report(passed=False, at=AFTER),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "e2e-failed"
    assert "7 / 16 / 0 / 4" in " ".join(result["notes"])
    assert "the successful publish predates this head" in result["notes"]


def test_a_publish_that_started_the_tests_is_waited_on_not_retriggered():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=HEAD, starts_e2e=True),
            smoke_report(ok=True, at=AFTER),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "e2e"
    assert result["command"] == "none"


def test_a_head_with_no_started_run_gets_one_requested():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=HEAD),
            smoke_report(ok=True, at=AFTER),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "e2e"
    assert result["command"] == "/test e2e-ocp-helm"


def test_a_failed_quality_gate_names_the_comment_to_address():
    pr = make_pr(comments=[comment("a-reviewer", "/ok-to-test"), sonar_report()])

    result = classify(pr)
    assert result["stage"] == "sonar"
    assert result["command"] == (
        f"/fs-fix can you address the sonarqubecloud findings in {SONAR_URL}"
    )


def test_a_failed_quality_gate_outranks_the_publish_it_would_invalidate():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=HEAD, starts_e2e=True),
            smoke_report(ok=True, at=AFTER),
            e2e_report(passed=True, at=AFTER),
            sonar_report(at=AFTER),
        ],
        mergeStateStatus="CLEAN",
    )

    assert classify(pr)["stage"] == "sonar"


def test_a_passing_quality_gate_is_not_a_stage():
    pr = make_pr(
        comments=[comment("a-reviewer", "/ok-to-test", at=BEFORE), sonar_report(failed=False)]
    )

    assert classify(pr)["stage"] == "publish"


def test_a_quality_gate_failure_older_than_the_head_is_superseded():
    pr = make_pr(
        comments=[comment("a-reviewer", "/ok-to-test", at=BEFORE), sonar_report(at=BEFORE)]
    )

    assert classify(pr)["stage"] == "publish"


def test_open_review_findings_win_over_the_quality_gate():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[sonar_report()],
    )

    result = classify(pr)
    assert result["stage"] == "code"
    assert any(SONAR_URL in note for note in result["notes"])


def test_a_quality_gate_is_attempted_once_then_reported_as_residue():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            sonar_report(at=HEAD),
            fix_finished(at=AFTER, run="1"),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "publish"
    assert any("advisory" in note for note in result["notes"])


def test_two_fix_runs_that_produced_nothing_stop_the_retry():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[fix_finished(at=AFTER, run="1"), fix_finished(at=LATER, run="2")],
    )

    result = classify(pr)
    assert result["stage"] == "fix-failed"
    assert result["command"] == "none"


def test_one_run_reporting_twice_is_one_attempt():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED", at=BEFORE)],
        comments=[
            fix_finished(ok=True, at=AFTER, run="9"),
            fix_finished(at=LATER, run="9", post_script=True),
        ],
    )

    result = classify(pr)
    assert result["stage"] == "code"
    assert "two fix runs in a row" not in " ".join(result["notes"])


def test_a_blocked_merge_is_not_a_reason_to_rerun_the_tests():
    pr = make_pr(
        comments=[
            comment("a-reviewer", "/ok-to-test", at=BEFORE),
            publish_report(ok=True, at=HEAD, starts_e2e=True),
            smoke_report(ok=True, at=AFTER),
            e2e_report(passed=True, at=AFTER),
        ]
    )

    result = classify(pr)
    assert result["stage"] == "blocked"
    assert result["command"] == "none"
    assert "merge is blocked by a required check or approval" in result["notes"]


def test_a_failed_publish_names_the_failure():
    pr = make_pr(
        comments=[comment("a-reviewer", "/ok-to-test"), publish_report(ok=False)],
    )

    result = classify(pr)
    assert result["stage"] == "publish-failed"
    assert result["command"] == "/fs-diagnose"


def test_a_held_pr_is_not_actionable_whatever_its_signals_say():
    pr = make_pr(reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED")])

    result = classify(pr, hold_reason="waiting on a named reviewer")
    assert result["stage"] == "held"
    assert result["command"] == "none"
    assert "waiting on a named reviewer" in result["notes"]


def test_a_closed_pr_is_closed():
    assert classify(make_pr(state="MERGED"))["stage"] == "closed"


def test_review_findings_are_carried_into_the_plan():
    pr = make_pr(
        reviews=[review("fullsend-ai-review", "CHANGES_REQUESTED")],
        comments=[
            comment(
                "fullsend-ai-review",
                "## Review\n### Findings\n#### Low\n- **[naming conventions]** use `error`",
                association="NONE",
            )
        ],
    )

    assert classify(pr)["findings"] == ["naming conventions"]


def test_workspaces_come_from_the_changed_paths():
    pr = make_pr(
        files=[
            {"path": "workspaces/rbac/e2e-tests/a.ts"},
            {"path": "workspaces/rbac/metadata/b.yaml"},
            {"path": "README.md"},
        ]
    )

    assert pipeline.workspaces_of(pr) == ["rbac"]


def test_ledger_round_trip(tmp_path, capsys):
    ledger = tmp_path / "pipeline.json"

    assert pipeline.main(["--ledger", str(ledger), "add", "4440", "4441"]) == 0
    assert pipeline.main(["--ledger", str(ledger), "hold", "4441", "--reason", "parked"]) == 0
    assert pipeline.main(["--ledger", str(ledger), "list"]) == 0
    output = capsys.readouterr().out
    assert "4440" in output
    assert "parked" in output

    assert pipeline.main(["--ledger", str(ledger), "release", "4441"]) == 0
    assert pipeline.main(["--ledger", str(ledger), "remove", "4440"]) == 0
    saved = json.loads(ledger.read_text())
    assert list(saved["prs"]) == ["4441"]
    assert "hold" not in saved["prs"]["4441"]


def test_a_stage_change_is_recorded_once(tmp_path):
    ledger = pipeline.load_ledger(tmp_path / "pipeline.json", "o/r")
    entry = pipeline.entry_for(ledger, 4440)

    first = pipeline.record(entry, {"stage": "gate", "command": "/ok-to-test", "head_at": HEAD})
    again = pipeline.record(entry, {"stage": "gate", "command": "/ok-to-test", "head_at": HEAD})
    moved = pipeline.record(entry, {"stage": "publish", "command": "/publish", "head_at": HEAD})

    assert first == {"changed": False, "previous": None}
    assert again == {"changed": False, "previous": "gate"}
    assert moved == {"changed": True, "previous": "gate"}
    assert [item["stage"] for item in entry["stage_history"]] == ["gate", "publish"]


@pytest.mark.parametrize("argument", ["--no-write", "--json"])
def test_global_options_are_accepted_after_the_command(tmp_path, argument):
    ledger = tmp_path / "pipeline.json"

    assert pipeline.main(["--ledger", str(ledger), "add", "4440"]) == 0
    assert pipeline.main(["list", argument, "--ledger", str(ledger)]) == 0
