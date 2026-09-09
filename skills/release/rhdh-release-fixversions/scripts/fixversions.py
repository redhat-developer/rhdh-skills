#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""List and synchronize Jira fix versions across RHIDP, RHDHPLAN, and RHDHBUGS."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from _auth import JiraAuth, resolve_jira_auth  # noqa: E402
from _fixversions_core import (  # noqa: E402
    DEFAULT_RECENT_DAYS,
    LIFECYCLE_VALUES,
    PROJECTS,
    close_out_report,
    collect_names,
    compute_plan,
    count_by_lifecycle,
    diff_report,
    filter_names_by_recency,
    index_by_name,
    next_z_stream_follow_up,
    recent_filter_meta,
    status_report,
    version_summary,
)
from _release_dates import lookup_release_doc, lookup_release_feature  # noqa: E402
from _stream_lifecycle import lookup_rhdh_stream_support  # noqa: E402
from _stream_versions import (  # noqa: E402
    next_z_stream_version,
    release_feature_summary,
    y_stream_key,
)

API_BASE = "/rest/api/3"


class JiraVersionClient:
    def __init__(self, auth: JiraAuth) -> None:
        self.auth = auth
        credentials = f"{auth.login}:{auth.token}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        self._headers = {
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.auth.server}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                if not body:
                    return None
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Jira HTTP {exc.code} {method} {path}: {detail}") from exc

    def list_versions(self, project_key: str) -> list[dict[str, Any]]:
        return self._request("GET", f"{API_BASE}/project/{project_key}/versions")

    def create_version(self, project_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "name": fields["name"],
            "project": project_key,
        }
        if fields.get("description"):
            payload["description"] = fields["description"]
        if fields.get("startDate"):
            payload["startDate"] = fields["startDate"]
        if fields.get("releaseDate"):
            payload["releaseDate"] = fields["releaseDate"]
        if fields.get("released"):
            payload["released"] = True
        if fields.get("archived"):
            payload["archived"] = True
        created = self._request("POST", f"{API_BASE}/version", payload)
        if fields.get("archived") and created and created.get("id"):
            return self.update_version(str(created["id"]), {"archived": True})
        return created

    def update_version(self, version_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key in ("name", "description", "startDate", "releaseDate", "released", "archived"):
            if key in fields:
                value = fields[key]
                if key in ("description", "startDate", "releaseDate") and value == "":
                    payload[key] = ""
                else:
                    payload[key] = value
        return self._request("PUT", f"{API_BASE}/version/{version_id}", payload)

    def delete_version(self, version_id: str, move_fix_issues_to: str | None = None) -> None:
        query = {}
        if move_fix_issues_to:
            query["moveFixIssuesTo"] = move_fix_issues_to
        self._request("DELETE", f"{API_BASE}/version/{version_id}", query=query or None)

    def issue_count_for_version(self, project_key: str, version_name: str) -> int:
        jql = f'project = {project_key} AND fixVersion = "{version_name}"'
        result = self._request(
            "POST",
            f"{API_BASE}/search/approximate-count",
            payload={"jql": jql},
        )
        if not isinstance(result, dict):
            return 0
        return int(result.get("count", 0))

    def search_issues(
        self,
        jql: str,
        *,
        max_results: int = 5,
        fields: str = "summary,description,status",
    ) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"{API_BASE}/search/jql",
            query={
                "jql": jql,
                "maxResults": str(max_results),
                "fields": fields,
            },
        )
        if not isinstance(result, dict):
            return []
        return result.get("issues", [])

    def get_issue(self, issue_key: str, *, fields: str = "description") -> dict[str, Any]:
        result = self._request(
            "GET",
            f"{API_BASE}/issue/{issue_key}",
            query={"fields": fields},
        )
        return result if isinstance(result, dict) else {}


def load_by_project(client: JiraVersionClient) -> dict[str, dict[str, dict[str, Any]]]:
    by_project: dict[str, dict[str, dict[str, Any]]] = {}
    for project in PROJECTS:
        versions = client.list_versions(project)
        by_project[project] = index_by_name(versions)
    return by_project


