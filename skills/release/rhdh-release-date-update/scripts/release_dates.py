#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["ruamel.yaml"]
# ///
"""Diff and update RHDH release-date files against an authoritative schedule.

Targets:
  github  redhat-developer/rhdh-plugin-export-overlays: release-schedule.yaml
  gitlab  rhidp/rhdh-jira-lint (gitlab.cee.redhat.com): release_calendar.yaml

Source-of-truth dates are supplied by the caller as JSON (see
references/target-schemas.md for the shape) after invoking
/rhdh-release-schedule — this script never talks to Jira or the schedule
spreadsheet itself.

This script never opens a pull or merge request. It pushes the rendered file
to this skill's fixed branch (rhdh-release-date-update) via the GitHub/GitLab
content APIs, and reports whether an open PR/MR already targets that branch.
Constructing the `gh pr create` / `glab mr create` command is /rhdh-forge's
job, invoked by the calling skill after this script's plan is approved.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

# Overridable via env var for testing against a scratch repo/project — never
# set these in normal use, the defaults are the real production targets.
GITHUB_REPO = os.environ.get(
    "RELEASE_DATE_UPDATE_GITHUB_REPO", "redhat-developer/rhdh-plugin-export-overlays"
)
GITHUB_FILE_PATH = os.environ.get("RELEASE_DATE_UPDATE_GITHUB_PATH", "release-schedule.yaml")
GITHUB_BASE_BRANCH = os.environ.get("RELEASE_DATE_UPDATE_GITHUB_BASE", "main")

GITLAB_HOST = os.environ.get("RELEASE_DATE_UPDATE_GITLAB_HOST", "gitlab.cee.redhat.com")
GITLAB_PROJECT = os.environ.get("RELEASE_DATE_UPDATE_GITLAB_PROJECT", "rhidp/rhdh-jira-lint")
GITLAB_FILE_PATH = os.environ.get("RELEASE_DATE_UPDATE_GITLAB_PATH", "release_calendar.yaml")
GITLAB_BASE_BRANCH = os.environ.get("RELEASE_DATE_UPDATE_GITLAB_BASE", "main")

BRANCH_NAME = os.environ.get("RELEASE_DATE_UPDATE_BRANCH", "rhdh-release-date-update")

TBD_VALUES = {None, "", "TBD", "tbd"}

# Protected branch names refused as an apply target regardless of how
# BRANCH_NAME is configured. RELEASE_DATE_UPDATE_BRANCH is documented as a
# testing-only override; a misconfiguration here must never turn into a direct
# commit to a base branch that skips PR/MR review.
PROTECTED_BRANCH_RE = re.compile(r"^(main|master|develop|release-.*)$")

# Fields that must be present in the source JSON before a version absent from a
# target file can be created there. Every existing entry in both live files
# carries all of these, so a partial entry would be malformed. A field missing
# here is never invented: on an existing entry the current value stands, and on
# a new entry the whole entry is withheld and reported.
REQUIRED_FIELDS = {
    "github": ("backstage_version", "feature_freeze"),
    "gitlab": ("feature_freeze", "code_freeze", "ga_push", "backstage_version"),
}

# The three fields that are dates rather than version strings. Each target only
# cares about the subset it writes — see REQUIRED_FIELDS — so validation is
# scoped per target rather than checking every date in every source entry.
DATE_FIELDS = {"feature_freeze", "code_freeze", "ga_push"}

# Both target files track minor releases only — every entry in each is x.y.0.
# The active-release JQL also returns z-streams, and the planned-release
# spreadsheet path normalizes to a bare x.y, so both forms are distinguished
# from genuine garbage: a z-stream is silently out of scope, but "2.2" is a
# transcription bug worth surfacing rather than another silent skip.
MINOR_RELEASE_RE = re.compile(r"^\d+\.\d+\.0$")
MAJOR_MINOR_ONLY_RE = re.compile(r"^\d+\.\d+$")
ZSTREAM_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _supplied(value: Any) -> bool:
    """True when the source actually carries a value for a field."""
    if isinstance(value, str):
        value = value.strip()
    return value not in TBD_VALUES


def _version_form(version: str) -> str:
    v = str(version)
    if MINOR_RELEASE_RE.match(v):
        return "minor"
    if ZSTREAM_RE.match(v):
        return "zstream"
    if MAJOR_MINOR_ONLY_RE.match(v):
        return "major-minor"
    return "unrecognized"


def _is_iso_date(value: Any) -> bool:
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _invalid_date_fields(info: dict[str, Any], target: str) -> dict[str, Any]:
    """Supplied values in this target's date fields that are not YYYY-MM-DD.

    The GitLab consumer parses every feature_freeze with exactly this format
    and crashes on its next scheduled run otherwise — a value this function
    would reject is one that function would reject too.
    """
    relevant = DATE_FIELDS & set(REQUIRED_FIELDS[target])
    return {
        field: info.get(field)
        for field in relevant
        if _supplied(info.get(field)) and not _is_iso_date(info.get(field))
    }


def _missing_fields(info: dict[str, Any], target: str) -> list[str]:
    return [field for field in REQUIRED_FIELDS[target] if not _supplied(info.get(field))]


def _version_gate(version: str) -> dict[str, Any] | None:
    """A `diff` report entry for a version outside this script's scope, else None.

    A z-stream is silently out of scope — neither target file has ever tracked
    one. A bare x.y (what the planned-release spreadsheet path normalizes to)
    or anything else unrecognized is a transcription bug, not an out-of-scope
    version, so it is reported rather than silently dropped.
    """
    form = _version_form(version)
    if form == "zstream":
        return {"version": version, "state": "skipped-zstream"}
    if form in ("major-minor", "unrecognized"):
        return {
            "version": version,
            "state": "invalid",
            "error": f"version must be of the form x.y.0; got {version!r}",
        }
    return None


def _version_skip(version: str) -> dict[str, Any] | None:
    """The `render` equivalent of `_version_gate`, in the skip-record shape."""
    form = _version_form(version)
    if form == "zstream":
        return {"version": version, "reason": "zstream"}
    if form in ("major-minor", "unrecognized"):
        return {
            "version": version,
            "reason": "invalid-version",
            "error": f"version must be of the form x.y.0; got {version!r}",
        }
    return None


def _run_json(cmd: list[str]) -> Any:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def gh_api(path: str, method: str = "GET", fields: dict[str, str] | None = None) -> Any:
    cmd = ["gh", "api", path, "--method", method]
    for key, value in (fields or {}).items():
        cmd += ["-f", f"{key}={value}"]
    return _run_json(cmd)


def _gitlab_project_encoded() -> str:
    return GITLAB_PROJECT.replace("/", "%2F")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def cmd_check(_args: argparse.Namespace) -> int:
    checks = []

    gh_status = _run(["gh", "auth", "status"])
    checks.append({"capability": "gh", "status": "pass" if gh_status.returncode == 0 else "fail"})

    glab_status = _run(["glab", "auth", "status", "--hostname", GITLAB_HOST])
    checks.append(
        {
            "capability": f"glab ({GITLAB_HOST})",
            "status": "pass" if glab_status.returncode == 0 else "fail",
        }
    )

    ok = all(c["status"] == "pass" for c in checks)
    print(json.dumps({"ok": ok, "checks": checks}, indent=2))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def fetch_github_file(ref: str = GITHUB_BASE_BRANCH) -> tuple[str, str]:
    """Return (content, blob_sha) for GITHUB_FILE_PATH at ref."""
    data = gh_api(f"repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}?ref={ref}")
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def fetch_gitlab_file(ref: str = GITLAB_BASE_BRANCH) -> tuple[str, str]:
    """Return (content, last_commit_id) for GITLAB_FILE_PATH at ref.

    Uses the file-metadata endpoint rather than /raw so the caller gets a
    revision to compare later — /raw returns bytes with no revision metadata
    at all, which is what let render and apply drift silently in the first
    place.
    """
    encoded_path = GITLAB_FILE_PATH.replace("/", "%2F")
    data = _run_json(
        [
            "glab",
            "api",
            "--hostname",
            GITLAB_HOST,
            f"projects/{_gitlab_project_encoded()}/repository/files/{encoded_path}?ref={ref}",
        ]
    )
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["last_commit_id"]


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def _load_source(source_json: Path) -> dict[str, dict[str, Any]]:
    return json.loads(source_json.read_text())


def _github_releases(doc: CommentedMap) -> dict[str, dict[str, Any]]:
    """Index the GitHub file's list-of-dicts by rhdh-version."""
    indexed = {}
    for entry in doc.get("releases", []) or []:
        indexed[str(entry.get("rhdh-version"))] = entry
    return indexed


