from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "jira" / "rhdh-install-prepare-refinement"
SCRIPT = SKILL / "scripts" / "prepare_refinement.py"
SCRIPT_DIR = SCRIPT.parent
FIXTURE = SKILL / "fixtures" / "refinement-queue.sample.json"


def run_fixture(*extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--fixture",
        str(FIXTURE),
        "--today",
        "2026-10-05",
        *extra,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=SCRIPT_DIR, check=False)


def test_fixture_briefing_omits_zero_signals_and_lists_attention():
    result = run_fixture("--no-facts")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "# 🎯 RHDH Install · Refinement" in out
    assert "🔥 **Freeze approaching**" in out
    assert "4 issues need an owner" in out
    assert "1 Epic needs breakdown" in out
    assert "6 issues have no Priority" in out
    assert "4 issues have no detected gaps" in out
    assert "0 blocked" not in out.lower()


def test_facts_json_includes_overlaps(tmp_path: Path):
    facts_path = tmp_path / "facts.json"
    result = run_fixture("--facts-out", str(facts_path))
    assert result.returncode == 0, result.stderr
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    assert facts["queue"]["total"] == 14
    assert facts["release"]["freeze_days"] == 8
    overlap_keys = {entry["key"] for entry in facts["overlaps"]}
    assert "RHIDP-15433" in overlap_keys
    assert "RHIDP-17196" in overlap_keys