def cmd_check(_args: argparse.Namespace) -> int:
    auth = resolve_jira_auth()
    client = JiraVersionClient(auth)
    projects: list[dict[str, Any]] = []
    ok = True
    for project in PROJECTS:
        try:
            versions = client.list_versions(project)
            indexed = index_by_name(versions)
            projects.append(
                {
                    "project": project,
                    "status": "pass",
                    "count": len(versions),
                    "lifecycle_counts": count_by_lifecycle(indexed),
                }
            )
        except RuntimeError as exc:
            ok = False
            projects.append({"project": project, "status": "fail", "error": str(exc)})
    payload = {
        "ok": ok,
        "server": auth.server,
        "auth_source": auth.auth_source,
        "projects": projects,
    }
    print(json.dumps(payload, indent=2))
    return 0 if ok else 1


def _filter_by_lifecycle(
    versions: list[dict[str, Any]],
    lifecycle: str | None,
) -> list[dict[str, Any]]:
    if lifecycle is None:
        return versions
    return [item for item in versions if item["lifecycle"] == lifecycle]


def _recency_names(
    args: argparse.Namespace, by_project: dict[str, dict[str, dict[str, Any]]]
) -> tuple[set[str] | None, dict[str, str]]:
    if getattr(args, "all_versions", False):
        return None, {"scope": "all"}
    within_days = getattr(args, "within_days", DEFAULT_RECENT_DAYS)
    names = filter_names_by_recency(by_project, collect_names(by_project), within_days=within_days)
    meta = recent_filter_meta(within_days=within_days)
    meta["scope"] = "recent"
    meta["matching_versions"] = str(len(names))
    return names, meta


def _add_recency_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--all-versions",
        action="store_true",
        help="Include every fix version (default: recent window only)",
    )
    parser.add_argument(
        "--within-days",
        type=int,
        default=DEFAULT_RECENT_DAYS,
        metavar="N",
        help=f"Recent window in days when not using --all-versions (default: {DEFAULT_RECENT_DAYS})",
    )


