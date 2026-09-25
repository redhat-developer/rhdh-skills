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
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def glab_api(path: str, method: str = "GET", fields: dict[str, str] | None = None) -> Any:
    cmd = ["glab", "api", "--hostname", GITLAB_HOST, path, "--method", method]
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


def fetch_gitlab_file(ref: str = GITLAB_BASE_BRANCH) -> str:
    """Return content for GITLAB_FILE_PATH at ref."""
    encoded_path = GITLAB_FILE_PATH.replace("/", "%2F")
    cmd = [
        "glab",
        "api",
        "--hostname",
        GITLAB_HOST,
        f"projects/{_gitlab_project_encoded()}/repository/files/{encoded_path}/raw?ref={ref}",
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"glab fetch failed: {result.stderr.strip()}")
    return result.stdout


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
        ff = info.get("feature_freeze")
        if ff in TBD_VALUES:
            report.append({"version": version, "state": "skipped-tbd"})
            continue
        current = existing.get(version)
        desired = {
            "rhdh-version": version,
            "backstage-version": info.get("backstage_version"),
            "feature-freeze": ff,
        }
        if current is None:
            report.append({"version": version, "state": "missing", "desired": desired})
        elif str(current.get("backstage-version")) != str(desired["backstage-version"]) or str(
            current.get("feature-freeze")
        ) != str(desired["feature-freeze"]):
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


def diff_gitlab(source: dict[str, dict[str, Any]], doc: CommentedMap) -> list[dict[str, Any]]:
    existing = doc.get("releases", CommentedMap()) or {}
    report = []
    for version, info in source.items():
        ff = info.get("feature_freeze")
        if ff in TBD_VALUES:
            report.append({"version": version, "state": "skipped-tbd"})
            continue
        desired = {
            "feature_freeze": ff,
            "code_freeze": info.get("code_freeze"),
            "ga_push": info.get("ga_push"),
            "backstage_version": info.get("backstage_version"),
        }
        current = existing.get(version)
        if current is None:
            report.append({"version": version, "state": "missing", "desired": desired})
        elif any(str(current.get(k)) != str(v) for k, v in desired.items()):
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
    gitlab_content = fetch_gitlab_file()

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


def render_github(source: dict[str, dict[str, Any]], doc: CommentedMap) -> bool:
    existing = _github_releases(doc)
    changed = False
    releases = doc.setdefault("releases", [])
    for version, info in source.items():
        ff = info.get("feature_freeze")
        if ff in TBD_VALUES:
            continue
        entry = existing.get(version)
        if entry is None:
            new_entry = CommentedMap()
            new_entry["rhdh-version"] = DQ(version)
            new_entry["backstage-version"] = DQ(info.get("backstage_version"))
            new_entry["feature-freeze"] = DQ(ff)
            releases.append(new_entry)
            changed = True
        else:
            if str(entry.get("backstage-version")) != str(info.get("backstage_version")):
                entry["backstage-version"] = DQ(info.get("backstage_version"))
                changed = True
            if str(entry.get("feature-freeze")) != str(ff):
                entry["feature-freeze"] = DQ(ff)
                changed = True
    return changed


def render_gitlab(source: dict[str, dict[str, Any]], doc: CommentedMap) -> bool:
    releases = doc.setdefault("releases", CommentedMap())
    changed = False
    for version, info in source.items():
        ff = info.get("feature_freeze")
        if ff in TBD_VALUES:
            continue
        desired = {
            "feature_freeze": ff,
            "code_freeze": info.get("code_freeze"),
            "ga_push": info.get("ga_push"),
            "backstage_version": info.get("backstage_version"),
        }
        entry = releases.get(version)
        if entry is None:
            new_entry = CommentedMap()
            for key, value in desired.items():
                new_entry[key] = DQ(value)
            releases[DQ(version)] = new_entry
            changed = True
        else:
            for key, value in desired.items():
                if str(entry.get(key)) != str(value):
                    entry[key] = DQ(value)
                    changed = True
    return changed


def cmd_render(args: argparse.Namespace) -> int:
    source = _load_source(Path(args.source_json))
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    if args.target == "github":
        content, _ = fetch_github_file()
        doc = yaml.load(content)
        changed = render_github(source, doc)
    else:
        content = fetch_gitlab_file()
        doc = yaml.load(content)
        changed = render_gitlab(source, doc)

    out_path = Path(args.output)
    with out_path.open("w") as fh:
        yaml.dump(doc, fh)

    print(json.dumps({"target": args.target, "changed": changed, "output": str(out_path)}))
    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def apply_github(rendered_path: Path) -> dict[str, Any]:
    ref_resp = _run(["gh", "api", f"repos/{GITHUB_REPO}/git/ref/heads/{GITHUB_BASE_BRANCH}"])
    base_sha = json.loads(ref_resp.stdout)["object"]["sha"]

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

    # File sha on the branch (falls back to base sha for a brand-new branch).
    try:
        _, file_sha = fetch_github_file(ref=BRANCH_NAME)
    except Exception:
        file_sha = None

    content_b64 = base64.b64encode(rendered_path.read_bytes()).decode("ascii")
    fields = {
        "message": "Update RHDH release schedule dates",
        "content": content_b64,
        "branch": BRANCH_NAME,
    }
    if file_sha:
        fields["sha"] = file_sha
    put_result = gh_api(f"repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}", "PUT", fields)

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
    return {
        "target": "github",
        "ok": True,
        "branch": BRANCH_NAME,
        "branch_created": branch_created,
        "commit": put_result.get("commit", {}).get("sha") if put_result else None,
        "existing_open_pr": existing_pr or [],
    }


def apply_gitlab(rendered_path: Path) -> dict[str, Any]:
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
    content = rendered_path.read_text()

    # Try update first; fall back to create for a brand-new file.
    update = _run(
        [
            "glab",
            "api",
            "--hostname",
            GITLAB_HOST,
            f"projects/{project}/repository/files/{encoded_path}",
            "--method",
            "PUT",
            "-f",
            f"branch={BRANCH_NAME}",
            "-f",
            "commit_message=Update RHDH release schedule dates",
            "-f",
            f"content={content}",
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
            f"projects/{project}/merge_requests?source_branch={BRANCH_NAME}&state=opened",
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

    results = []
    if args.target in ("github", "all"):
        results.append(apply_github(Path(args.github_rendered)))
    if args.target in ("gitlab", "all"):
        results.append(apply_gitlab(Path(args.gitlab_rendered)))

    ok = all(r.get("ok") for r in results)
    print(json.dumps({"ok": ok, "results": results}, indent=2))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
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
