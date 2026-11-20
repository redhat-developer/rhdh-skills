"""Shipped skill commands must run under BSD sed and bash 3.2, not only GNU sed and bash 5."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


def _shipped_scripts() -> list[Path]:
    return sorted(
        path for path in SKILLS.rglob("*.sh") if path.is_file() and "third-party" not in path.parts
    )


def _platform_bash() -> str:
    """The bash a stock shell resolves to: 3.2 on macOS, 5.x on Linux."""
    if Path("/bin/bash").is_file():
        return "/bin/bash"
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on this host to parse shipped scripts")
    return bash


def test_no_bare_sed_inplace_in_shipped_commands() -> None:
    """A bare `sed -i` breaks on the macOS runner the shell tests now use."""
    assert _find(BARE_SED_INPLACE, (".sh", ".md")) == []


def test_no_bash4_builtins_in_shipped_scripts() -> None:
    """macOS resolves `bash` to 3.2, which has no associative arrays or mapfile."""
    assert _find(BASH4_ONLY, (".sh",)) == []


@pytest.mark.parametrize(
    "script",
    _shipped_scripts(),
    ids=lambda path: str(path.relative_to(SKILLS)),
)
def test_shipped_scripts_parse_under_platform_bash(script: Path) -> None:
    """Parse every script with the host's bash, because 3.2 rejects syntax 5 accepts.

    `case` used directly inside `$( ... )` is valid bash 5 and a parse error on
    3.2, so the script emits a truncated report with no facts block at all. No
    regex rule sees that class, and no runtime test reaches it, because the
    script never gets far enough to run. The Linux runner parses with 5.x and
    passes; the macOS runner is what makes this bite.
    """
    result = subprocess.run(
        [_platform_bash(), "-n", str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{script.relative_to(ROOT)}: {result.stderr.strip()}"