def diff_github(source: dict[str, dict[str, Any]], doc: CommentedMap) -> list[dict[str, Any]]:
    existing = _github_releases(doc)
    report = []
    for version, info in source.items():
        gate = _version_gate(version)
        if gate:
            report.append(gate)
            continue
        ff = info.get("feature_freeze")
        if not _supplied(ff):
            report.append({"version": version, "state": "skipped-tbd"})
            continue
        invalid = _invalid_date_fields(info, "github")
        if invalid:
            report.append({"version": version, "state": "invalid", "invalid_fields": invalid})
            continue
        current = existing.get(version)
        if current is None:
            absent = _missing_fields(info, "github")
            if absent:
                report.append({"version": version, "state": "incomplete", "missing_fields": absent})
                continue
            report.append(
                {
                    "version": version,
                    "state": "missing",
                    "desired": {
                        "rhdh-version": version,
                        "backstage-version": info.get("backstage_version"),
                        "feature-freeze": ff,
                    },
                }
            )
            continue

        # Only a supplied field can be stale. An absent one leaves the current
        # value alone rather than overwriting it with a placeholder.
        desired = {"feature-freeze": ff}
        if _supplied(info.get("backstage_version")):
            desired["backstage-version"] = info.get("backstage_version")
        drifted = {
            key: value for key, value in desired.items() if str(current.get(key)) != str(value)
        }
        if drifted:
            report.append(
                {
                    "version": version,
                    "state": "stale",
                    "current": dict(current),
                    "desired": {"rhdh-version": version, **desired},
                }
            )
        else:
            report.append({"version": version, "state": "match"})
    return report


