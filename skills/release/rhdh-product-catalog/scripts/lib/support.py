"""Support-level labels shared by product-catalog scripts."""

from __future__ import annotations

from typing import Any

SUPPORT_ORDER = (
    "generally-available",
    "tech-preview",
    "dev-preview",
    "community",
    "unknown",
)
SUPPORT_LABELS = {
    "generally-available": "Generally Available",
    "tech-preview": "Tech Preview",
    "dev-preview": "Developer Preview",
    "community": "Community",
    "unknown": "Unknown",
}
SUPPORT_ALIASES = {
    "ga": "generally-available",
    "generally available": "generally-available",
    "generally-available": "generally-available",
    "generally_available": "generally-available",
    # Overlay 1.9 (and earlier) used "production" for GA.
    "production": "generally-available",
    "tp": "tech-preview",
    "tech preview": "tech-preview",
    "tech-preview": "tech-preview",
    "tech_preview": "tech-preview",
    "dp": "dev-preview",
    "dev preview": "dev-preview",
    "developer preview": "dev-preview",
    "dev-preview": "dev-preview",
    "dev_preview": "dev-preview",
    "community": "community",
    "unknown": "unknown",
}


def as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_support(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = raw.get("level")
    if raw is None or raw == "":
        return "unknown"
    key = as_str(raw).lower().replace("_", "-")
    key = SUPPORT_ALIASES.get(key, key)
    if key not in SUPPORT_LABELS:
        return "unknown"
    return key


def resolve_support_filters(values: list[str]) -> set[str]:
    resolved: set[str] = set()
    for raw in values:
        key = normalize_support(raw)
        if key == "unknown" and raw.strip().lower() not in {"unknown"}:
            raise ValueError(f"Unrecognized support level: {raw}")
        resolved.add(key)
    return resolved


def md_cell(value: str) -> str:
    return (value or "—").replace("|", "\\|").replace("\n", " ")


def source_caption(source: dict[str, str], ref: str) -> str:
    kind = source.get("type", "")
    if kind == "tarball":
        caption = f"redhat-developer/rhdh-plugin-export-overlays@{ref} (tarball)"
    else:
        path = source.get("path", "")
        if kind == "local-git":
            caption = f"local git {path} (`{ref}`)"
        elif kind == "workdir":
            caption = f"working tree {path}"
        else:
            caption = f"{kind} {path}".strip()
    if source.get("pre_release") == "true":
        caption += " — pre-release"
    return caption


def source_caption_diff(source: dict[str, str], ref_from: str, ref_to: str) -> str:
    kind = source.get("type", "")
    path = source.get("path", "")
    span = f"`{ref_from}` → `{ref_to}`"
    if kind == "tarball":
        caption = f"redhat-developer/rhdh-plugin-export-overlays {span} (tarball)"
    elif kind == "local-git":
        caption = f"local git {path} ({span})"
    else:
        caption = f"{kind} {path} ({span})".strip()
    notes = []
    if source.get("pre_release_from") == "true":
        notes.append(f"`{ref_from}` is pre-release")
    if source.get("pre_release_to") == "true":
        notes.append(f"`{ref_to}` is pre-release")
    if notes:
        caption += f" ({'; '.join(notes)})"
    return caption
