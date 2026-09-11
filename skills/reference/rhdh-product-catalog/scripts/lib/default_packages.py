"""Core RHDH package list from overlay default.packages.yaml.

See https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/default.packages.yaml
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support import SUPPORT_LABELS, as_str, normalize_support

DEFAULT_PACKAGES_REL = "default.packages.yaml"
DEFAULT_PACKAGES_URL = (
    "https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/default.packages.yaml"
)

OOTB_ENABLED = "enabled"
OOTB_DISABLED = "disabled"
OOTB_MIXED = "mixed"

_CORE_LINE = re.compile(r"^-\s*package:\s*(.+)$")
_SUPPORT_LINE = re.compile(r"^support:\s*(.+)$")
_PLUGIN_PACKAGES_BLOCK = re.compile(
    r"^\s{2}packages:\s*\n((?:^\s*-\s*.+\n?)+)",
    re.MULTILINE,
)
_PLUGIN_PACKAGE_ITEM = re.compile(r"^\s*-\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class CoreEntry:
    package: str
    ootb: str
    support: str
    support_label: str


class CoreIndex:
    """Lookup npm package names listed in default.packages.yaml."""

    def __init__(self, entries: dict[str, CoreEntry]) -> None:
        self._entries = entries

    @classmethod
    def parse(cls, text: str) -> CoreIndex:
        return cls(_parse_default_packages(text))

    def get(self, package_name: str) -> CoreEntry | None:
        return self._entries.get(package_name)

    def __len__(self) -> int:
        return len(self._entries)

    def counts(self) -> dict[str, int]:
        enabled = sum(1 for e in self._entries.values() if e.ootb == OOTB_ENABLED)
        disabled = sum(1 for e in self._entries.values() if e.ootb == OOTB_DISABLED)
        return {"enabled": enabled, "disabled": disabled, "total": len(self._entries)}


def _parse_default_packages(text: str) -> dict[str, CoreEntry]:
    state: str | None = None
    entries: dict[str, CoreEntry] = {}
    pending_name: str | None = None
    pending_support: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "enabled:" or stripped.startswith("enabled:"):
            if pending_name and state:
                _commit_entry(entries, pending_name, state, pending_support)
                pending_name = None
                pending_support = None
            state = OOTB_ENABLED
            continue
        if stripped == "disabled:" or stripped.startswith("disabled:"):
            if pending_name and state:
                _commit_entry(entries, pending_name, state, pending_support)
                pending_name = None
                pending_support = None
            state = OOTB_DISABLED
            continue
        if not state:
            continue
        m = _CORE_LINE.match(stripped)
        if m:
            if pending_name:
                _commit_entry(entries, pending_name, state, pending_support)
            pending_name = m.group(1).strip().strip("'\"").strip()
            pending_support = None
            continue
        m = _SUPPORT_LINE.match(stripped)
        if m and pending_name:
            pending_support = m.group(1).strip().strip("'\"").strip()

    if pending_name:
        _commit_entry(entries, pending_name, state, pending_support)
    return entries


def _commit_entry(
    entries: dict[str, CoreEntry],
    package: str,
    ootb: str,
    support_raw: str | None,
) -> None:
    support = normalize_support(support_raw)
    entries[package] = CoreEntry(
        package=package,
        ootb=ootb,
        support=support,
        support_label=SUPPORT_LABELS[support],
    )


def load_core_index_from_text(text: str) -> CoreIndex:
    return CoreIndex.parse(text)


def load_core_index_from_path(path: Path) -> CoreIndex | None:
    if not path.is_file():
        return None
    return CoreIndex.parse(path.read_text(encoding="utf-8"))


def core_ootb_label(ootb: str) -> str:
    if ootb == OOTB_ENABLED:
        return "enabled OOTB"
    if ootb == OOTB_DISABLED:
        return "disabled OOTB"
    if ootb == OOTB_MIXED:
        return "mixed OOTB"
    return ""


def apply_core_to_package(pkg: dict[str, Any], core: CoreIndex | None) -> None:
    entry = core.get(pkg["package_name"]) if core else None
    pkg["core"] = entry is not None
    pkg["core_ootb"] = entry.ootb if entry else ""
    pkg["core_ootb_label"] = core_ootb_label(pkg["core_ootb"])
    pkg["core_support"] = entry.support if entry else ""
    pkg["core_support_label"] = entry.support_label if entry else ""


def build_metadata_name_index(packages: list[dict[str, Any]]) -> dict[str, str]:
    """Map Package metadata.name (plugin short refs) to npm packageName."""
    index: dict[str, str] = {}
    for pkg in packages:
        name = as_str(pkg.get("name"))
        npm = as_str(pkg.get("package_name"))
        if name and npm:
            index[name] = npm
    return index


def plugin_package_refs(doc: dict[str, Any], text: str) -> list[str]:
    spec = doc.get("spec") or {}
    raw = spec.get("packages") if isinstance(spec, dict) else None
    if isinstance(raw, list):
        refs = [as_str(item) for item in raw if as_str(item)]
        if refs:
            return refs
    match = _PLUGIN_PACKAGES_BLOCK.search(text)
    if not match:
        return []
    block = match.group(1)
    return [m.group(1).strip().strip("'\"") for m in _PLUGIN_PACKAGE_ITEM.finditer(block)]


def resolve_plugin_npm_packages(
    refs: list[str],
    metadata_index: dict[str, str],
    packages_by_npm: dict[str, dict[str, Any]],
    plugin_name: str,
) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        npm = metadata_index.get(ref)
        if not npm and ref in packages_by_npm:
            npm = ref
        if npm and npm not in seen:
            seen.add(npm)
            resolved.append(npm)
    if resolved:
        return resolved
    # Fallback: packages in a workspace matching the plugin catalog name.
    for pkg in packages_by_npm.values():
        if pkg.get("workspace") == plugin_name:
            npm = pkg.get("package_name", "")
            if npm and npm not in seen:
                seen.add(npm)
                resolved.append(npm)
    return resolved


def summarize_core_ootb(npm_names: list[str], core: CoreIndex | None) -> tuple[bool, str]:
    if not core or not npm_names:
        return False, ""
    hits = [core.get(name) for name in npm_names]
    hits = [h for h in hits if h is not None]
    if not hits:
        return False, ""
    states = {h.ootb for h in hits}
    if states == {OOTB_ENABLED}:
        return True, OOTB_ENABLED
    if states == {OOTB_DISABLED}:
        return True, OOTB_DISABLED
    return True, OOTB_MIXED


def apply_core_to_plugin(
    plugin: dict[str, Any],
    *,
    core: CoreIndex | None,
    metadata_index: dict[str, str],
    packages_by_npm: dict[str, dict[str, Any]],
) -> None:
    refs = list(plugin.get("package_refs") or [])
    npm_names = resolve_plugin_npm_packages(
        refs,
        metadata_index,
        packages_by_npm,
        plugin.get("name", ""),
    )
    is_core, ootb = summarize_core_ootb(npm_names, core)
    plugin["npm_packages"] = npm_names
    plugin["core"] = is_core
    plugin["core_ootb"] = ootb if is_core else ""
    plugin["core_ootb_label"] = core_ootb_label(ootb) if is_core else ""


def enrich_packages_with_core(
    packages: list[dict[str, Any]], core: CoreIndex | None
) -> None:
    for pkg in packages:
        apply_core_to_package(pkg, core)


def enrich_plugins_with_core(
    plugins: list[dict[str, Any]],
    *,
    core: CoreIndex | None,
    packages: list[dict[str, Any]],
) -> None:
    metadata_index = build_metadata_name_index(packages)
    packages_by_npm = {p["package_name"]: p for p in packages if p.get("package_name")}
    for plugin in plugins:
        apply_core_to_plugin(
            plugin,
            core=core,
            metadata_index=metadata_index,
            packages_by_npm=packages_by_npm,
        )
