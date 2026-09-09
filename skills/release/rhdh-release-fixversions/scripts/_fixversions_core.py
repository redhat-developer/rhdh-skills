"""Pure fix-version sync logic — no HTTP, no credentials."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

PROJECTS = ("RHIDP", "RHDHPLAN", "RHDHBUGS")
DEFAULT_RECENT_DAYS = 365
CANONICAL_ORDER = PROJECTS
SYNC_FIELDS = ("description", "startDate", "releaseDate", "released", "archived")
LIFECYCLE_ARCHIVED = "archived"
LIFECYCLE_RELEASED = "released"
LIFECYCLE_UNRELEASED = "unreleased"
LIFECYCLE_VALUES = (LIFECYCLE_ARCHIVED, LIFECYCLE_RELEASED, LIFECYCLE_UNRELEASED)


def version_meta(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": version.get("name", ""),
        "description": version.get("description") or "",
        "startDate": version.get("startDate") or "",
        "releaseDate": version.get("releaseDate") or "",
        "released": bool(version.get("released")),
        "archived": bool(version.get("archived")),
    }


def lifecycle_from_meta(meta: dict[str, Any]) -> str:
    """Map version metadata to Jira's effective lifecycle state."""
    if meta.get("archived"):
        return LIFECYCLE_ARCHIVED
    if meta.get("released"):
        return LIFECYCLE_RELEASED
    return LIFECYCLE_UNRELEASED


def version_lifecycle(version: dict[str, Any]) -> str:
    return lifecycle_from_meta(version_meta(version))


def version_summary(version: dict[str, Any]) -> dict[str, Any]:
    """Compact read model for list/status output."""
    meta = version_meta(version)
    return {
        "id": version.get("id"),
        "name": meta["name"],
        "lifecycle": lifecycle_from_meta(meta),
        "released": meta["released"],
        "archived": meta["archived"],
        "startDate": meta["startDate"] or None,
        "releaseDate": meta["releaseDate"] or None,
        "description": meta["description"] or None,
    }


def project_version_view(
    current: dict[str, Any] | None,
    target_meta: dict[str, Any],
) -> dict[str, Any]:
    """Per-project presence, lifecycle, and sync against canonical metadata."""
    canonical_lifecycle = lifecycle_from_meta(target_meta)
    if current is None:
        return {
            "present": False,
            "lifecycle": None,
            "canonical_lifecycle": canonical_lifecycle,
            "sync": "missing",
        }
    current_meta = version_meta(current)
    lifecycle = lifecycle_from_meta(current_meta)
    sync = "ok" if current_meta == target_meta else "drift"
    return {
        "present": True,
        "id": current.get("id"),
        "lifecycle": lifecycle,
        "canonical_lifecycle": canonical_lifecycle,
        "lifecycle_matches": lifecycle == canonical_lifecycle,
        "sync": sync,
        "released": current_meta["released"],
        "archived": current_meta["archived"],
        "releaseDate": current_meta["releaseDate"] or None,
    }


