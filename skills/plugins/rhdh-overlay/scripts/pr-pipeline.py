#!/usr/bin/env python3
"""Track overlay PRs through the publish and e2e pipeline.

Keeps a local ledger of PRs and refreshes each one's pipeline stage from the
signals in its GitHub comments and checks. Read-only: the script reports what
each PR needs next, and never posts a PR comment.

Stages, in order:

    diagnosed   a CI diagnosis named the failure as this PR's regression
    code        review findings open, a fix agent run is needed
    fixing      a fix agent run is in flight
    fix-failed  two fix runs in a row ended without a commit
    sonar       the SonarQube quality gate failed for this head
    gate        review clean, waiting for a trusted /ok-to-test
    publish     gate passed, no successful publish for the current head
    publishing  /publish posted, the publish check has not settled
    smoke       images published, waiting for the smoke test
    e2e         smoke green, waiting for the e2e run
    mergeable   every gate green for the current head
    superseded  the branch carries no changes, so there is nothing to merge
    held        parked on purpose; the stage is not actionable

Failure stages name what to investigate: ``publish-failed``, ``smoke-failed``,
``e2e-failed`` and ``fix-failed``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_REPO = "redhat-developer/rhdh-plugin-export-overlays"

# Who may post the commands we key on. openshift-ci applies the same rule, so a
# comment from anyone else is not evidence that a gate passed. GitHub Apps report
# CONTRIBUTOR, which is why it must not count as trusted.
TRUSTED_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}
KNOWN_BOTS = {
    "github-actions",
    "fullsend-ai-coder",
    "fullsend-ai-review",
    "fullsend-ai-triage",
    "openshift-ci",
    "openshift-cherrypick-robot",
    "rhdh-test-bot",
    "sonarqubecloud",
}

REVIEW_AGENT = "fullsend-ai-review"
FIX_AGENT = "fullsend-ai-coder"
TEST_BOT = "rhdh-test-bot"
SONAR_BOT = "sonarqubecloud"

E2E_RESULT = re.compile(r"###\s*(✅|❌|⚠️)?\s*(Passed|Failed|Skipped)\s+E2E Tests")
E2E_COUNTS = re.compile(
    r"Passed:\s*(\d+)\s*\|\s*Failed:\s*(\d+)\s*\|\s*Flaky:\s*(\d+)\s*\|\s*Skipped:\s*(\d+)"
)
FINDING = re.compile(r"^- \*\*\[([^\]]+)\]", re.MULTILINE)
RUN_ID = re.compile(r"/actions/runs/(\d+)")
COMMAND_LINE = re.compile(
    r"^\s*/(ok-to-test|publish|test\s+e2e-ocp-helm|fs-fix|fs-diagnose|retest)\b"
)
PUBLISH_CHECK_NAMES = {"publish"}

# What a code-clean review still needs: the fix agent reads the review threads
# itself, so the request points at them rather than paraphrasing them.
FIX_REQUEST = "/fs-fix can you address the review threads and rebase this PR branch"

# A branch older than this is a premise risk, not just a merge conflict risk:
# the code it patches and the failure it exists for may both be gone, and a
# rebase is cheaper than a build that proves an obsolete diff. Two weeks is the
# point where the backlogs in this repository start to rot.
STALE_DAYS = 14


def state_home() -> Path:
    """Return the XDG state directory, falling back to ~/.local/state."""
    root = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(root) / "rhdh-overlay"


def default_ledger() -> Path:
    return state_home() / "pipeline.json"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def short(moment: datetime | None) -> str:
    return moment.strftime("%m-%d %H:%M") if moment else "-"


def run_gh(args: list[str], check: bool = True):
    """Run a gh command and return parsed JSON output."""
    cmd = ["gh", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=120)
    except FileNotFoundError:
        print("error: gh CLI not found — install from https://cli.github.com/", file=sys.stderr)
        raise SystemExit(1) from None
    except subprocess.CalledProcessError as exc:
        if check:
            print(f"error: {' '.join(cmd)}", file=sys.stderr)
            print(exc.stderr, file=sys.stderr)
            raise SystemExit(1) from None
        return None
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def fetch_pr(number: int, repo: str) -> dict | None:
    """Fetch one PR with every field the classifier reads."""
    fields = ",".join(
        (
            "number",
            "title",
            "state",
            "isDraft",
            "headRefOid",
            "mergeable",
            "mergeStateStatus",
            "updatedAt",
            "commits",
            "files",
            "comments",
            "reviews",
            "statusCheckRollup",
        )
    )
    return run_gh(["pr", "view", str(number), "--repo", repo, "--json", fields], check=False)


def workspaces_of(pr: dict) -> list[str]:
    """Return the distinct workspaces the PR touches."""
    found = []
    for entry in pr.get("files") or []:
        parts = (entry.get("path") or "").split("/")
        if len(parts) > 1 and parts[0] == "workspaces" and parts[1] not in found:
            found.append(parts[1])
    return found


def comment_time(comment: dict) -> datetime | None:
    return parse_time(comment.get("createdAt"))


def is_trusted(comment: dict) -> bool:
    """Report whether a comment could satisfy the trusted-user gate."""
    association = (comment.get("authorAssociation") or "").upper()
    if association:
        return association in TRUSTED_ASSOCIATIONS
    author = ((comment.get("author") or {}).get("login") or "").lower().removesuffix("[bot]")
    return bool(author) and author not in KNOWN_BOTS


def collect_signals(pr: dict) -> dict:
    """Extract the dated signals the stage machine reads."""
    signals: dict = {
        "commits": [
            parse_time(c.get("committedDate") or c.get("authoredDate"))
            for c in pr.get("commits") or []
        ],
        "changes_requested": [],
        "approved": [],
        "fixes": [],
        "fix_starts": [],
        "ok_to_test": [],
        "publish_requests": [],
        "test_requests": [],
        "publish_results": [],
        "smoke_results": [],
        "e2e_results": [],
        "diagnoses": [],
        "diagnosis_reviews": [],
        "rejections": [],
        "findings": [],
        "sonar": None,
    }
    for review in pr.get("reviews") or []:
        author = (review.get("author") or {}).get("login") or ""
        if author != REVIEW_AGENT:
            continue
        submitted = parse_time(review.get("submittedAt"))
        if review.get("state") == "CHANGES_REQUESTED":
            signals["changes_requested"].append(submitted)
            # The agent raises this review only when it wants the findings
            # implemented, so it is the gate. The diagnosis comment itself
            # cannot be searched: its prose quotes the other verdicts too
            # ("Previous diagnosis ... pr_regression") even when the current
            # verdict is flake, pre-existing, or "no action needed".
            if "PR-regression" in (review.get("body") or ""):
                signals["diagnosis_reviews"].append(submitted)
        elif review.get("state") == "APPROVED":
            signals["approved"].append(submitted)

    for comment in pr.get("comments") or []:
        author = (comment.get("author") or {}).get("login") or ""
        body = comment.get("body") or ""
        stamp = comment_time(comment)
        for line in body.splitlines():
            match = COMMAND_LINE.match(line)
            if not match or not is_trusted(comment):
                continue
            command = match.group(1).split()[0]
            if command == "ok-to-test":
                signals["ok_to_test"].append(stamp)
            elif command == "publish":
                signals["publish_requests"].append(stamp)
            elif command == "test":
                signals["test_requests"].append(stamp)
        if author == FIX_AGENT:
            # One run can report twice — a terminal status comment and a separate
            # post-script failure with the same workflow link — so outcomes are
            # keyed by run id and a failure wins over a success for the same run.
            if "Finished Fix" in body or "Post-fix script failed" in body:
                run = RUN_ID.search(body)
                signals["fixes"].append(
                    {
                        "at": stamp,
                        "ok": "Finished Fix" in body and "❌" not in body,
                        "run": run.group(1) if run else stamp.isoformat(),
                        "url": comment.get("url") or "",
                    }
                )
            elif "Fix · Started" in body:
                # The coder announces the run with a workflow link before it reports
                # an outcome. A run with no outcome yet is in flight, and asking for
                # another one would start a second run against the same findings.
                signals["fix_starts"].append(stamp)
        # Workflow outcomes are identified by the run link they carry, not by the
        # author: gh reports these comments as `github-actions` and associates them
        # as CONTRIBUTOR, indistinguishable from a bot that must not satisfy a gate.
        if "Publish workflow" in body and "/actions/runs/" in body:
            signals["publish_results"].append(
                {
                    "at": stamp,
                    "ok": "completed with success" in body,
                    # A successful publish ends by triggering the e2e run itself, so
                    # asking for one again would queue a duplicate.
                    "starts_e2e": "Running e2e tests" in body,
                }
            )
        if "Smoke tests workflow" in body and "/actions/runs/" in body:
            signals["smoke_results"].append((stamp, "passed" in body))
        if author == TEST_BOT and E2E_RESULT.search(body):
            counts = E2E_COUNTS.search(body)
            signals["e2e_results"].append(
                {
                    "at": stamp,
                    "passed": "✅" in body.split("\n", 1)[0],
                    "counts": counts.groups() if counts else None,
                }
            )
        if author == REVIEW_AGENT and "ci-diagnose" in body:
            # Where the findings live, so this is what the fix request quotes.
            # The verdict is the one line that says whose failure this is.
            verdict = ""
            for line in body.splitlines():
                if line.startswith("**Verdict:**"):
                    verdict = line.split("**Verdict:**", 1)[1].strip().lower()
                    break
            signals["diagnoses"].append(
                {"at": stamp, "url": comment.get("url") or "", "verdict": verdict}
            )
        if "Cannot trigger testing until a trusted user" in body:
            signals["rejections"].append(stamp)
        if author == SONAR_BOT:
            # The last analysis wins: a later pass supersedes an earlier failure,
            # and a failure older than the head has been superseded by the push.
            signals["sonar"] = {
                "at": stamp,
                "failed": "Quality Gate failed" in body,
                "url": comment.get("url") or "",
            }
        if author == REVIEW_AGENT:
            found = FINDING.findall(body)
            if found:
                signals["findings"] = found
    for key in ("changes_requested", "approved", "ok_to_test", "publish_requests", "test_requests"):
        signals[key] = [s for s in signals[key] if s]
    signals["commits"] = [c for c in signals["commits"] if c]
    signals["fixes"] = _one_outcome_per_run(signals["fixes"])
    return signals


def _one_outcome_per_run(outcomes: list[dict]) -> list[dict]:
    """Collapse repeated reports for the same fix run, keeping a failure."""
    merged: dict[str, dict] = {}
    for outcome in outcomes:
        seen = merged.get(outcome["run"])
        if seen is None or (seen["ok"] and not outcome["ok"]) or outcome["at"] > seen["at"]:
            merged[outcome["run"]] = outcome
    return sorted(merged.values(), key=lambda outcome: outcome["at"])


def publish_check_state(pr: dict) -> str:
    for check in pr.get("statusCheckRollup") or []:
        name = (check.get("name") or check.get("context") or "").lower()
        if name in PUBLISH_CHECK_NAMES:
            return (check.get("conclusion") or check.get("state") or "").upper()
    return ""


def latest(items):
    dated = [item for item in items if item]
    if not dated:
        return None
    return max(
        dated,
        key=lambda item: (
            item[0] if isinstance(item, tuple) else item["at"] if isinstance(item, dict) else item
        ),
    )


def after(item, moment: datetime | None) -> bool:
    """True when a signal is recent enough to describe the current head."""
    if item is None or moment is None:
        return False
    stamp = item["at"] if isinstance(item, dict) else item[0] if isinstance(item, tuple) else item
    return stamp is not None and stamp >= moment


def classify(pr: dict, hold_reason: str | None = None, now: datetime | None = None) -> dict:
    """Return the pipeline stage and next command for one PR.

    The stage is the most actionable thing about the PR, not the earliest unmet
    gate: a PR with failing e2e evidence reports ``e2e-failed`` even if its
    publish predates the current head, because the failure is what needs a
    decision. Everything not actionable goes into ``notes``.

    ``now`` exists so the staleness rule is testable: a branch older than
    ``STALE_DAYS`` is a premise risk as well as a conflict risk, so it earns a
    rebase before it earns a build.
    """
    signals = collect_signals(pr)
    head_at = max(signals["commits"]) if signals["commits"] else None
    moment = now or datetime.now(timezone.utc)
    age = moment - head_at if head_at else None
    stale = bool(age and age >= timedelta(days=STALE_DAYS))
    notes: list[str] = []

    def result(stage: str, command: str, detail: str = "") -> dict:
        if stale:
            notes.append(
                f"the head is {age.days} days old: re-check that the code it patches and the "
                "failure it exists for still match main before merging"
            )
            if command in ("/publish", "/test e2e-ocp-helm"):
                command, detail = (
                    FIX_REQUEST,
                    "rebase as well as fix before publishing a stale head",
                )
        return {
            "stage": stage,
            "command": command,
            "detail": detail,
            "head_at": iso(head_at),
            "merge_state": pr.get("mergeStateStatus"),
            "findings": signals["findings"][:6],
            "notes": notes,
        }

    if pr.get("state") != "OPEN":
        return result("closed", "none")
    if hold_reason:
        notes.append(hold_reason)
        return result("held", "none")
    if pr.get("isDraft"):
        notes.append("draft PR")
    if not pr.get("files"):
        # A fix that reverts the PR to what main already has leaves an empty
        # branch: the publish workflow cancels it, so the only move is to close.
        notes.append("the branch is identical to main, so there is nothing to merge")
        return result("superseded", "none")

    started = latest(signals["fix_starts"])
    finished = latest(signals["fixes"])
    if started and (finished is None or finished["at"] < started):
        return result("fixing", "none", "a fix run is in progress")

    sonar = signals["sonar"]
    sonar_open = bool(sonar and sonar["failed"] and after(sonar, head_at))
    # A run that died before announcing itself still counts as an attempt, so
    # both the start and the outcome comments are evidence that it was tried.
    fix_attempts = [*signals["fix_starts"], *signals["fixes"]]

    # A CI diagnosis is derived from the failing run rather than from reading
    # the diff, so it names the failure more precisely than the review that
    # summarises it. Ranked ahead of the plain review request, and it points at
    # the findings comment rather than at the review.
    diagnosis = None
    verdict = latest(signals["diagnosis_reviews"])
    if verdict and after(verdict, head_at):
        details = [entry for entry in signals["diagnoses"] if after(entry, head_at)]
        if details:
            diagnosis = details[-1]
    addressed = bool(diagnosis and any(f["ok"] and after(f, verdict) for f in signals["fixes"]))
    changes = latest(signals["changes_requested"])
    code_open = bool(changes and not any(f["ok"] and after(f, changes) for f in signals["fixes"]))
    wants_fix = bool(diagnosis and not addressed) or code_open or sonar_open

    # A fix run that ended without a commit changed nothing, so repeating the
    # same request asks for the same run again. One failure is worth a retry —
    # agent runs die for transient reasons — but two in a row for the same head
    # is a pattern, and the next attempt would be the third of the same thing.
    failed_fixes = [f for f in signals["fixes"] if not f["ok"] and after(f, head_at)]
    if len(failed_fixes) >= 2 and wants_fix:
        notes.append(f"two fix runs in a row failed; the last: {failed_fixes[-1]['url']}")
        if sonar_open:
            notes.append(f"the quality gate is still failing: {sonar['url']}")
        return result("fix-failed", "none", "two fix runs in a row ended without a commit")

    if diagnosis and not addressed:
        return result(
            "diagnosed",
            f"/fs-fix can you incorporate the findings in {diagnosis['url']} to fix the e2e tests?",
            "a CI diagnosis traced the failures to this PR",
        )

    if code_open:
        if any(not f["ok"] and after(f, changes) for f in signals["fixes"]):
            notes.append("the last fix run failed, so this is a retry")
        if sonar_open:
            notes.append(f"the quality gate also failed: {sonar['url']}")
        return result("code", FIX_REQUEST, "review findings are open")

    # Ranked above the gate and the publish: the fix is another commit, and a
    # commit invalidates any publish, smoke, or e2e result already earned. But
    # only one attempt is spent per analysis — the gate is advisory here, and a
    # second cycle delays the publish and e2e it would invalidate anyway.
    if sonar_open and not any(after(attempt, sonar["at"]) for attempt in fix_attempts):
        return result(
            "sonar",
            f"/fs-fix can you address the sonarqubecloud findings in {sonar['url']}",
            "the quality gate failed for this head",
        )
    if sonar_open:
        notes.append(
            f"the quality gate is still red after a fix attempt, and is advisory: {sonar['url']}"
        )

    if not latest(signals["ok_to_test"]):
        return result("gate", "/ok-to-test", "no trusted /ok-to-test yet")

    publishes = signals["publish_results"]
    published = [entry for entry in publishes if entry["ok"] and after(entry, head_at)]
    publish_failed = any(not entry["ok"] and after(entry, head_at) for entry in publishes)
    smok_ok = any(pair[1] and after(pair, head_at) for pair in signals["smoke_results"])
    smoke_failed = any(not pair[1] and after(pair, head_at) for pair in signals["smoke_results"])
    runs = [run for run in signals["e2e_results"] if after(run, head_at)]
    check = publish_check_state(pr)

    if runs and not runs[-1]["passed"]:
        counts = " / ".join(runs[-1]["counts"]) if runs[-1]["counts"] else "unknown counts"
        notes.append(f"e2e failed (passed / failed / flaky / skipped: {counts})")
        # A re-run requested after the failure has already answered it, and the
        # publish check can take a minute to appear. Reporting the old failure
        # here is what tempts a second request.
        if any(after(request, runs[-1]["at"]) for request in signals["test_requests"]):
            return result("e2e", "none", "test re-run requested after the failure")
        if any(after(request, runs[-1]["at"]) for request in signals["publish_requests"]):
            return result("publishing", "none", "re-run requested after the failure")
        covering = [dx for dx in signals["diagnoses"] if after(dx, runs[-1]["at"])]
        if covering:
            # Diagnosing an already-diagnosed run only repeats the same answer.
            found = covering[-1]
            notes.append(f"diagnosed on {found['url']}")
            verdict = found["verdict"]
            if "flake" in verdict or "no action needed" in verdict or "re-running" in verdict:
                notes.append("the diagnosis expects a re-run to pass")
                # A flake needs the tests run again, not the artifact rebuilt:
                # the plugin images the tests exercise did not change.
                if not published:
                    notes.append("the successful publish predates this head")
                return result("e2e-failed", "/test e2e-ocp-helm", "re-run the checks for this head")
            notes.append("the diagnosis does not blame this PR — hold it or force it through")
            return result("e2e-failed", "none", "diagnosed as not this PR's fault")
        if not published:
            notes.append("the successful publish predates this head")
        return result("e2e-failed", "/fs-diagnose", "e2e failed for the current head")
    if check in {"PENDING", "QUEUED", "IN_PROGRESS"}:
        return result("publishing", "none", "the publish check is running")
    if publish_failed and not published:
        notes.append("the last publish for this head failed")
        if signals["diagnoses"] and after(signals["diagnoses"][-1], head_at):
            notes.append("a diagnosis already covers it")
        return result("publish-failed", "/fs-diagnose", "publish failed for the current head")
    if not published:
        return result("publish", "/publish", "no successful publish for the current head")
    if smoke_failed:
        return result("smoke-failed", "/fs-diagnose", "smoke tests failed for this head")
    if not smok_ok:
        return result("smoke", "none", "waiting for the smoke test")
    if not runs:
        if signals["e2e_results"]:
            notes.append("the last e2e result predates the current head")
        if published[-1]["starts_e2e"]:
            return result("e2e", "none", "the publish started the e2e run; waiting for it")
        return result("e2e", "/test e2e-ocp-helm", "no e2e run was started for this head")
    if pr.get("mergeStateStatus") == "BLOCKED":
        notes.append("merge is blocked by a required check or approval")
        return result("blocked", "none", "e2e passed but merge is blocked")
    return result("mergeable", "merge", "all gates green for the current head")


def load_ledger(path: Path, repo: str) -> dict:
    if path.is_file():
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"warning: {path} is not valid JSON; starting a new ledger", file=sys.stderr)
            ledger = {}
    else:
        ledger = {}
    ledger.setdefault("repo", repo)
    ledger.setdefault("prs", {})
    return ledger


def save_ledger(path: Path, ledger: dict) -> None:
    ledger["updated_at"] = iso(datetime.now(timezone.utc))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def entry_for(ledger: dict, number: int) -> dict:
    return ledger["prs"].setdefault(str(number), {"stage_history": []})


def record(entry: dict, snapshot: dict) -> dict:
    """Fold a fresh snapshot into the ledger entry and report what changed."""
    previous = entry.get("stage")
    entry["stage"] = snapshot["stage"]
    entry["command"] = snapshot["command"]
    entry["head_at"] = snapshot["head_at"]
    entry["last_checked"] = iso(datetime.now(timezone.utc))
    history = entry.setdefault("stage_history", [])
    if previous != snapshot["stage"]:
        history.append({"at": entry["last_checked"], "stage": snapshot["stage"]})
        del history[:-25]
    return {"changed": previous not in (None, snapshot["stage"]), "previous": previous}


def render(rows: list[dict], deltas: list[dict], ledger: dict, path: Path) -> str:
    lines = ["# Overlay PR pipeline", ""]
    lines.append(f"Ledger: `{path}`  ")
    lines.append(f"Checked: {iso(datetime.now(timezone.utc))}  ")
    lines.append(f"Tracked: {len(ledger['prs'])} PRs")
    lines.append("")
    if rows:
        lines.append("| PR | Workspace | Head | Stage | Next | Notes |")
        lines.append("|---|---|---|---|---|---|")
        for row in rows:
            workspace = row["workspace"] or "-"
            notes = list(row["notes"])
            # Findings are only the specification while a fix is owed; on a PR that
            # already moved past review they are stale and just add noise.
            if row["findings"] and row["stage"] in {"code", "fixing"}:
                unique = list(dict.fromkeys(row["findings"]))
                notes.append("findings: " + "; ".join(unique[:2]))
            notes = "; ".join(notes)
            command = row["command"] if row["command"] != "none" else "wait"
            lines.append(
                f"| #{row['number']} | `{workspace}` | {short(parse_time(row['head_at']))} "
                f"| {row['stage']} | `{command}` | {notes} |"
            )
        lines.append("")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["stage"]] = counts.get(row["stage"], 0) + 1
    if counts:
        lines.append(
            "**By stage:** "
            + ", ".join(f"{stage} {count}" for stage, count in sorted(counts.items()))
        )
        lines.append("")
    actionable = [row for row in rows if row["command"] not in {"none", "merge"}]
    if actionable:
        lines.append("## Command plan")
        lines.append("")
        lines.append("Posting any of these is an external write and needs approval first.")
        lines.append("")
        for row in actionable:
            lines.append(f"- `#{row['number']}` ({row['stage']}): `{row['command']}`")
        lines.append("")
    moves = [delta for delta in deltas if delta["changed"]]
    if moves:
        lines.append("## Changed since the last check")
        lines.append("")
        for delta in moves:
            lines.append(
                f"- `#{delta['number']}`: {delta['previous'] or '(new)'} → {delta['stage']}"
            )
        lines.append("")
    ready = [row for row in rows if row["command"] == "merge"]
    if ready:
        lines.append("## Ready to merge")
        lines.append("")
        for row in ready:
            lines.append(
                f"- `#{row['number']}` — {row['notes'][0] if row['notes'] else 'all gates green'}"
            )
        lines.append("")
    return "\n".join(lines)


def refresh(numbers: list[int], repo: str, ledger: dict) -> tuple[list[dict], list[dict]]:
    """Re-read every tracked PR and fold the result into the ledger."""
    rows, deltas = [], []
    for number in numbers:
        entry = entry_for(ledger, number)
        pr = fetch_pr(number, repo)
        if pr is None:
            rows.append(
                {
                    "number": number,
                    "workspace": entry.get("workspace", ""),
                    "stage": "missing",
                    "command": "none",
                    "head_at": entry.get("head_at"),
                    "notes": ["PR could not be read — deleted, or gh is not authenticated"],
                }
            )
            continue
        hold = entry.get("hold_reason", "parked") if entry.get("hold") else None
        snapshot = classify(pr, hold_reason=hold)
        workspace = ", ".join(workspaces_of(pr)) or entry.get("workspace", "")
        entry["workspace"] = workspace
        entry.setdefault("title", pr.get("title", ""))
        if snapshot["merge_state"]:
            entry["merge_state"] = snapshot["merge_state"]
        delta = record(entry, snapshot)
        deltas.append({"number": number, "stage": snapshot["stage"], **delta})
        rows.append({"number": number, "workspace": workspace, **snapshot})
    return rows, deltas


def _add_global_options(parser: argparse.ArgumentParser, suppress: bool = False) -> None:
    """Add the options that may appear before or after the subcommand.

    ``SUPPRESS`` stops a subparser from resetting a value the caller already gave on
    the other side of the command name.
    """
    parser.add_argument(
        "--repo", default=argparse.SUPPRESS if suppress else DEFAULT_REPO, help="owner/name"
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=argparse.SUPPRESS if suppress else None,
        help="ledger file to read and write",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="report without updating the ledger",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="emit JSON instead of markdown",
    )


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    _add_global_options(common, suppress=True)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], parents=[common])
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("status", help="refresh every tracked PR and report", parents=[common])
    add = commands.add_parser("add", help="start tracking PRs", parents=[common])
    add.add_argument("numbers", type=int, nargs="+")
    remove = commands.add_parser("remove", help="stop tracking PRs", parents=[common])
    remove.add_argument("numbers", type=int, nargs="+")
    hold = commands.add_parser(
        "hold", help="park a PR so its stage is not actionable", parents=[common]
    )
    hold.add_argument("number", type=int)
    hold.add_argument("--reason", default="")
    release = commands.add_parser("release", help="clear a hold", parents=[common])
    release.add_argument("number", type=int)
    commands.add_parser("list", help="list tracked PRs without contacting GitHub", parents=[common])

    args = parser.parse_args(argv)
    action = args.command or "status"
    no_write = getattr(args, "no_write", False)
    path = getattr(args, "ledger", None) or default_ledger()
    ledger = load_ledger(path, getattr(args, "repo", DEFAULT_REPO))

    if action == "add":
        for number in args.numbers:
            entry_for(ledger, number).setdefault("added_at", iso(datetime.now(timezone.utc)))
        save_ledger(path, ledger)
        print(f"tracking {len(ledger['prs'])} PRs in {path}")
        return 0

    if action == "remove":
        for number in args.numbers:
            ledger["prs"].pop(str(number), None)
        save_ledger(path, ledger)
        print(f"tracking {len(ledger['prs'])} PRs in {path}")
        return 0

    if action == "hold":
        entry = entry_for(ledger, args.number)
        entry["hold"] = True
        entry["hold_reason"] = args.reason or "parked"
        save_ledger(path, ledger)
        print(f"#{args.number} held: {entry['hold_reason']}")
        return 0

    if action == "release":
        entry = entry_for(ledger, args.number)
        entry.pop("hold", None)
        entry.pop("hold_reason", None)
        save_ledger(path, ledger)
        print(f"#{args.number} released")
        return 0

    numbers = sorted(int(number) for number in ledger["prs"])
    if action == "list":
        for number in numbers:
            entry = ledger["prs"][str(number)]
            hold = f" (held: {entry.get('hold_reason', '')})" if entry.get("hold") else ""
            print(f"#{number}  {entry.get('stage', 'unknown')}  {entry.get('workspace', '')}{hold}")
        return 0

    if not numbers:
        print(
            f"no PRs tracked in {path} — add some with: pr-pipeline.py add <number> ...",
            file=sys.stderr,
        )
        return 1

    rows, deltas = refresh(numbers, getattr(args, "repo", DEFAULT_REPO), ledger)
    if not no_write:
        save_ledger(path, ledger)

    if getattr(args, "json", False):
        print(json.dumps({"ledger": str(path), "prs": rows, "deltas": deltas}, indent=2))
    else:
        print(render(rows, deltas, ledger, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