def diff_gitlab(source: dict[str, dict[str, Any]], doc: CommentedMap) -> list[dict[str, Any]]:
    existing = doc.get("releases", CommentedMap()) or {}
    report = []
    for version, info in source.items():
        gate = _version_gate(version)
        if gate:
            report.append(gate)
            continue
        ff = info.get("feature_freeze")
        if not _supplied(ff):
            report.append({"version": version, "state": "skipped-tbd"})
            continue
        invalid = _invalid_date_fields(info, "gitlab")
        if invalid:
            report.append({"version": version, "state": "invalid", "invalid_fields": invalid})
            continue
        current = existing.get(version)
        if current is None:
            absent = _missing_fields(info, "gitlab")
            if absent:
                report.append({"version": version, "state": "incomplete", "missing_fields": absent})
                continue
            report.append(
                {
                    "version": version,
                    "state": "missing",
                    "desired": {key: info.get(key) for key in REQUIRED_FIELDS["gitlab"]},
                }
            )
            continue

        # Only a supplied field can be stale. An absent one leaves the current
        # value alone rather than overwriting it with a placeholder.
        desired = {
            key: info.get(key) for key in REQUIRED_FIELDS["gitlab"] if _supplied(info.get(key))
        }
        if any(str(current.get(key)) != str(value) for key, value in desired.items()):
            report.append(
                {
                    "version": version,
                    "state": "stale",
                    "current": dict(current),
                    "desired": desired,
                }
            )
        else:
            report.append({"version": version, "state": "match"})
    return report


