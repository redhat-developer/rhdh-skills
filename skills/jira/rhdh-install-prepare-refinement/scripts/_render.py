"""Render refinement briefing markdown."""

from __future__ import annotations

import urllib.parse

from _release import ReleaseContext
from _signals import SignalResult

SECTION_META = {
    "features": ("🚀", "feature_release_planning"),
    "work_readiness": ("🎫", "team"),
    "hygiene": ("🧹", "hygiene"),
    "clear": ("✅", "clear"),
}


def jira_issues_url(base: str, jql: str) -> str:
    return f"{base}/issues/?jql={urllib.parse.quote(jql, safe='')}"


def render_briefing(
    *,
    config: dict,
    release: ReleaseContext,
    queue_total: int,
    queue_jql: str,
    signals: list[SignalResult],
) -> str:
    base = config.get("jira_base", "https://redhat.atlassian.net").rstrip("/")
    team = config.get("team", {}).get("short_name", "Install")
    dashboards = config.get("dashboards", {})

    primary_url = f"{base}/browse/{release.plan_feature_key}"
    secondary_url = f"{base}/browse/{release.secondary_plan_feature_key}"
    queue_url = jira_issues_url(base, queue_jql)
    team_dash = dashboards.get("team", {}).get("url", "")

    lines: list[str] = [
        "# 🎯 RHDH Install · Refinement",
        "",
        f"🚀 **[{release.primary_version}]({primary_url})** · "
        f"[{release.secondary_version} ({release.secondary_ga_label})]({secondary_url})",
    ]

    if release.code_freeze_date and release.days_to_code_freeze is not None:
        day = release.code_freeze_date.day
        freeze_str = f"{day} {release.code_freeze_date.strftime('%b')}"
        lines.append(f"🗓️ **Code freeze:** {freeze_str} · **{release.days_to_code_freeze} days**")

    team_link = f" · [{dashboards.get('team', {}).get('label', 'RHDH Team Dashboard')}]({team_dash})" if team_dash else ""
    lines.append(f"🎫 **[{queue_total} issues]({queue_url})** in refinement{team_link}")
    lines.append("")

    if release.freeze_warning:
        lines.append("🔥 **Freeze approaching**")
        lines.append("")

    by_section: dict[str, list[SignalResult]] = {}
    for sig in signals:
        by_section.setdefault(sig.section, []).append(sig)

    section_order = ["features", "work_readiness", "hygiene", "clear"]
    for section_id in section_order:
        section_signals = by_section.get(section_id, [])
        if not section_signals:
            continue
        if section_id == "clear":
            for sig in section_signals:
                url = jira_issues_url(base, sig.jql)
                lines.append(f"## ✅ [{sig.message}]({url})")
            lines.append("")
            continue

        emoji, dash_key = SECTION_META[section_id]
        heading = _section_heading(section_id, config, team, release, base)
        lines.append(f"## {emoji} {heading}")
        lines.append("")
        for sig in section_signals:
            url = jira_issues_url(base, sig.jql)
            suffix = f" · {sig.suffix}" if sig.suffix else ""
            lines.append(f"{sig.emoji} **[{sig.message}]({url})**{suffix}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _section_heading(section_id: str, config: dict, team: str, release: ReleaseContext, base: str) -> str:
    dashboards = config.get("dashboards", {})
    team_id = config.get("team", {}).get("id", "")

    if section_id == "features":
        candidate = release.candidate_label
        jql = (
            f'labels = {candidate} AND "Team[Team]" = {team_id}'
            if team_id
            else f"labels = {candidate}"
        )
        url = jira_issues_url(base, jql)
        tracking = dashboards.get("feature_tracking", {})
        tracking_bit = f" · [{tracking.get('label', 'Feature Tracking')}]({tracking.get('url', '')})" if tracking.get("url") else ""
        return f"[RHDH Feature Release Planning: {candidate}, {team}]({url}){tracking_bit}"

    if section_id == "work_readiness":
        queue = _queue_jql_from_config(config)
        url = jira_issues_url(base, queue)
        return f"[RHDH Team Dashboard: {team}, refinement queue]({url})"

    if section_id == "hygiene":
        dash = dashboards.get("hygiene", {})
        url = dash.get("url", base)
        return f"[RHDH Hygiene: {team}, active release window]({url})"

    return section_id


def _queue_jql_from_config(config: dict) -> str:
    from _jql import build_queue_jql

    return build_queue_jql(config)
