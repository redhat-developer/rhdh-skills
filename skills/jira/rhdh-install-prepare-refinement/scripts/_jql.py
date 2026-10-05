"""JQL builders for Install refinement queue."""

from __future__ import annotations


def build_queue_jql(config: dict) -> str:
    team_id = config.get("team", {}).get("id", "")
    project = config.get("queue", {}).get("project", "RHIDP")
    statuses = config.get("queue", {}).get("statuses", ["New", "To Do"])
    status_clause = ", ".join(f'"{s}"' if " " in s else s for s in statuses)
    parts = [f"project = {project}"]
    if config.get("queue", {}).get("use_open_sprint"):
        parts.append("sprint in openSprints()")
    if team_id:
        parts.append(f'"Team[Team]" = {team_id}')
    parts.append(f"status in ({status_clause})")
    return " AND ".join(parts)