def cmd_diff(args: argparse.Namespace) -> int:
    source = _load_source(Path(args.source_json))
    yaml = YAML()
    yaml.preserve_quotes = True

    github_content, _ = fetch_github_file()
    gitlab_content, _ = fetch_gitlab_file()

    github_doc = yaml.load(github_content)
    gitlab_doc = yaml.load(gitlab_content)

    report = {
        "github": {
            "repo": GITHUB_REPO,
            "path": GITHUB_FILE_PATH,
            "entries": diff_github(source, github_doc),
        },
        "gitlab": {
            "project": GITLAB_PROJECT,
            "path": GITLAB_FILE_PATH,
            "entries": diff_gitlab(source, gitlab_doc),
        },
    }
    print(json.dumps(report, indent=2))
    return 0


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def render_github(
    source: dict[str, dict[str, Any]], doc: CommentedMap
) -> tuple[bool, list[dict[str, Any]]]:
    existing = _github_releases(doc)
    changed = False
    skipped: list[dict[str, Any]] = []
    releases = doc.setdefault("releases", [])
    for version, info in source.items():
        skip = _version_skip(version)
        if skip:
            skipped.append(skip)
            continue
        ff = info.get("feature_freeze")
        if not _supplied(ff):
            skipped.append({"version": version, "reason": "tbd"})
            continue
        invalid = _invalid_date_fields(info, "github")
        if invalid:
            skipped.append({"version": version, "reason": "invalid-date", "fields": invalid})
            continue
        entry = existing.get(version)
        if entry is None:
            absent = _missing_fields(info, "github")
            if absent:
                skipped.append(
                    {"version": version, "reason": "incomplete", "missing_fields": absent}
                )
                continue
            new_entry = CommentedMap()
            new_entry["rhdh-version"] = DQ(version)
            new_entry["backstage-version"] = DQ(info.get("backstage_version"))
            new_entry["feature-freeze"] = DQ(ff)
            releases.append(new_entry)
            changed = True
            continue

        # Write only what the source supplied; an absent field keeps the value
        # already in the file rather than being overwritten with a placeholder.
        if str(entry.get("feature-freeze")) != str(ff):
            entry["feature-freeze"] = DQ(ff)
            changed = True
        backstage = info.get("backstage_version")
        if not _supplied(backstage):
            skipped.append(
                {
                    "version": version,
                    "reason": "fields-not-supplied",
                    "fields": ["backstage_version"],
                }
            )
        elif str(entry.get("backstage-version")) != str(backstage):
            entry["backstage-version"] = DQ(backstage)
            changed = True
    return changed, skipped


def render_gitlab(
    source: dict[str, dict[str, Any]], doc: CommentedMap
) -> tuple[bool, list[dict[str, Any]]]:
    releases = doc.setdefault("releases", CommentedMap())
    changed = False
    skipped: list[dict[str, Any]] = []
    for version, info in source.items():
        skip = _version_skip(version)
        if skip:
            skipped.append(skip)
            continue
        ff = info.get("feature_freeze")
        if not _supplied(ff):
            skipped.append({"version": version, "reason": "tbd"})
            continue
        invalid = _invalid_date_fields(info, "gitlab")
        if invalid:
            skipped.append({"version": version, "reason": "invalid-date", "fields": invalid})
            continue
        entry = releases.get(version)
        if entry is None:
            absent = _missing_fields(info, "gitlab")
            if absent:
                skipped.append(
                    {"version": version, "reason": "incomplete", "missing_fields": absent}
                )
                continue
            new_entry = CommentedMap()
            for key in REQUIRED_FIELDS["gitlab"]:
                new_entry[key] = DQ(info.get(key))
            releases[DQ(version)] = new_entry
            changed = True
            continue

        # Write only what the source supplied; an absent field keeps the value
        # already in the file rather than being overwritten with a placeholder.
        unsupplied = _missing_fields(info, "gitlab")
        if unsupplied:
            skipped.append(
                {"version": version, "reason": "fields-not-supplied", "fields": unsupplied}
            )
        for key in REQUIRED_FIELDS["gitlab"]:
            value = info.get(key)
            if not _supplied(value):
                continue
            if str(entry.get(key)) != str(value):
                entry[key] = DQ(value)
                changed = True
    return changed, skipped


