"""Consume one locally prepared event; atomically retain one receipt per issue revision."""

import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .model import load_export
from .policy import is_upstream_repository
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


def upstream_patch_handoff(event, dest, key, base):
    """An upstream fix is attached to the Jira issue, never opened as a pull request."""
    repository, branch = event["repository"], event["branch"]
    note = "\n".join(
        [
            f"# Suggested upstream patch for {key}",
            "",
            f"- Upstream repository: {repository}",
            f"- Branch: {branch} at {base}",
            "- Patch: [change.patch](change.patch)",
            "- Verification: [VERIFY.md](VERIFY.md)",
            "",
            "Do not open a pull request in this upstream repository from this workflow.",
            f"Attach `change.patch` to {key} in RHDHBUGS and mention the follow-up in the comment.",
            "",
            "Suggested comment line:",
            "",
            f"> A suggested fix for {repository} is attached as `change.patch` "
            f"(based on {branch} at {base}).",
            "> It must land upstream first; RHDH can pick it up once it is released.",
        ]
    )
    if event.get("body"):
        note += f"\n\n## Proposed change\n\n{event['body']}\n"
    (dest / "UPSTREAM-PATCH.md").write_text(note + "\n")
    write_json(
        dest / "proposal.json",
        {
            **{name: event.get(name) for name in ("repository", "branch", "kind", "title")},
            "upstream": True,
            "attachment": "change.patch",
            "backports": [],
        },
    )
    return "review_patch"


def reviewed_comments(event, key, inputs):
    """Verify the investigator read the complete thread and anchored each interpretation."""
    if not event.get("commentExport") or not isinstance(event.get("commentReview"), list):
        return None
    source = inputs / event["commentExport"]
    if not source.is_file():
        return None
    issues = [t for t in load_export(str(source)) if t.key == key]
    if len(issues) != 1 or not issues[0].comments_complete:
        return None
    rows = event["commentReview"]
    comments = {c.id: " ".join(c.body.split()) for c in issues[0].comments}
    if len(comments) != len(issues[0].comments) or "" in comments:
        return None
    if len(rows) != len(comments) or {required(r, "id") for r in rows} != comments.keys():
        return None
    for row in rows:
        if " ".join(required(row, "excerpt").split()) not in comments[row["id"]]:
            return None
        required(row, "scope")
        required(row, "observation")
    return rows


def evidenced_backport(record, comments, docs, inputs):
    gate = required(record, "decision")
    if gate in {"skip", "undetermined"}:
        action, reason = backport_decision(record)
        return ("human_review" if action == "undetermined" else action), reason
    if gate not in {"assess", "propose"}:
        raise ValueError("invalid backport decision")
    if record.get("supportStatus") == "unsupported":
        return "skip", "Branch is outside the support window."
    if record.get("compatibility") == "breaking":
        return "skip", "The proposed change would break compatibility on this branch."
    if record.get("supportStatus") != "supported" or not str(
        record.get("supportSource") or ""
    ).startswith("https://"):
        return "human_review", "Target branch support is unverified."
    if (
        record.get("compatibility") != "compatible"
        or not (record.get("compatibilityEvidence") or "").strip()
    ):
        return "human_review", "Target branch compatibility is unverified."
    if comments is None:
        return "human_review", "Complete verified Jira comment review unavailable."
    branch = required(record, "branch")
    matched = [row for row in comments if row["scope"] == branch]
    if docs:
        guidance = record.get("guidance", {})
        if any(row.get("contradictsGuidance") for row in matched):
            return "human_review", "Target-branch comment evidence conflicts with the guidance."
        status = guidance.get("status")
        reason = guidance.get("basis")
        if status in {"already_covered", "not_applicable"} and reason:
            return "skip", reason
        if status != "verified_gap" or not reason or not record.get("base"):
            return (
                "human_review",
                "Applicability or a documentation gap on this release is unverified.",
            )
        for field in ("behaviorCheck", "docsCheck"):
            check = guidance.get(field) or {}
            if check.get("base") != record["base"]:
                return "human_review", "Check is missing or targets a different revision."
            path = inputs / required(check, "file")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != check.get(
                "sha256"
            ):
                return "human_review", "The recorded release check is unavailable or has changed."
        return "propose", reason
    merged = dict(record)
    for field in ("impact", "workaround"):
        observed = {row[field] for row in matched if row.get(field) not in (None, "unknown")}
        if not observed:
            continue
        if len(observed) > 1 or record.get(field) not in (None, "unknown", *observed):
            return "human_review", f"Conflicting target-branch {field} evidence."
        merged[field] = observed.pop()
    if matched:
        merged["impactEvidence"] = " ".join(
            filter(None, [merged.get("impactEvidence"), *(r["observation"] for r in matched)])
        )
    action, reason = backport_decision(merged)
    return ("human_review" if action == "undetermined" else action), reason


