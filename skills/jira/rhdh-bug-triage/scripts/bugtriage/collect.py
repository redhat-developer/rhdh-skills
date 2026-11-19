"""Build one evidence file per sampled ticket.

The output is input for the adjudication step: ticket facts, linked keys, PR
state, and search phrases. It contains no credential and performs no write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .discovery import discover
from .forge import collect_for_ticket, load_cache
from .model import load_export
from .report import now_iso, write_json
from .run import RunError, load_sample_manifest


@dataclass
class CollectConfig:
    input_path: str
    sample_path: str
    output_dir: str
    forge_cache: str = ""
    use_gh: bool = False
    repos: Optional[List[str]] = None
    backlog_path: str = ""
    jira_search: bool = False
    max_queries: int = 4
    query_limit: int = 20
    hydrate_limit: int = 10
    field_names: Optional[dict] = None


def collect(config: CollectConfig) -> Dict[str, str]:
    tickets = {ticket.key: ticket for ticket in load_export(config.input_path)}
    sample = load_sample_manifest(config.sample_path)
    cache = load_cache(config.forge_cache)
    backlog = load_export(config.backlog_path or config.input_path)
    output = Path(config.output_dir)
    if output.exists():
        raise RunError("evidence directory already exists; use a fresh directory")
    missing = [entry["key"] for entry in sample.get("tickets", []) if entry["key"] not in tickets]
    if missing:
        raise RunError("sample keys absent from export: " + ", ".join(missing))
    output.mkdir(parents=True, exist_ok=False)
    written: Dict[str, str] = {}
    for entry in sample.get("tickets", []):
        key = entry["key"]
        ticket = tickets.get(key)
        if ticket is None:
            raise RunError(f"sample names {key}, which is absent from the export")
        evidence = collect_for_ticket(ticket, cache, config.use_gh, repos=config.repos)
        evidence["kind"] = entry.get("kind", "aged")
        evidence["stratum"] = entry.get("stratum", "")
        evidence["commentsComplete"] = ticket.comments_complete
        evidence["created"] = ticket.created
        evidence["issueUpdated"] = ticket.updated
        evidence["collectedAt"] = now_iso()
        evidence["discovery"] = discover(
            ticket,
            backlog,
            live=config.jira_search,
            max_queries=config.max_queries,
            query_limit=config.query_limit,
            hydrate_limit=config.hydrate_limit,
            field_names=config.field_names,
        )
        if entry.get("controlLabel"):
            evidence["controlLabel"] = entry["controlLabel"]
        path = output / f"{key}.json"
        write_json(path, evidence)
        written[key] = str(path)
    write_json(
        output / "index.json",
        {
            "schemaVersion": 1,
            "generatedAt": now_iso(),
            "dryRun": True,
            "forge": "gh" if config.use_gh else "cache-only",
            "backlog": config.backlog_path or config.input_path,
            "jiraSearch": config.jira_search,
            "tickets": [{"key": key, "path": path} for key, path in sorted(written.items())],
        },
    )
    return written