def cmd_render(args: argparse.Namespace) -> int:
    source = _load_source(Path(args.source_json))
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    if args.target == "github":
        content, source_revision = fetch_github_file()
        doc = yaml.load(content)
        changed, skipped = render_github(source, doc)
    else:
        content, source_revision = fetch_gitlab_file()
        doc = yaml.load(content)
        changed, skipped = render_gitlab(source, doc)

    out_path = Path(args.output)
    with out_path.open("w") as fh:
        yaml.dump(doc, fh)

    print(
        json.dumps(
            {
                "target": args.target,
                "changed": changed,
                "output": str(out_path),
                "skipped": skipped,
                "source_revision": source_revision,
            }
        )
    )
    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _refuse_protected_branch(target: str, base_branch: str) -> dict[str, Any] | None:
    """Refuse to let BRANCH_NAME collide with the branch apply would commit on top of.

    BRANCH_NAME is RELEASE_DATE_UPDATE_BRANCH, documented as a testing-only
    override. If it is ever misconfigured to equal the base branch, the
    "Reference already exists" fallback below reads that as "the update branch
    already exists" and proceeds to PUT straight onto the base branch,
    bypassing the PR/MR review this whole workflow depends on. Checked before
    any API call, so a bad configuration touches nothing.
    """
    if BRANCH_NAME == base_branch or PROTECTED_BRANCH_RE.match(BRANCH_NAME):
        return {
            "target": target,
            "ok": False,
            "error": (
                f"refusing to apply: RELEASE_DATE_UPDATE_BRANCH={BRANCH_NAME!r} is a "
                "protected branch, not an update branch"
            ),
        }
    return None


def _refuse_source_drift(target: str, expected: str | None, current: str) -> dict[str, Any] | None:
    """Refuse when the base file has moved since render ran.

    `render` only ever wrote a blob sha / last_commit_id into its JSON output;
    it never stopped `apply` from pushing stale bytes with it. Without this,
    a base-file change made during human review between render and apply is
    silently reverted by the push, and what lands does not match what was
    approved.
    """
    if expected is not None and expected != current:
        return {
            "target": target,
            "ok": False,
            "error": (
                f"refusing to apply: source moved from {expected!r} to {current!r} "
                "since render ran; re-run render and get the new diff re-approved"
            ),
        }
    return None


