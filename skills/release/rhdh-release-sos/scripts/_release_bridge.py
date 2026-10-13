"""Reuse query and date helpers from the sibling rhdh-release-status skill."""

from __future__ import annotations

import sys
from pathlib import Path

_STATUS_SCRIPTS = Path(__file__).resolve().parents[2] / "rhdh-release-status" / "scripts"


def status_scripts_dir() -> Path:
    """Return the rhdh-release-status scripts directory."""
    if not (_STATUS_SCRIPTS / "release.py").is_file():
        raise RuntimeError(
            "rhdh-release-status is required: expected scripts at "
            f"{_STATUS_SCRIPTS}. Install /rhdh-release-status alongside this skill."
        )
    return _STATUS_SCRIPTS


def import_release_modules():
    """Import jql, release, and rich_filter from rhdh-release-status."""
    directory = status_scripts_dir()
    path = str(directory)
    if path not in sys.path:
        sys.path.insert(0, path)
    import jql  # noqa: PLC0415
    import release  # noqa: PLC0415
    import rich_filter  # noqa: PLC0415

    return jql, release, rich_filter
