"""Install helper copies rhdh-spec-driven into a product repo's openspec/."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "skills/reference/rhdh-spec-driven-schema/scripts/install_project_schema.py"
SOURCE_SCHEMA = (
    ROOT / "skills/reference/rhdh-spec-driven-schema/schemas/rhdh-spec-driven/schema.yaml"
)


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_install_writes_config_and_schema(tmp_path: Path) -> None:
    result = run(tmp_path, str(tmp_path))
    assert result.returncode == 0, result.stderr
    config = tmp_path / "openspec" / "config.yaml"
    schema = tmp_path / "openspec" / "schemas" / "rhdh-spec-driven" / "schema.yaml"
    assert config.is_file()
    assert "schema: rhdh-spec-driven" in config.read_text(encoding="utf-8")
    assert schema.is_file()
    assert schema.read_text(encoding="utf-8") == SOURCE_SCHEMA.read_text(encoding="utf-8")
    assert (tmp_path / "openspec" / "changes").is_dir()


def test_install_is_idempotent_without_force(tmp_path: Path) -> None:
    assert run(tmp_path, str(tmp_path)).returncode == 0
    config = tmp_path / "openspec" / "config.yaml"
    config.write_text("schema: custom\n", encoding="utf-8")
    result = run(tmp_path, str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert config.read_text(encoding="utf-8") == "schema: custom\n"
    assert "kept" in result.stdout


def test_force_overwrites_existing(tmp_path: Path) -> None:
    assert run(tmp_path, str(tmp_path)).returncode == 0
    config = tmp_path / "openspec" / "config.yaml"
    config.write_text("schema: custom\n", encoding="utf-8")
    result = run(tmp_path, str(tmp_path), "--force")
    assert result.returncode == 0, result.stderr
    assert "schema: rhdh-spec-driven" in config.read_text(encoding="utf-8")
    assert "replaced" in result.stdout