def index_by_name(versions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {v["name"]: v for v in versions if v.get("name")}


def find_canonical(
    by_project: dict[str, dict[str, dict[str, Any]]],
    name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    for project in CANONICAL_ORDER:
        version = by_project.get(project, {}).get(name)
        if version is not None:
            return version, project
    return None, None


def collect_names(by_project: dict[str, dict[str, dict[str, Any]]]) -> set[str]:
    names: set[str] = set()
    for versions in by_project.values():
        names.update(versions.keys())
    return names


def parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def version_reference_date(version: dict[str, Any]) -> date | None:
    """Best available date for recency — release date, then start date."""
    meta = version_meta(version)
    for key in ("releaseDate", "startDate"):
        parsed = parse_iso_date(meta[key])
        if parsed is not None:
            return parsed
    return None


def is_version_recent(
    by_project: dict[str, dict[str, dict[str, Any]]],
    name: str,
    *,
    cutoff: date,
) -> bool:
    """True when any project copy is active or dated on/after cutoff.

    Unreleased versions are always recent — they are in-flight release work.
    Released or archived versions need a release/start date within the window;
    undated historical releases are treated as old noise.
    """
    copies = [
        by_project[project][name] for project in PROJECTS if name in by_project.get(project, {})
    ]
    if not copies:
        return False
    for version in copies:
        if version_lifecycle(version) == LIFECYCLE_UNRELEASED:
            return True
        ref_date = version_reference_date(version)
        if ref_date is not None and ref_date >= cutoff:
            return True
    return False


def filter_names_by_recency(
    by_project: dict[str, dict[str, dict[str, Any]]],
    names: set[str],
    *,
    within_days: int = DEFAULT_RECENT_DAYS,
    today: date | None = None,
) -> set[str]:
    today = today or date.today()
    cutoff = today - timedelta(days=within_days)
    return {name for name in names if is_version_recent(by_project, name, cutoff=cutoff)}


def apply_release_doc_dates(
    meta: dict[str, Any],
    release_doc: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Fill empty startDate/releaseDate from the RHDHPLAN release Feature table.

    Explicit values already on meta win. Only non-TBD milestone cells apply.
    """
    if not release_doc or not release_doc.get("milestones"):
        return meta, {}

    milestones = release_doc["milestones"]
    issue_key = release_doc.get("issue_key", "")
    out = dict(meta)
    sources: dict[str, str] = {}

    if not out.get("releaseDate"):
        for milestone in ("ga_announce", "go_no_go"):
            value = milestones.get(milestone)
            if value and value != "TBD":
                out["releaseDate"] = value
                sources["releaseDate"] = f"{issue_key} ({milestone.replace('_', ' ')})"
                break

    if not out.get("startDate"):
        for milestone in ("feature_freeze", "code_freeze"):
            value = milestones.get(milestone)
            if value and value != "TBD":
                out["startDate"] = value
                sources["startDate"] = f"{issue_key} ({milestone.replace('_', ' ')})"
                break

    return out, sources


def recent_filter_meta(
    *,
    within_days: int,
    today: date | None = None,
) -> dict[str, str]:
    today = today or date.today()
    cutoff = today - timedelta(days=within_days)
    return {
        "within_days": str(within_days),
        "cutoff_date": cutoff.isoformat(),
        "as_of": today.isoformat(),
    }


def compute_plan(
    by_project: dict[str, dict[str, dict[str, Any]]],
    *,
    prune: bool = False,
    only_name: str | None = None,
    override_meta: dict[str, Any] | None = None,
    within_days: int = DEFAULT_RECENT_DAYS,
    all_versions: bool = False,
    release_docs: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return ordered create/update/delete operations to align projects."""
    names = collect_names(by_project)
    if only_name is not None:
        names = {only_name}
    elif not all_versions:
        names = filter_names_by_recency(by_project, names, within_days=within_days)

    operations: list[dict[str, Any]] = []
    docs = release_docs or {}

    def _finalize_target(
        meta: dict[str, Any], version_name: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        finalized, sources = apply_release_doc_dates(meta, docs.get(version_name))
        finalized["name"] = version_name
        return finalized, sources

    def _append_fields(operation: dict[str, Any], sources: dict[str, str]) -> dict[str, Any]:
        if sources:
            operation["date_sources"] = sources
        return operation

    for name in sorted(names):
        ref, ref_project = find_canonical(by_project, name)
        if ref is None:
            if only_name is None:
                continue
            target_meta = {
                "name": name,
                "description": "",
                "startDate": "",
                "releaseDate": "",
                "released": False,
                "archived": False,
            }
            if override_meta:
                target_meta.update(override_meta)
            target_meta, date_sources = _finalize_target(target_meta, name)
            ref_project = None
            for project in PROJECTS:
                operations.append(
                    _append_fields(
                        {
                            "action": "create",
                            "project": project,
                            "name": name,
                            "canonical_project": ref_project,
                            "fields": target_meta,
                        },
                        date_sources,
                    )
                )
            continue

        target_meta = version_meta(ref)
        if override_meta:
            target_meta.update(override_meta)
        target_meta, date_sources = _finalize_target(target_meta, name)

        present_projects = [p for p in PROJECTS if name in by_project.get(p, {})]
        if len(present_projects) == 1 and prune:
            lone = present_projects[0]
            operations.append(
                {
                    "action": "delete",
                    "project": lone,
                    "name": name,
                    "version_id": by_project[lone][name]["id"],
                    "reason": "orphan (only one project holds this version)",
                }
            )
            continue

        for project in PROJECTS:
            current = by_project.get(project, {}).get(name)
            if current is None:
                operations.append(
                    _append_fields(
                        {
                            "action": "create",
                            "project": project,
                            "name": name,
                            "canonical_project": ref_project,
                            "fields": target_meta,
                        },
                        date_sources,
                    )
                )
                continue
            current_meta = version_meta(current)
            if current_meta != target_meta:
                operations.append(
                    _append_fields(
                        {
                            "action": "update",
                            "project": project,
                            "name": name,
                            "version_id": current["id"],
                            "canonical_project": ref_project,
                            "from": current_meta,
                            "to": target_meta,
                        },
                        date_sources,
                    )
                )

    return operations


def diff_report(
    by_project: dict[str, dict[str, dict[str, Any]]],
    *,
    names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Summarize drift and per-project lifecycle per version name."""
    rows: list[dict[str, Any]] = []
    selected = names if names is not None else collect_names(by_project)
    for name in sorted(selected):
        ref, ref_project = find_canonical(by_project, name)
        if ref is None:
            continue
        target = version_meta(ref)
        canonical_lifecycle = lifecycle_from_meta(target)
        projects: dict[str, dict[str, Any]] = {}
        in_sync = True
        lifecycle_aligned = True
        for project in PROJECTS:
            view = project_version_view(by_project.get(project, {}).get(name), target)
            projects[project] = view
            if view["sync"] != "ok":
                in_sync = False
            if view["present"] and not view["lifecycle_matches"]:
                lifecycle_aligned = False
        rows.append(
            {
                "name": name,
                "canonical_project": ref_project,
                "canonical_lifecycle": canonical_lifecycle,
                "projects": projects,
                "in_sync": in_sync,
                "lifecycle_aligned": lifecycle_aligned,
            }
        )
    return rows


def status_report(
    by_project: dict[str, dict[str, dict[str, Any]]],
    name: str,
) -> dict[str, Any]:
    """Cross-project lifecycle and sync for one fix version name."""
    ref, ref_project = find_canonical(by_project, name)
    if ref is None:
        return {
            "name": name,
            "found": False,
            "projects": {
                project: {
                    "present": False,
                    "lifecycle": None,
                }
                for project in PROJECTS
            },
        }
    target = version_meta(ref)
    projects = {
        project: project_version_view(by_project.get(project, {}).get(name), target)
        for project in PROJECTS
    }
    return {
        "name": name,
        "found": True,
        "canonical_project": ref_project,
        "canonical_lifecycle": lifecycle_from_meta(target),
        "projects": projects,
        "in_sync": all(view["sync"] == "ok" for view in projects.values()),
        "lifecycle_aligned": all(
            view["lifecycle_matches"] for view in projects.values() if view["present"]
        ),
    }


def count_by_lifecycle(versions: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in LIFECYCLE_VALUES}
    for version in versions.values():
        counts[version_lifecycle(version)] += 1
    return counts


def next_z_stream_follow_up(
    by_project: dict[str, dict[str, dict[str, Any]]],
    current_version: str,
    *,
    next_version: str | None,
    stream_lifecycle: dict[str, Any] | None,
    next_release_feature: dict[str, Any] | None,
    release_feature_summary: str,
) -> dict[str, Any] | None:
    """When closing a z-stream GA, suggest creating the next patch stream artifacts."""
    if next_version is None:
        return None

    stream = stream_lifecycle or {}
    support_continues = stream.get("supported")
    next_fix_versions = status_report(by_project, next_version)
    next_fix_exists = next_fix_versions["found"]
    next_feature_exists = bool(next_release_feature and next_release_feature.get("issue_key"))

    needs_fix_version = not next_fix_exists or not all(
        next_fix_versions["projects"][project]["present"] for project in PROJECTS
    )
    needs_release_feature = not next_feature_exists

    prompt_user = support_continues is True and (needs_fix_version or needs_release_feature)

    suggested_actions: list[dict[str, str]] = []
    if needs_fix_version:
        suggested_actions.append(
            {
                "artifact": "fix_version",
                "command": (
                    f"uv run scripts/fixversions.py ensure {next_version} --json "
                    "(then plan/apply through /mutation-gate)"
                ),
                "reason": "Engineering needs the fix version to assign incoming issues immediately",
            }
        )
    if needs_release_feature:
        suggested_actions.append(
            {
                "artifact": "release_feature",
                "skill": "/rhdh-jira-create",
                "summary": release_feature_summary,
                "project": "RHDHPLAN",
                "issue_type": "Feature",
                "component": "Release",
                "reason": "Release managers track milestones on the RHDHPLAN release Feature",
            }
        )

    prompt_message: str | None = None
    if prompt_user:
        missing = []
        if needs_fix_version:
            missing.append(f"fix version {next_version}")
        if needs_release_feature:
            missing.append(f"release Feature ({release_feature_summary})")
        prompt_message = (
            f"RHDH {stream.get('stream', '')} is still supported. "
            f"Create {' and '.join(missing)} now so engineering can assign issues "
            f"to {next_version} as they come up?"
        )

    return {
        "current_version": current_version,
        "next_version": next_version,
        "stream": stream.get("stream"),
        "stream_support": stream,
        "support_continues": support_continues,
        "next_fix_version": {
            "exists": next_fix_exists,
            "present_everywhere": next_fix_exists
            and all(next_fix_versions["projects"][project]["present"] for project in PROJECTS),
            "status": next_fix_versions,
        },
        "next_release_feature": next_release_feature or {"found": False},
        "needs_fix_version": needs_fix_version,
        "needs_release_feature": needs_release_feature,
        "prompt_user": prompt_user,
        "prompt_message": prompt_message,
        "suggested_actions": suggested_actions,
    }


def close_out_report(
    by_project: dict[str, dict[str, dict[str, Any]]],
    version: str,
    release_feature: dict[str, Any] | None,
    *,
    next_z_stream: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check fix versions are released before closing the RHDHPLAN release Feature."""
    fix_versions = status_report(by_project, version)
    blockers: list[str] = []
    warnings: list[str] = []

    if release_feature is None or not release_feature.get("issue_key"):
        warnings.append("No RHDHPLAN release Feature matched this version")
    elif release_feature.get("is_closed"):
        warnings.append(
            "Release Feature "
            f"{release_feature['issue_key']} is already "
            f"{release_feature.get('status', 'closed')}"
        )

    if not fix_versions["found"]:
        blockers.append("Fix version absent from RHIDP, RHDHPLAN, and RHDHBUGS")
    else:
        for project in PROJECTS:
            view = fix_versions["projects"][project]
            if not view["present"]:
                blockers.append(f"{project}: fix version missing")
            elif view["lifecycle"] != LIFECYCLE_RELEASED:
                blockers.append(
                    f"{project}: fix version is {view['lifecycle']} "
                    "(must be released before closing the release Feature)"
                )
        if not fix_versions["in_sync"]:
            warnings.append("Fix version metadata drifts across projects (run diff)")
        if not fix_versions["lifecycle_aligned"]:
            warnings.append("Fix version lifecycle differs across projects")

    fix_versions_released = fix_versions["found"] and all(
        fix_versions["projects"][project]["present"]
        and fix_versions["projects"][project]["lifecycle"] == LIFECYCLE_RELEASED
        for project in PROJECTS
    )

    suggested: str | None = None
    if not fix_versions_released:
        suggested = (
            f"uv run scripts/fixversions.py ensure {version} --released --json "
            "(add --release-date YYYY-MM-DD when GA date is known; then plan/apply)"
        )

    result: dict[str, Any] = {
        "version": version,
        "release_feature": release_feature or {"found": False},
        "fix_versions": fix_versions,
        "fix_versions_released": fix_versions_released,
        "ready_to_close_release_feature": fix_versions_released,
        "ok": fix_versions_released,
        "blockers": blockers,
        "warnings": warnings,
        "suggested_command": suggested,
    }
    if next_z_stream is not None:
        result["next_z_stream"] = next_z_stream
        if next_z_stream.get("prompt_user"):
            result["prompt_user"] = True
            result["prompt_message"] = next_z_stream.get("prompt_message")
    return result