def apply_github(rendered_path: Path, expect_revision: str | None = None) -> dict[str, Any]:
    refused = _refuse_protected_branch("github", GITHUB_BASE_BRANCH)
    if refused:
        return refused

    if not expect_revision:
        return {"target": "github", "ok": False, "error": "render-time revision is required"}

    if expect_revision is not None:
        try:
            _, current_revision = fetch_github_file(ref=GITHUB_BASE_BRANCH)
        except Exception as exc:
            return {
                "target": "github",
                "ok": False,
                "error": f"could not verify source revision: {exc}",
            }
        drift = _refuse_source_drift("github", expect_revision, current_revision)
        if drift:
            return drift

    ref_resp = _run(["gh", "api", f"repos/{GITHUB_REPO}/git/ref/heads/{GITHUB_BASE_BRANCH}"])
    if ref_resp.returncode != 0:
        return {"target": "github", "ok": False, "error": ref_resp.stderr.strip()}
    base_sha = json.loads(ref_resp.stdout)["object"]["sha"]

    # Finish reading local input before the first write (branch creation).
    try:
        content_b64 = base64.b64encode(rendered_path.read_bytes()).decode("ascii")
    except OSError as exc:
        return {"target": "github", "ok": False, "error": f"could not read rendered file: {exc}"}

    create_branch = _run(
        [
            "gh",
            "api",
            f"repos/{GITHUB_REPO}/git/refs",
            "--method",
            "POST",
            "-f",
            "ref=refs/heads/" + BRANCH_NAME,
            "-f",
            f"sha={base_sha}",
        ]
    )
    branch_created = create_branch.returncode == 0
    if not branch_created and "Reference already exists" not in create_branch.stderr:
        return {"target": "github", "ok": False, "error": create_branch.stderr.strip()}

    # The destination must still match the approved render's baseline. Using
    # its latest SHA without this check would bless and overwrite branch edits.
    try:
        _, file_sha = fetch_github_file(ref=BRANCH_NAME)
    except RuntimeError as exc:
        return {"target": "github", "ok": False, "error": f"could not verify update branch: {exc}"}
    if file_sha != expect_revision:
        return {
            "target": "github",
            "ok": False,
            "error": "update branch differs from the rendered baseline; reconcile its PR before re-rendering",
        }

    fields = {
        "message": "Update RHDH release schedule dates",
        "content": content_b64,
        "branch": BRANCH_NAME,
    }
    fields["sha"] = file_sha
    try:
        put_result = gh_api(f"repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}", "PUT", fields)
    except RuntimeError as exc:
        return {"target": "github", "ok": False, "error": str(exc)}

    # The push already succeeded above; a failure here must not lose that
    # result, so default to an empty list rather than letting it raise.
    try:
        existing_pr = _run_json(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                GITHUB_REPO,
                "--base",
                GITHUB_BASE_BRANCH,
                "--head",
                BRANCH_NAME,
                "--state",
                "open",
                "--json",
                "url,title",
            ]
        )
    except RuntimeError:
        existing_pr = None
    return {
        "target": "github",
        "ok": True,
        "branch": BRANCH_NAME,
        "branch_created": branch_created,
        "commit": put_result.get("commit", {}).get("sha") if put_result else None,
        "existing_open_pr": existing_pr or [],
    }


def apply_gitlab(rendered_path: Path, expect_revision: str | None = None) -> dict[str, Any]:
    refused = _refuse_protected_branch("gitlab", GITLAB_BASE_BRANCH)
    if refused:
        return refused

    if not expect_revision:
        return {"target": "gitlab", "ok": False, "error": "render-time revision is required"}

    if expect_revision is not None:
        try:
            _, current_revision = fetch_gitlab_file(ref=GITLAB_BASE_BRANCH)
        except RuntimeError as exc:
            return {
                "target": "gitlab",
                "ok": False,
                "error": f"could not verify source revision: {exc}",
            }
        drift = _refuse_source_drift("gitlab", expect_revision, current_revision)
        if drift:
            return drift

    try:
        content = rendered_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {"target": "gitlab", "ok": False, "error": f"could not read rendered file: {exc}"}

    project = _gitlab_project_encoded()
    create_branch = _run(
        [
            "glab",
            "api",
            "--hostname",
            GITLAB_HOST,
            f"projects/{project}/repository/branches",
            "--method",
            "POST",
            "-f",
            f"branch={BRANCH_NAME}",
            "-f",
            f"ref={GITLAB_BASE_BRANCH}",
        ]
    )
    branch_created = create_branch.returncode == 0
    if not branch_created and "already exists" not in create_branch.stderr:
        return {"target": "gitlab", "ok": False, "error": create_branch.stderr.strip()}

    encoded_path = GITLAB_FILE_PATH.replace("/", "%2F")
    # Check against render, then lock the write against any later branch edit.
    # A failed read must not turn off optimistic locking.
    try:
        _, branch_last_commit_id = fetch_gitlab_file(ref=BRANCH_NAME)
    except RuntimeError as exc:
        return {"target": "gitlab", "ok": False, "error": f"could not verify update branch: {exc}"}
    if branch_last_commit_id != expect_revision:
        return {
            "target": "gitlab",
            "ok": False,
            "error": "update branch differs from the rendered baseline; reconcile its MR before re-rendering",
        }

    put_fields = [
        "-f",
        f"branch={BRANCH_NAME}",
        "-f",
        "commit_message=Update RHDH release schedule dates",
        "-f",
        f"content={content}",
    ]
    put_fields += ["-f", f"last_commit_id={branch_last_commit_id}"]

    # GITLAB_FILE_PATH is release_calendar.yaml, which already exists on every
    # branch — this is always an update (PUT), never a create (POST).
    update = _run(
        [
            "glab",
            "api",
            "--hostname",
            GITLAB_HOST,
            f"projects/{project}/repository/files/{encoded_path}",
            "--method",
            "PUT",
            *put_fields,
        ]
    )
    if update.returncode != 0:
        return {"target": "gitlab", "ok": False, "error": update.stderr.strip()}

    existing_mr = _run(
        [
            "glab",
            "api",
            "--hostname",
            GITLAB_HOST,
            f"projects/{project}/merge_requests?source_branch={quote(BRANCH_NAME, safe='')}&state=opened",
        ]
    )
    existing = json.loads(existing_mr.stdout) if existing_mr.returncode == 0 else []
    return {
        "target": "gitlab",
        "ok": True,
        "branch": BRANCH_NAME,
        "branch_created": branch_created,
        "existing_open_mr": existing,
    }


