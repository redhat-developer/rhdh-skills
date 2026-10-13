"""Contract tests for the OpenSpec journal helper.

Covers the containment, field-validation, and archive-naming guarantees the
CLI must not regress: a change name can never escape openspec/changes/, the
derived ts/event fields cannot be forged via k=v, constrained fields reject
junk, and a short name never resolves to a longer date-prefixed archive.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "skills/reference/openspec-journal/scripts/openspec-journal.py"


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "openspec" / "changes" / "data-export").mkdir(parents=True)
    return tmp_path


def test_write_and_read_round_trip(workspace: Path) -> None:
    result = run(workspace, "data-export", "decision", "input=Chose CSV", "output=Done")
    assert result.returncode == 0, result.stderr
    line = (workspace / "openspec/changes/data-export/journal.jsonl").read_text().strip()
    record = json.loads(line)
    assert record["event"] == "decision"
    assert record["input"] == "Chose CSV"


@pytest.mark.parametrize("bad", ["../../secrets", "a/b", "..", "a\\b"])
def test_change_name_cannot_escape_changes_dir(workspace: Path, bad: str) -> None:
    (workspace / "secrets").mkdir()
    result = run(workspace, bad, "decision", "input=x", "output=y")
    assert result.returncode != 0
    assert not (workspace / "secrets" / "journal.jsonl").exists()


def test_reserved_fields_cannot_be_forged(workspace: Path) -> None:
    result = run(
        workspace,
        "data-export",
        "decision",
        "input=x",
        "output=y",
        "event=archive",
        "ts=1970-01-01T00:00:00Z",
        "phase=archive",
    )
    assert result.returncode == 2
    assert not (workspace / "openspec/changes/data-export/journal.jsonl").exists()


@pytest.mark.parametrize("bad", [".", "archive"])
def test_change_name_cannot_be_changes_or_archive_root(workspace: Path, bad: str) -> None:
    result = run(workspace, bad, "decision", "input=x", "output=y")
    assert result.returncode != 0
    assert not (workspace / "openspec/changes/journal.jsonl").exists()
    assert not (workspace / "openspec/changes/archive/journal.jsonl").exists()


def test_input_file_must_stay_under_change_dir(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret summary that is short", encoding="utf-8")
    result = run(
        workspace,
        "data-export",
        "decision",
        f"--input-file={outside}",
        "output=y",
    )
    assert result.returncode != 0
    assert not (workspace / "openspec/changes/data-export/journal.jsonl").exists()


def test_input_file_under_change_dir_is_accepted(workspace: Path) -> None:
    inside = workspace / "openspec/changes/data-export/note.txt"
    inside.write_text("Chose CSV", encoding="utf-8")
    result = run(
        workspace,
        "data-export",
        "decision",
        f"--input-file={inside}",
        "output=Done",
    )
    assert result.returncode == 0, result.stderr
    record = json.loads(
        (workspace / "openspec/changes/data-export/journal.jsonl").read_text().strip()
    )
    assert record["input"] == "Chose CSV"
    assert record["phase"] == "any"


def test_unknown_extra_field_rejected(workspace: Path) -> None:
    result = run(workspace, "data-export", "decision", "input=x", "output=y", "junk=1")
    assert result.returncode == 2
    assert "unknown field" in result.stderr


def test_mode_validated_on_task_complete(workspace: Path) -> None:
    result = run(
        workspace,
        "data-export",
        "task.complete",
        "ref=1.1",
        "mode=banana",
        "input=x",
        "output=y",
    )
    assert result.returncode == 2
    assert "mode='banana'" in result.stderr


def test_count_must_be_integer(workspace: Path) -> None:
    result = run(workspace, "data-export", "agent.spawned", "count=nope", "kind=debate")
    assert result.returncode == 2
    assert "count='nope'" in result.stderr


def test_count_is_stored_as_int(workspace: Path) -> None:
    result = run(workspace, "data-export", "agent.spawned", "count=3", "kind=debate")
    assert result.returncode == 0, result.stderr
    record = json.loads(
        (workspace / "openspec/changes/data-export/journal.jsonl").read_text().strip()
    )
    assert record["count"] == 3


def test_short_name_does_not_match_longer_archived_change(workspace: Path) -> None:
    archive = workspace / "openspec/changes/archive/2026-01-01-user-auth"
    archive.mkdir(parents=True)
    result = run(workspace, "auth", "decision", "input=x", "output=y")
    assert result.returncode != 0
    assert not (archive / "journal.jsonl").exists()


def test_date_prefixed_archive_resolves_by_exact_name(workspace: Path) -> None:
    archive = workspace / "openspec/changes/archive/2026-01-01-user-auth"
    archive.mkdir(parents=True)
    result = run(workspace, "user-auth", "decision", "input=x", "output=y")
    assert result.returncode == 0, result.stderr
    assert (archive / "journal.jsonl").exists()
