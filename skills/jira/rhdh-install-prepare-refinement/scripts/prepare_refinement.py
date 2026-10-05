#!/usr/bin/env python3
"""Deterministic RHDH Install refinement briefing (zero-token)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or SKILL_ROOT / "references" / "config.json"
    with cfg_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_fixture(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict) and "issues" in data:
        return data["issues"]
    if isinstance(data, list):
        return data
    raise SystemExit(f"Unexpected fixture shape in {path}")


def discover_epics_without_children(auth, issues: list[dict]) -> list[str]:
    from _issues import normalize
    from _jira_client import child_count

    missing: list[str] = []
    for raw in issues:
        row = normalize(raw)
        if row["issuetype"] != "Epic":
            continue
        if child_count(auth, row["key"]) == 0:
            missing.append(row["key"])
    return missing


def run_live(config: dict, calendar_path: Path) -> tuple[list[dict], list[str]]:
    from _auth import resolve_jira_auth
    from _issues import normalize
    from _jira_client import search_jql
    from _jql import build_queue_jql

    auth = resolve_jira_auth()
    jql = build_queue_jql(config)
    raw = search_jql(auth, jql)
    issues = [normalize(r) for r in raw]
    epic_gaps = discover_epics_without_children(auth, raw)
    return issues, epic_gaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RHDH Install refinement briefing")
    parser.add_argument("--config", type=Path, help="Path to config.yaml")
    parser.add_argument("--fixture", type=Path, help="JSON issues for offline run (no Jira)")
    parser.add_argument("--facts", choices=["-", "stdout"], help="Also print facts JSON to stderr (-) or stdout")
    parser.add_argument(
        "--facts-out",
        type=Path,
        default=None,
        help="Facts JSON path (default: skill facts/refinement-latest.json)",
    )
    parser.add_argument("--no-facts", action="store_true", help="Skip writing facts JSON")
    parser.add_argument("--today", type=str, help="Override date YYYY-MM-DD for tests")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    calendar_path = SKILL_ROOT / "assets" / "release_calendar.json"

    from _issues import normalize_fixture
    from _release import build_release_context
    from _jql import build_queue_jql
    from _signals import build_facts, evaluate_signals
    from _render import render_briefing

    today = date.fromisoformat(args.today) if args.today else None
    release = build_release_context(config, calendar_path, today=today)
    queue_jql = build_queue_jql(config)

    epic_without_children: list[str] = []
    if args.fixture:
        issues = normalize_fixture(load_fixture(args.fixture))
        epic_without_children = [i["key"] for i in issues if i.get("issuetype") == "Epic" and i.get("no_children")]
    else:
        issues, epic_without_children = run_live(config, calendar_path)

    team_id = config.get("team", {}).get("id", "")
    signals = evaluate_signals(
        issues,
        epic_without_children=epic_without_children,
        release=release,
        team_id=team_id,
        queue_jql=queue_jql,
    )
    facts = build_facts(issues, signals, release, queue_jql)
    markdown = render_briefing(
        config=config,
        release=release,
        queue_total=len(issues),
        queue_jql=queue_jql,
        signals=signals,
    )

    print(markdown, end="")

    facts_path = None
    if not args.no_facts:
        facts_path = args.facts_out or (SKILL_ROOT / "facts" / "refinement-latest.json")
    if facts_path:
        facts_path.parent.mkdir(parents=True, exist_ok=True)
        facts_path.write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
        print(f"prepare_refinement: facts → {facts_path}", file=sys.stderr)

    if args.facts in ("-", "stdout"):
        payload = json.dumps(facts, indent=2) + "\n"
        print(payload, file=sys.stderr if args.facts == "-" else sys.stdout)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
