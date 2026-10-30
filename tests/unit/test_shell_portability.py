"""Shipped skill commands must run under BSD sed and bash 3.2, not only GNU sed and bash 5."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SKILLS = ROOT / "skills"

# A bare `sed -i`: BSD sed reads the next argument as the backup suffix, so
# `sed -i -E` runs the edit without -E and rewrites nothing.
BARE_SED_INPLACE = re.compile(r"^[ \t]*sed[ \t]+-[a-zA-Z]*i(?![.A-Za-z0-9])")
# Builtins that macOS bash 3.2 does not have.
BASH4_ONLY = re.compile(r"\bdeclare[ \t]+-A\b|\bmapfile\b|\breadarray\b")


def _find(pattern: re.Pattern[str], suffixes: tuple[str, ...]) -> list[str]:
    """Return `path:line: text` for every matching line in a shipped skill file."""
    hits: list[str] = []
    for path in sorted(SKILLS.rglob("*")):
        if path.suffix not in suffixes or not path.is_file():
            continue
        if "third-party" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    return hits


def test_no_bare_sed_inplace_in_shipped_commands() -> None:
    """A bare `sed -i` breaks on the macOS runner the shell tests now use."""
    assert _find(BARE_SED_INPLACE, (".sh", ".md")) == []


def test_no_bash4_builtins_in_shipped_scripts() -> None:
    """macOS resolves `bash` to 3.2, which has no associative arrays or mapfile."""
    assert _find(BASH4_ONLY, (".sh",)) == []
