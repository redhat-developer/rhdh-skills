"""Z-stream (patch) version helpers for fix version names."""

from __future__ import annotations

import re

_Z_STREAM_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_Y_STREAM_RE = re.compile(r"^(\d+)\.(\d+)$")


def parse_z_stream(version: str) -> tuple[int, int, int] | None:
    match = _Z_STREAM_RE.match(version.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def y_stream_key(version: str) -> str | None:
    parsed = parse_z_stream(version)
    if parsed is not None:
        return f"{parsed[0]}.{parsed[1]}"
    match = _Y_STREAM_RE.match(version.strip())
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return None


def next_z_stream_version(version: str) -> str | None:
    """Bump the patch segment: 1.9.8 -> 1.9.9."""
    parsed = parse_z_stream(version)
    if parsed is None:
        return None
    major, minor, patch = parsed
    return f"{major}.{minor}.{patch + 1}"


def release_feature_summary(version: str) -> str:
    return f"RHDH {version} Release"