def backport_decision(record):
    """Apply the branch eligibility gate before weighing impact and mitigation."""
    gate = required(record, "decision")
    reason = required(record, "reason")
    if gate in {"skip", "undetermined"}:
        return gate, reason
    if gate not in {"assess", "propose"}:
        raise ValueError("invalid backport decision")
    impact = record.get("impact", "unknown")
    workaround = record.get("workaround", "unknown")
    if impact not in {"low", "moderate", "high", "unknown"} or workaround not in {
        "easy_verified",
        "costly",
        "none_verified",
        "unknown",
    }:
        raise ValueError("invalid branch impact or workaround")
    basis = record.get("impactEvidence")
    if not isinstance(basis, str) or not basis.strip():
        return "undetermined", f"{reason} Branch impact and workaround evidence needed."
    if impact == "low" or (impact == "moderate" and workaround == "easy_verified"):
        action = "skip"
    elif impact in {"moderate", "high"} and workaround in {"costly", "none_verified"}:
        action = "propose"
    else:
        action = "undetermined"
    return action, f"{reason} Impact: {impact}. Workaround: {workaround}. {basis}"


def proposal_body(repo, record, fallback):
    """Check the investigator's filled template against the verified target commit."""
    paths = git(repo, "ls-tree", "-r", "--name-only", "-z", record["base"]).split("\0")
    roots = ("", ".github/", "docs/")
    defaults = [
        path
        for root in roots
        for path in paths
        if path.casefold() == root + "pull_request_template.md"
    ]
    named = [
        path
        for path in paths
        if any(path.casefold().startswith(root + "pull_request_template/") for root in roots)
        and path.lower().endswith(".md")
    ]
    selected = record.get("templatePath")
    if selected is None:
        candidates = defaults or named
        if len(candidates) > 1:
            raise ValueError("select the applicable PR template with templatePath")
        selected = next(iter(candidates), None)
    elif selected not in defaults + named:
        raise ValueError("templatePath is not a PR template at the target base")
    body = record.get("body", fallback)
    if selected:
        template = git(repo, "show", f"{record['base']}:{selected}")
        headings = re.findall(r"^#{1,6} +.+$", template, re.M)
        remaining = body.splitlines()
        for heading in headings:
            if heading not in remaining:
                raise ValueError(f"fill the target PR template {selected}, preserving {heading}")
            remaining = remaining[remaining.index(heading) + 1 :]
        if body.strip() == template.strip():
            raise ValueError("fill the PR template before proposing the change")
    placeholder = "<!-- triage-verification -->"
    if body.count(placeholder) > 1:
        raise ValueError("use one verification placeholder per proposal")
    if placeholder in body:
        return body.replace(placeholder, test_section(record, heading=False))
    return body + "\n" + test_section(record)


