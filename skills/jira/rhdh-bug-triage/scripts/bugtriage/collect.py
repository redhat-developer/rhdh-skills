"""Build one evidence file per sampled ticket.

The output is input for the adjudication step: ticket facts, linked keys, PR
state, and search phrases. It contains no credential and performs no write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

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


def collect(config: CollectConfig) -> Dict[str, str]:
    tickets = {ticket.key: ticket for ticket in load_export(config.input_path)}
    sample = load_sample_manifest(config.sample_path)
    cache = load_cache(config.forge_cache)
    output = Path(config.output_dir)
    written: Dict[str, str] = {}
    for entry in sample.get("tickets", []):
        key = entry["key"]
        ticket = tickets.get(key)
        if ticket is None:
            raise RunError(f"sample names {key}, which is absent from the export")
        evidence = collect_for_ticket(ticket, cache, config.use_gh)
        evidence["kind"] = entry.get("kind", "aged")
        evidence["stratum"] = entry.get("stratum", "")
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
            "tickets": [{"key": key, "path": path} for key, path in sorted(written.items())],
        },
    )
    return written
