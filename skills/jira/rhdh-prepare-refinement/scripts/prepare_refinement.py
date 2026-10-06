#!/usr/bin/env python3
"""RHDH refinement briefing — works for any scrum team.

Usage:
    ./scripts/prepare-refinement --team Install --fix-version 2.1.0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RHDH team refinement briefing")
    parser.add_argument("--team", required=True, help="Team name (Install, Plugins, Frontend, AI, COPE, Documentation)")
    parser.add_argument("--fix-version", required=True, help="fixVersion (e.g. 2.1.0)")
    parser.add_argument("--today", help="Override date YYYY-MM-DD (tests)")
    parser.add_argument("--facts-out", type=Path, help="Write facts JSON to file")
    parser.add_argument("--format", choices=("refinement", "markdown", "plain"), default=None)
    args = parser.parse_args(argv)

    from _auth import resolve_jira_auth
    from _issues import normalize
    from _jira_client import search_jql, child_count
    from _jql import build_queue_jql
    from _release import resolve
    from _signals import evaluate, build_facts
    from _team import resolve_team, JIRA_BASE

    today = date.fromisoformat(args.today) if args.today else None
    version = args.fix_version.strip()
    team = resolve_team(args.team)

    release = resolve(version, today=today)
    jql = build_queue_jql(team_id=team["team_id"], fix_versions=(version,))
    auth = resolve_jira_auth()
    raw = search_jql(auth, jql)
    issues = [normalize(r) for r in raw]

    for issue in issues:
        if issue["issuetype"] == "Epic" and child_count(auth, issue["key"]) == 0:
            issue["no_children"] = True

    signals = evaluate(issues, queue_jql=jql, release=release)
    facts = build_facts(issues, signals, release, jql)
    output = render(release, signals, facts, team, fmt=args.format)
    print(output, end="")

    if args.facts_out:
        args.facts_out.parent.mkdir(parents=True, exist_ok=True)
        args.facts_out.write_text(json.dumps(facts, indent=2) + "\n")

    return 0


# ── Render ───────────────────────────────────────────────────────────────

def render(release, signals, facts, team, *, fmt: str | None = None) -> str:
    style = fmt or ("refinement" if sys.stdout.isatty() else "plain")
    base = "https://redhat.atlassian.net"
    dashboards = team["dashboards"]
    overlaps = {o["key"]: o["signals"] for o in facts["overlaps"]}
    by_name = {s.name: s for s in signals}
    v = release.version
    name = team["team_name"]

    lines = [f"🎯 RHDH {name} · Refinement", "", f"Release: {v}"]

    if release.code_freeze or release.feature_freeze:
        lines.append(_freeze_line(release))

    lines.extend(["", "✨ Summary", _summary(release, by_name, overlaps), ""])

    sections = [
        ("🚀 Feature Tracking", "feature_tracking", _feature_bullets(release, by_name, base, style)),
        ("🎫 Team Dashboard", "team_refinement", _team_bullets(by_name, overlaps, base, style)),
        ("🧹 Hygiene", "hygiene", _hygiene_bullets(by_name, overlaps, base, style)),
    ]
    for title, key, bullets in sections:
        dash = dashboards[key]
        lines.append(f"{title} (Dashboard)")
        lines.append(f"   {v} · {name}")
        lines.append(f"   {_link(dash['label'], dash['url'], style)}")
        if bullets:
            lines.append("")
            for b in bullets:
                lines.append(f"   ✨ {b}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _freeze_line(r) -> str:
    if r.phase == "feature_freeze" and r.feature_freeze:
        d, days = r.feature_freeze, (r.feature_freeze - r.today).days
        label = "Feature freeze"
    elif r.code_freeze:
        d, days = r.code_freeze, r.days_to_code_freeze
        label = "Code freeze"
    else:
        d, days = r.feature_freeze, (r.feature_freeze - r.today).days
        label = "Feature freeze"
    fire = " 🔥" if r.freeze_warning else ""
    return f"{label}: {d.day} {d.strftime('%b')} · {days} days{fire}"


def _summary(release, by_name, overlaps) -> str:
    parts = []
    if release.freeze_warning and release.phase_label:
        parts.append(f"{release.version} needs the most attention in the {release.phase_label} window.")
    elif release.freeze_warning:
        parts.append(f"{release.version} needs the most attention approaching freeze.")
    else:
        parts.append(f"{release.version} is the focus for this refinement pass.")

    details = []
    if "epic_no_children" in by_name:
        n = len(by_name["epic_no_children"].keys)
        details.append(f"{'One' if n == 1 else n} Epic{'s' if n > 1 else ''} still {'have' if n > 1 else 'has'} no breakdown")
    if "unassigned" in by_name:
        n = len(by_name["unassigned"].keys)
        details.append(f"{'several' if n > 1 else 'one'} refinement items are still unowned")
    if overlaps:
        n = len(overlaps)
        details.append(f"{n} item{'s' if n != 1 else ''} appear{'s' if n == 1 else ''} across multiple checks")
    if details:
        parts.append(", ".join(details) + ".")
    return "\n".join(parts)


def _feature_bullets(release, by_name, base, style) -> list[str]:
    bullets = []
    sig = by_name.get("epic_no_children")
    if sig:
        for key in sig.keys:
            tail = ""
            if release.freeze_warning and release.days_to_code_freeze is not None:
                tail = f" with {release.days_to_code_freeze} days until freeze"
            bullets.append(
                f"{_issue(key, base, style)} stands out for {release.version}"
                f" — Epic has no breakdown and no owner{tail}"
            )
    return bullets[:3]


def _team_bullets(by_name, overlaps, base, style) -> list[str]:
    bullets = []
    sig = by_name.get("unassigned")
    if sig:
        jql_url = _jql_url(base, sig.jql)
        bullets.append(f"{len(sig.keys)} refinement issues have no owner. {_link('View issues', jql_url, style)}")
    cross = [k for k, sigs in overlaps.items() if "unsized" in sigs and "no_priority" in sigs]
    if cross:
        key = sorted(cross)[0]
        bullets.append(f"{_issue(key, base, style)} needs the most discussion — unsized and flagged in hygiene below")
    return bullets[:3]


def _hygiene_bullets(by_name, overlaps, base, style) -> list[str]:
    bullets = []
    sig = by_name.get("no_priority")
    if sig:
        jql_url = _jql_url(base, sig.jql)
        bullets.append(f"{len(sig.keys)} issues have missing Jira fields. {_link('View issues', jql_url, style)}")
    return bullets[:3]


# ── Link helpers ─────────────────────────────────────────────────────────

_OSC8_ST = "\033\\"
_OSC8_END = f"\033]8;;{_OSC8_ST}"
_SGR_RESET = "\033[0m"


def _osc8(label: str, url: str) -> str:
    return f"\033]8;;{url}{_OSC8_ST}{label}{_OSC8_END}{_SGR_RESET}"


def _link(label: str, url: str, style: str) -> str:
    if style == "markdown":
        return f"[{label}]({url})"
    if style == "plain":
        return label
    inner = _osc8(label, url) if not os.environ.get("NO_COLOR") else label
    return f"(Link: {inner})"


def _issue(key: str, base: str, style: str) -> str:
    url = f"{base}/browse/{key}"
    if style == "markdown":
        return f"[{key}]({url})"
    if style == "plain":
        return key
    return _osc8(key, url) if not os.environ.get("NO_COLOR") else key


def _jql_url(base: str, jql: str) -> str:
    return f"{base}/issues/?jql={urllib.parse.quote(jql, safe='')}"


if __name__ == "__main__":
    raise SystemExit(main())