def test_section(record, *, heading=True):
    """Render the investigator's recorded commands as text; never execute them."""
    lines = ["", "### How this was tested", ""] if heading else []
    commands = record.get("testCommands", [])
    if not isinstance(commands, list) or not all(
        isinstance(c, str) and c.strip() for c in commands
    ):
        raise ValueError("testCommands must be a list of recorded commands")
    if commands:
        lines.extend(["```bash", *commands, "```", ""])
    lines.append(required(record, "verification"))
    if "verificationLog" in record:
        log = html.escape(required(record, "verificationLog"))
        lines.extend(
            [
                "",
                "<details>",
                "<summary>Verification log</summary>",
                "",
                f"<pre>{log}</pre>",
                "",
                "</details>",
            ]
        )
    return "\n".join(lines)


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
    if finding.get("investigation", {}).get("classification", {}).get("kind") in {
        "feature",
        "task",
        "uncertain",
    }:
        raise ValueError("issue classification requires human review before preparing a fix")
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
    if is_upstream_repository(event["repository"]) and event.get("backports"):
        raise ValueError(
            "upstream fixes are attached to the RHDHBUGS ticket as one patch; remove the backports"
        )
    base = proposal(event, dest, inputs, docs_only=docs_only)
    if is_upstream_repository(event["repository"]):
        return upstream_patch_handoff(event, dest, key, base)
    repo = inputs / event["checkout"]
    body = required(event, "body")
    lines = [
        f"# {required(event, 'title')}",
        "",
        proposal_body(repo, event, body),
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
    comments = reviewed_comments(event, key, inputs) if decisions else []
    comment_lines = []
    if comments:
        comment_lines.extend(["", "### Jira evidence", ""])
        for comment in comments:
            url = f"https://redhat.atlassian.net/browse/{key}?focusedCommentId={comment['id']}"
            comment_lines.append(
                f"- [Comment {comment['id']}]({url}) ({comment['scope']}): {comment['observation']}"
            )
    lines.extend(comment_lines)
    evaluated = []
    seen = {event["branch"]}
    for number, decision in enumerate(decisions):
        branch = required(decision, "branch")
        action, reason = evidenced_backport(decision, comments, docs_only, inputs)
        evaluated.append(
            {
                "branch": branch,
                "decision": action,
                "reason": reason,
                **{
                    field: decision[field]
                    for field in (
                        "supportStatus",
                        "supportSource",
                        "compatibility",
                        "compatibilityEvidence",
                    )
                    if field in decision
                },
            }
        )
        if branch in seen:
            raise ValueError("invalid or duplicate backport decision")
        seen.add(branch)
        lines.append(f"- {branch}: {action}. {reason}")
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
            (directory / "PROPOSAL.md").write_text(
                f"# {event['title']} ({branch})\n\n{proposal_body(repo, decision, body)}\n\n"
                f"Target: {branch} at {decision['base']}.\n\n{reason}\n"
                + "\n".join(comment_lines)
                + "\n\n[Patch](change.patch) · [Verification record](VERIFY.md)\n"
            )
    lines.extend(["", "[Patch](change.patch) · [Verification record](VERIFY.md)"])
    release_targets = {}
    for record in [
        event,
        *(
            record
            for record, result in zip(decisions, evaluated)
            if result["decision"] == "propose"
        ),
    ]:
        if "releaseTarget" in record:
            target = record["releaseTarget"]
            version, source = required(target, "version"), required(target, "source")
            if not source.startswith("https://"):
                raise ValueError("releaseTarget requires a cited branch-to-version mapping")
            release_targets[record["branch"]] = {"version": version, "source": source}
    for result in evaluated:
        if result["branch"] in release_targets:
            result["releaseTarget"] = release_targets[result["branch"]]
    write_json(
        dest / "proposal.json",
        {
            **{name: event.get(name) for name in ("repository", "branch", "kind", "title")},
            **(
                {"releaseTarget": release_targets[event["branch"]]}
                if event["branch"] in release_targets
                else {}
            ),
            "reviewedCommentIds": [row["id"] for row in comments or []],
            "backports": evaluated,
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