def cmd_list(args: argparse.Namespace) -> int:
    client = JiraVersionClient(resolve_jira_auth())
    by_project = load_by_project(client)
    recent_names, filter_meta = _recency_names(args, by_project)
    out: dict[str, Any] = {"filter": filter_meta, "projects": {}}
    for project in PROJECTS:
        versions = by_project[project].values()
        if recent_names is not None:
            versions = [v for v in versions if v["name"] in recent_names]
        summaries = [version_summary(v) for v in sorted(versions, key=lambda item: item["name"])]
        out["projects"][project] = {
            "lifecycle_counts": count_by_lifecycle(
                {v["name"]: v for v in versions},
            ),
            "versions": _filter_by_lifecycle(summaries, args.lifecycle),
        }
    print(json.dumps(out, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    client = JiraVersionClient(resolve_jira_auth())
    by_project = load_by_project(client)
    print(json.dumps(status_report(by_project, args.version), indent=2))
    return 0


def _next_z_stream_follow_up(
    client: JiraVersionClient,
    by_project: dict[str, dict[str, dict[str, Any]]],
    version: str,
) -> dict[str, Any] | None:
    next_version = next_z_stream_version(version)
    if next_version is None:
        return None

    stream_key = y_stream_key(version)
    stream_lifecycle = lookup_rhdh_stream_support(stream_key) if stream_key else None
    next_release_feature = lookup_release_feature(client, next_version)
    return next_z_stream_follow_up(
        by_project,
        version,
        next_version=next_version,
        stream_lifecycle=stream_lifecycle,
        next_release_feature=next_release_feature,
        release_feature_summary=release_feature_summary(next_version),
    )


def cmd_close_check(args: argparse.Namespace) -> int:
    client = JiraVersionClient(resolve_jira_auth())
    by_project = load_by_project(client)
    release_feature = lookup_release_feature(client, args.version)
    next_z_stream = None
    if not args.skip_next_stream:
        next_z_stream = _next_z_stream_follow_up(client, by_project, args.version)
    report = close_out_report(
        by_project,
        args.version,
        release_feature,
        next_z_stream=next_z_stream,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def cmd_diff(args: argparse.Namespace) -> int:
    client = JiraVersionClient(resolve_jira_auth())
    by_project = load_by_project(client)
    recent_names, filter_meta = _recency_names(args, by_project)
    report = diff_report(by_project, names=recent_names)
    payload: dict[str, Any] = {"filter": filter_meta, "drift": report}
    if args.prune:
        payload["orphans"] = [
            row["name"]
            for row in report
            if sum(1 for view in row["projects"].values() if view["present"]) == 1
        ]
    print(json.dumps(payload, indent=2))
    return 0


def _override_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    override: dict[str, Any] = {}
    if args.description is not None:
        override["description"] = args.description
    if args.start_date is not None:
        override["startDate"] = args.start_date
    if args.release_date is not None:
        override["releaseDate"] = args.release_date
    if args.released is not None:
        override["released"] = args.released
    if args.archived is not None:
        override["archived"] = args.archived
    return override or None


def _plan_version_names(
    args: argparse.Namespace, by_project: dict[str, dict[str, dict[str, Any]]]
) -> set[str]:
    if args.name:
        return {args.name}
    if args.all_versions:
        return collect_names(by_project)
    return filter_names_by_recency(
        by_project,
        collect_names(by_project),
        within_days=args.within_days,
    )


def _lookup_release_docs(
    client: JiraVersionClient,
    version_names: set[str],
) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for version in sorted(version_names):
        doc = lookup_release_doc(client, version)
        if doc is not None:
            docs[version] = doc
    return docs


def cmd_plan(args: argparse.Namespace) -> int:
    client = JiraVersionClient(resolve_jira_auth())
    by_project = load_by_project(client)
    if args.name:
        filter_meta = {"scope": "single", "version": args.name}
    else:
        _, filter_meta = _recency_names(args, by_project)

    release_docs: dict[str, dict[str, Any]] = {}
    if not args.no_release_doc:
        release_docs = _lookup_release_docs(client, _plan_version_names(args, by_project))
        if release_docs:
            filter_meta["release_docs"] = {
                version: {
                    "issue_key": doc["issue_key"],
                    "issue_url": doc["issue_url"],
                    "has_usable_dates": doc["has_usable_dates"],
                    "milestones": doc["milestones"],
                }
                for version, doc in release_docs.items()
            }

    operations = compute_plan(
        by_project,
        prune=args.prune,
        only_name=args.name,
        override_meta=_override_from_args(args),
        within_days=getattr(args, "within_days", DEFAULT_RECENT_DAYS),
        all_versions=getattr(args, "all_versions", False) or args.name is not None,
        release_docs=release_docs,
    )
    print(json.dumps({"filter": filter_meta, "operations": operations}, indent=2))
    return 0


def cmd_ensure(args: argparse.Namespace) -> int:
    args.name = args.version
    return cmd_plan(args)


def _resolve_move_target_id(
    client: JiraVersionClient,
    by_project: dict[str, dict[str, dict[str, Any]]],
    move_to_name: str,
    project: str,
) -> str:
    version = by_project.get(project, {}).get(move_to_name)
    if version:
        return str(version["id"])
    for proj_versions in by_project.values():
        if move_to_name in proj_versions:
            return str(proj_versions[move_to_name]["id"])
    raise RuntimeError(
        f"moveFixIssuesTo version {move_to_name!r} not found in any in-scope project"
    )


def cmd_apply(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    operations = plan.get("operations", plan)
    client = JiraVersionClient(resolve_jira_auth())
    by_project = load_by_project(client)
    outcomes: list[dict[str, Any]] = []

    for op in operations:
        action = op["action"]
        try:
            if action == "create":
                fields = dict(op["fields"])
                created = client.create_version(op["project"], fields)
                outcomes.append(
                    {
                        "action": action,
                        "project": op["project"],
                        "name": op["name"],
                        "status": "ok",
                        "version_id": created.get("id") if created else None,
                    }
                )
            elif action == "update":
                client.update_version(str(op["version_id"]), op["to"])
                outcomes.append(
                    {
                        "action": action,
                        "project": op["project"],
                        "name": op["name"],
                        "status": "ok",
                        "version_id": op["version_id"],
                    }
                )
            elif action == "delete":
                count = client.issue_count_for_version(op["project"], op["name"])
                if count and not args.move_issues_to:
                    outcomes.append(
                        {
                            "action": action,
                            "project": op["project"],
                            "name": op["name"],
                            "status": "skipped",
                            "reason": f"{count} issues still reference this version; pass --move-issues-to",
                        }
                    )
                    continue
                move_id = None
                if args.move_issues_to:
                    move_id = _resolve_move_target_id(
                        client, by_project, args.move_issues_to, op["project"]
                    )
                client.delete_version(str(op["version_id"]), move_id)
                outcomes.append(
                    {
                        "action": action,
                        "project": op["project"],
                        "name": op["name"],
                        "status": "ok",
                        "version_id": op["version_id"],
                        "moved_issues_to": args.move_issues_to,
                    }
                )
            else:
                outcomes.append({"action": action, "status": "skipped", "reason": "unknown action"})
        except RuntimeError as exc:
            outcomes.append(
                {
                    "action": action,
                    "project": op.get("project"),
                    "name": op.get("name"),
                    "status": "failed",
                    "error": str(exc),
                }
            )

    print(json.dumps({"outcomes": outcomes}, indent=2))
    failed = any(o.get("status") == "failed" for o in outcomes)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RHDH fix version sync across RHIDP, RHDHPLAN, RHDHBUGS"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        help="JSON output (always emitted; flag accepted for parity with release.py)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "check",
        parents=[common],
        help="Verify REST auth and project version access",
    )

    p = sub.add_parser(
        "list",
        parents=[common],
        help="List fix versions per project with lifecycle state",
    )
    p.add_argument(
        "--lifecycle",
        choices=LIFECYCLE_VALUES,
        help="Only versions in this state (archived, released, unreleased)",
    )
    _add_recency_args(p)

    p = sub.add_parser(
        "status",
        parents=[common],
        help="Lifecycle and sync for one version across all projects",
    )
    p.add_argument("version", help="Fix version name (e.g. 1.11.0)")

    p = sub.add_parser(
        "close-check",
        parents=[common],
        help="Verify fix versions are released before closing the release Feature",
    )
    p.add_argument("version", help="Fix version name (e.g. 1.11.0)")
    p.add_argument(
        "--skip-next-stream",
        action="store_true",
        help="Do not check RHDH stream lifecycle or suggest the next z-stream version",
    )

    p = sub.add_parser("diff", parents=[common], help="Show cross-project drift")
    p.add_argument("--prune", action="store_true", help="Also list orphan version names")
    _add_recency_args(p)

    for name in ("plan", "ensure"):
        p = sub.add_parser(
            name,
            parents=[common],
            help="Build sync operations" if name == "plan" else "Plan ensure for one version",
        )
        if name == "ensure":
            p.add_argument("version", help="Fix version name (e.g. 1.11.0)")
        else:
            p.add_argument("--name", help="Limit plan to one version name")
        p.add_argument("--prune", action="store_true", help="Include delete for orphan versions")
        p.add_argument("--description")
        p.add_argument("--start-date")
        p.add_argument("--release-date")
        p.add_argument("--released", action=argparse.BooleanOptionalAction)
        p.add_argument("--archived", action=argparse.BooleanOptionalAction)
        p.add_argument(
            "--no-release-doc",
            action="store_true",
            help="Do not read milestone dates from the RHDHPLAN release Feature",
        )
        if name == "plan":
            _add_recency_args(p)

    p = sub.add_parser("apply", parents=[common], help="Apply an approved plan JSON file")
    p.add_argument("--plan", required=True, help="Path to plan JSON from plan/ensure")
    p.add_argument(
        "--move-issues-to",
        help="Target version name when deleting a version that still has issues",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "check": cmd_check,
        "list": cmd_list,
        "status": cmd_status,
        "close-check": cmd_close_check,
        "diff": cmd_diff,
        "plan": cmd_plan,
        "ensure": cmd_ensure,
        "apply": cmd_apply,
    }
    try:
        return handlers[args.command](args)
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
