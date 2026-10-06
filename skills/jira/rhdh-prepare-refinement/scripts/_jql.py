"""JQL builder for a team's refinement queue."""

from __future__ import annotations


def build_queue_jql(
    *,
    team_id: str,
    project: str = "RHIDP",
    fix_versions: tuple[str, ...] | None = None,
) -> str:
    parts = [f"project = {project}"]
    parts.append("sprint in openSprints()")
    parts.append(f'"Team[Team]" = {team_id}')
    parts.append('status in (New, Refinement, "To Do")')
    if fix_versions:
        quoted = ", ".join(f'"{v}"' for v in fix_versions)
        parts.append(f"fixVersion in ({quoted})")
    return " AND ".join(parts)