def cmd_apply(args: argparse.Namespace) -> int:
    if not args.confirm:
        print(json.dumps({"ok": False, "error": "refusing to apply without --confirm"}))
        return 1

    targets = ("github", "gitlab") if args.target == "all" else (args.target,)
    errors = {}
    for target in targets:
        rendered = getattr(args, f"{target}_rendered")
        revision = getattr(args, f"{target}_expect_revision")
        if not rendered:
            errors[target] = f"--{target}-rendered is required"
        elif not revision:
            errors[target] = f"--{target}-expect-revision is required"
        else:
            try:
                Path(rendered).read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors[target] = f"could not read rendered file: {exc}"

    results = []
    failed = False
    for target in targets:
        if target in errors:
            result = {"target": target, "ok": False, "error": errors[target]}
        elif errors or failed:
            result = {
                "target": target,
                "ok": False,
                "skipped": True,
                "error": "not attempted because another target failed",
            }
        else:
            apply = {"github": apply_github, "gitlab": apply_gitlab}[target]
            try:
                result = apply(
                    Path(getattr(args, f"{target}_rendered")),
                    getattr(args, f"{target}_expect_revision"),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                result = {"target": target, "ok": False, "error": str(exc)}
        results.append(result)
        failed = failed or not result.get("ok")

    ok = all(r.get("ok") for r in results)
    print(json.dumps({"ok": ok, "results": results}, indent=2))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Verify gh and glab authentication")

    diff_p = sub.add_parser("diff", help="Compare source-of-truth dates against both target files")
    diff_p.add_argument("--source-json", required=True)

    render_p = sub.add_parser("render", help="Render an updated copy of one target file")
    render_p.add_argument("--target", choices=["github", "gitlab"], required=True)
    render_p.add_argument("--source-json", required=True)
    render_p.add_argument("--output", required=True)

    apply_p = sub.add_parser("apply", help="Push rendered file(s) to the skill's branch")
    apply_p.add_argument("--target", choices=["github", "gitlab", "all"], default="all")
    apply_p.add_argument("--github-rendered")
    apply_p.add_argument("--gitlab-rendered")
    apply_p.add_argument(
        "--github-expect-revision",
        help="Base-branch blob sha render_github was built from; refuse if it has since moved",
    )
    apply_p.add_argument(
        "--gitlab-expect-revision",
        help="Base-branch last_commit_id render_gitlab was built from; refuse if it has since moved",
    )
    apply_p.add_argument("--confirm", action="store_true")

    args = parser.parse_args(argv)

    commands = {
        "check": cmd_check,
        "diff": cmd_diff,
        "render": cmd_render,
        "apply": cmd_apply,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
