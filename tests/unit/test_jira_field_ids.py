"""The five copies of the Jira custom-field IDs must agree with fields.md.

ADR-0006 accepts duplicating these IDs so a skill installs alone. The cost is a
failure mode with no symptom: a stale copy reads a `customfield_*` key that is
not there, yields "", and the caller reports missing data instead of raising.

Only the offline half of the validator runs here. The `--live` half needs `acli`
and a Jira session, which CI does not have — but it is also not the half that
catches this. A copy drifting from the reference table is, and that comparison is
pure text.
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
JIRA_CONTEXT = PROJECT_ROOT / "skills" / "reference" / "rhdh-jira-context"
VALIDATOR = JIRA_CONTEXT / "scripts" / "validate_field_ids.py"


def run_validator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=JIRA_CONTEXT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_every_copy_agrees_with_the_reference_table():
    result = run_validator("--json")

    assert result.returncode == 0, (
        "A Jira custom-field ID has drifted from references/fields.md.\n"
        f"{result.stdout}\n{result.stderr}"
    )
    report = json.loads(result.stdout)
    assert report["inSync"] is True
    assert report["findings"] == []


def test_the_validator_checks_every_declared_copy():
    """A copy that moves or is renamed must fail loudly, not drop out of scope."""
    report = json.loads(run_validator("--json").stdout)

    assert report["copiesChecked"] == 5, (
        "COPY_PATHS no longer lists five copies. If a skill gained or lost its "
        "own field IDs, update the list and this expectation together."
    )
    assert report["documentedCount"] > 0, "No custom fields parsed from fields.md"


def test_a_drifted_copy_is_reported_with_its_path(tmp_path):
    """Prove the check fails on drift rather than passing vacuously.

    Reads and restores bytes rather than text. `write_text` re-encodes newlines
    per platform, so a text round-trip rewrites an LF file as CRLF on Windows and
    leaves the tree dirty — which fails the pre-commit hook even though every
    assertion passed.
    """
    copy = PROJECT_ROOT / "skills" / "release" / "rhdh-release-status" / "scripts" / "_jira.py"
    original = copy.read_bytes()
    assert b'"customfield_10028"' in original, "fixture ID missing; update this test"

    try:
        copy.write_bytes(original.replace(b'"customfield_10028"', b'"customfield_00000"', 1))
        result = run_validator("--json")
    finally:
        copy.write_bytes(original)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["inSync"] is False
    findings = [f for f in report["findings"] if f["code"] == "COPY_UNDOCUMENTED_ID"]
    assert findings, report
    assert "rhdh-release-status" in findings[0]["path"]
    assert "customfield_00000" in findings[0]["detail"]
