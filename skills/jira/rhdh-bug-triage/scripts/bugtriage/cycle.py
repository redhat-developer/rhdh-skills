"""Resume one five-issue slice of a frozen inventory in a run directory."""

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from .jira import export_from_acli, search_acli
from .model import DEFAULT_SAMPLE_SIZE, normalize_export
from .report import now_iso
from .review_queue import batch_counts
from .run import RunError, build_sample_manifest, default_jql, parse_as_of
from .selection import SelectionConfig


def _publish(path, data):
    """Publish complete bytes once, including when two invocations race."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as temporary:
        staged = Path(temporary) / "new"
        staged.touch(mode=0o600)
        staged.write_bytes(data)
        try:
            os.link(staged, path)
        except FileExistsError:
            pass
    return path.read_bytes()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _binding(review, inventory_hash, packet_bytes):
    return {
        "inventoryHash": inventory_hash,
        "packetHash": _digest(packet_bytes),
        "review": review.name,
    }


def adopted_review(review, inventory_hash, packet_bytes):
    receipt = review.parent / "private" / "adopted-first-review.json"
    return (
        review.name in {"review", "review-1"}
        and receipt.is_file()
        and json.loads(receipt.read_bytes()) == _binding(review, inventory_hash, packet_bytes)
    )


def _finished(review, keys, inventory_hash, can_adopt):
    audit = review / "01-triage/audit"
    if not (review / "run.json").is_file():
        return False
    if not (audit / "packets.json").is_file() or not (audit / "selection.json").is_file():
        return False
    packet_bytes = (audit / "packets.json").read_bytes()
    packets = json.loads(packet_bytes)
    selection = json.loads((audit / "selection.json").read_bytes())
    selected = [entry["key"] for entry in selection["tickets"]]
    accounted = selected + [entry["key"] for entry in selection["excluded"]]
    if sorted(accounted) != sorted(keys) or sorted(selected) != sorted(
        packet["key"] for packet in packets["packets"]
    ):
        raise RunError(f"{review} does not account for the exact inventory slice")
    source_hash = packets["meta"]["coverage"].get("inventoryHash")
    if source_hash != inventory_hash and not adopted_review(review, inventory_hash, packet_bytes):
        if (
            source_hash
            or not can_adopt
            or review.name not in {"review", "review-1"}
            or selection.get("scope") != "all-open"
        ):
            raise RunError(f"{review} belongs to a different or unverified inventory")
        receipt = review.parent / "private/adopted-first-review.json"
        binding = _binding(review, inventory_hash, packet_bytes)
        if json.loads(_publish(receipt, json.dumps(binding).encode())) != binding:
            raise RunError("first review already bound to another inventory or packet")
    cases = json.loads((review / "run.json").read_bytes()).get("cases")
    if cases is None or set(cases) != set(selected):
        return False
    for key, case in cases.items():
        if not (
            case.get("stage") and case.get("evidence") and (review / case["evidence"]).is_file()
        ):
            return False
        if case.get("proposedComment"):
            draft = review / "01-triage/comments" / f"{key}.md"
            if (
                not draft.is_file()
                or draft.read_text().rstrip() != case["proposedComment"].rstrip()
            ):
                return False
    return True


def render_cycle_index(review):
    """Render completed inventory slices for a cycle-managed finish."""
    root = review.parent
    inventory = root / "private/bugs.json"
    if not inventory.is_file() or not re.fullmatch(r"review(?:-[1-9]\d*)?", review.name):
        return None
    packet_bytes = (review / "01-triage/audit/packets.json").read_bytes()
    coverage = json.loads(packet_bytes).get("meta", {}).get("coverage", {})
    data = inventory.read_bytes()
    digest = _digest(data)
    if not coverage.get("inventoryHash") and not adopted_review(review, digest, packet_bytes):
        return None

    keys = json.loads(data)["keys"]
    first = root / "review" if (root / "review").exists() else root / "review-1"
    sections = []
    accounted = reviewed = 0
    for start in range(0, len(keys), DEFAULT_SAMPLE_SIZE):
        number = start // DEFAULT_SAMPLE_SIZE + 1
        directory = first if number == 1 else root / f"review-{number}"
        batch = keys[start : start + DEFAULT_SAMPLE_SIZE]
        if not _finished(directory, batch, digest, False):
            break
        cases = json.loads((directory / "run.json").read_bytes())["cases"]
        lines = [f"## [Batch {number}]({directory.name}/START-HERE.md)", ""]
        audit = f"{directory.name}/01-triage/audit"
        excluded = json.loads((directory / "01-triage/audit/selection.json").read_bytes())[
            "excluded"
        ]
        lines.extend([batch_counts(len(cases), excluded), ""])
        for key in batch:
            if key in cases:
                case = cases[key]
                finding = case.get("resolution") or case["finding"]
                lines.append(f"- [{key}]({audit}/bugs/{key}.md) — {finding}")
                for message in case.get("jiraFieldSummary", []):
                    lines.append(f"  - {message}")
            else:
                lines.append(f"- {key} — excluded. [Selection record]({audit}/selection.json)")
        sections.append("\n".join(lines))
        reviewed += len(cases)
        accounted += len(batch)
    intro = (
        f"**{reviewed} issues reviewed across {len(sections)} completed batches.** "
        f"{accounted - reviewed} excluded. {len(keys) - accounted} of {len(keys)} "
        "inventory entries remain."
    )
    return "\n\n".join(["# RHDH bug triage", intro, *reversed(sections)]) + "\n"


def resume(root, release, source=None, field_names=None):
    root = Path(root)
    private = root / "private"
    inventory_file = private / "bugs.json"
    first = root / "review"
    alternate = root / "review-1"
    if alternate.exists():
        if first.exists():
            raise RunError("two first-batch reviews exist; cannot choose the cycle history")
        first = alternate
    if source:
        data = Path(source).read_bytes()
    elif inventory_file.exists():
        data = inventory_file.read_bytes()
    else:
        if first.exists():
            raise RunError("supply the original --inventory when adopting an existing review")
        jql = default_jql(90, "all-open")
        data = json.dumps(
            {
                "project": "RHDHBUGS",
                "keys": [row["key"] for row in search_acli(jql, fields="key,status")],
                "jql": jql,
                "observedAt": now_iso(),
            },
            indent=2,
        ).encode()
    inventory = json.loads(data)
    keys = inventory.get("keys")
    if (
        inventory.get("project") != "RHDHBUGS"
        or not inventory.get("observedAt")
        or not isinstance(keys, list)
        or not all(isinstance(k, str) and re.fullmatch(r"RHDHBUGS-\d+", k) for k in keys)
        or len(set(keys)) != len(keys)
    ):
        raise RunError("expected a frozen inventory of unique RHDHBUGS keys")
    if not inventory_file.exists() and first.exists():
        _finished(first, keys[:DEFAULT_SAMPLE_SIZE], _digest(data), bool(source))
    stored = _publish(inventory_file, data)
    if stored != data:
        if source:
            raise RunError("run directory already has a different inventory")
        return resume(root, release, field_names=field_names)
    digest = _digest(data)
    for start in range(0, len(keys), DEFAULT_SAMPLE_SIZE):
        number = start // DEFAULT_SAMPLE_SIZE + 1
        batch = keys[start : start + DEFAULT_SAMPLE_SIZE]
        review = first if number == 1 else root / f"review-{number}"
        if _finished(review, batch, digest, bool(source)):
            continue
        inputs = private / f"batch-{number}"
        export = inputs / "export.json"
        sample = inputs / "sample.json"
        jql = "key IN (" + ", ".join(batch) + ") ORDER BY key ASC"
        prepared = export.exists()
        if not prepared:
            document = export_from_acli(jql, field_names=field_names)
            if sorted(issue["key"] for issue in document["issues"]) != sorted(batch):
                raise RunError("Jira did not return every key in the batch")
            document["provenance"].update(
                inventoryHash=digest,
                batch=number,
                inventorySize=len(keys),
                inventoryObservedAt=inventory["observedAt"],
            )
            _publish(export, json.dumps(document, indent=2).encode())
        document = json.loads(export.read_bytes())
        if document["provenance"].get("inventoryHash") != digest or sorted(
            issue["key"] for issue in document["issues"]
        ) != sorted(batch):
            raise RunError("saved batch export differs from the inventory")
        if not sample.exists():
            manifest = build_sample_manifest(
                normalize_export(document),
                SelectionConfig(scope="all-open", current_release=release, all_tickets=True),
                parse_as_of(None),
                jql,
            )
            _publish(sample, json.dumps(manifest, indent=2).encode())
        manifest = json.loads(sample.read_bytes())
        if manifest["currentRelease"] != release:
            raise RunError(
                f"resume this batch using its recorded release {manifest['currentRelease']}"
            )
        return {
            "state": "resume" if prepared or review.exists() else "ready",
            "batch": number,
            "keys": batch,
            "export": str(export),
            "sample": str(sample),
            "asOf": manifest["asOf"],
            "review": str(review),
        }
    return {"state": "complete", "accounted": len(keys)}
