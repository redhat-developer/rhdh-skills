"""Compare two overlay snapshots for support, lifecycle, added, and removed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from support import as_str, md_cell

KeyFn = Callable[[dict[str, Any]], str]
Predicate = Callable[[dict[str, Any]], bool]


@dataclass
class DiffReport:
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0
    warnings: list[str] = field(default_factory=list)

    def support_changes(self) -> list[dict[str, Any]]:
        return [row for row in self.changed if "support" in row["changes"]]

    def lifecycle_changes(self) -> list[dict[str, Any]]:
        return [row for row in self.changed if "lifecycle" in row["changes"]]


def package_key(pkg: dict[str, Any]) -> str:
    name = as_str(pkg.get("package_name"))
    if name:
        return name.lower()
    workspace = as_str(pkg.get("workspace"))
    filename = Path(as_str(pkg.get("file"))).name
    return f"{workspace}/{filename}".lower()


def plugin_key(plugin: dict[str, Any]) -> str:
    name = as_str(plugin.get("name"))
    if name:
        return name.lower()
    return Path(as_str(plugin.get("file"))).name.lower()


def _index(items: list[dict[str, Any]], key_fn: KeyFn) -> tuple[dict[str, dict[str, Any]], list[str]]:
    index: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for item in items:
        key = key_fn(item)
        if not key:
            warnings.append(
                f"Skipping row with empty identity ({item.get('file') or item.get('title')})."
            )
            continue
        if key in index:
            warnings.append(
                f"Duplicate identity {key!r}: keeping {index[key].get('file')}, "
                f"ignoring {item.get('file')}."
            )
            continue
        index[key] = item
    return index, warnings


def _lifecycle_value(item: dict[str, Any]) -> str:
    return as_str(item.get("lifecycle")).lower()


def _changes_between(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    if as_str(old.get("support")) != as_str(new.get("support")):
        changes.append("support")
    if _lifecycle_value(old) != _lifecycle_value(new):
        changes.append("lifecycle")
    return changes


def _title_sort(item: dict[str, Any]) -> tuple[str, str]:
    return (
        as_str(item.get("title")).lower(),
        as_str(item.get("name") or item.get("package_name") or item.get("file")).lower(),
    )


def diff_items(
    from_items: list[dict[str, Any]],
    to_items: list[dict[str, Any]],
    key_fn: KeyFn,
) -> DiffReport:
    from_idx, from_warn = _index(from_items, key_fn)
    to_idx, to_warn = _index(to_items, key_fn)
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    unchanged = 0
    for key, new in to_idx.items():
        old = from_idx.get(key)
        if old is None:
            added.append(new)
            continue
        changes = _changes_between(old, new)
        if changes:
            changed.append({"key": key, "from": old, "to": new, "changes": changes})
        else:
            unchanged += 1
    for key, old in from_idx.items():
        if key not in to_idx:
            removed.append(old)
    added.sort(key=_title_sort)
    removed.sort(key=_title_sort)
    changed.sort(key=lambda row: _title_sort(row["to"]))
    return DiffReport(
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        warnings=from_warn + to_warn,
    )


def restrict_to_matching_identities(
    from_items: list[dict[str, Any]],
    to_items: list[dict[str, Any]],
    key_fn: KeyFn,
    predicate: Predicate,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep identities that match on either version (so promotions are not dropped)."""
    from_idx, _ = _index(from_items, key_fn)
    to_idx, _ = _index(to_items, key_fn)
    keep: set[str] = set()
    for key in set(from_idx) | set(to_idx):
        old = from_idx.get(key)
        new = to_idx.get(key)
        if (old is not None and predicate(old)) or (new is not None and predicate(new)):
            keep.add(key)
    return (
        [item for item in from_items if key_fn(item) in keep],
        [item for item in to_items if key_fn(item) in keep],
    )


def arrow(old: str, new: str) -> str:
    left = md_cell(old)
    right = md_cell(new)
    if left == right:
        return left
    return f"{left} → **{right}**"
