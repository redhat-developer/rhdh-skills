"""Routing from triage findings to the fix-phase outcome folders."""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/jira/rhdh-bug-triage"
sys.path.insert(0, str(SKILL / "scripts"))

from bugtriage.layout import _investigation_counts, fix_outcome  # noqa: E402


def finding(**overrides):
    base = {
        "verdict": "still_valid",
        "handoff": {},
        "investigation": {"status": "completed"},
        "fix_plan": {
            "complexity": "small",
            "areas": [
                {"repository": "redhat-developer/rhdh", "paths": ["packages/app/src/App.tsx"]}
            ],
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_explicit_handoff_wins():
    packet = finding(handoff={"outcome": "docs"})
    assert fix_outcome(packet) == "docs"


def test_resolution_verdicts_do_not_open_code():
    for verdict in ("duplicate", "already_fixed", "no_longer_valid"):
        assert fix_outcome(finding(verdict=verdict)) == "resolution"


def test_blocked_investigation_goes_to_blocked():
    packet = finding(verdict="unclear", investigation={"status": "blocked"})
    assert fix_outcome(packet) == "blocked"


def test_documentation_only_areas_go_to_docs():
    packet = finding(
        fix_plan={
            "complexity": "small",
            "areas": [
                {
                    "repository": "redhat-developer/red-hat-developers-documentation-rhdh",
                    "paths": ["modules/shared/proc-example.adoc"],
                }
            ],
        }
    )
    assert fix_outcome(packet) == "docs"


def test_mixed_or_code_areas_go_to_pull_requests():
    packet = finding(
        fix_plan={
            "complexity": "small",
            "areas": [
                {
                    "repository": "redhat-developer/red-hat-developers-documentation-rhdh",
                    "paths": ["modules/shared/proc-example.adoc"],
                },
                {
                    "repository": "redhat-developer/rhdh-plugins",
                    "paths": ["workspaces/homepage/plugins/homepage/src/App.tsx"],
                },
            ],
        }
    )
    assert fix_outcome(packet) == "pull-requests"


def test_complexity_none_is_resolution_only():
    assert fix_outcome(finding(fix_plan={"complexity": "none", "areas": []})) == "resolution"


def test_missing_investigations_count_as_not_recorded():
    counts = _investigation_counts(
        [
            finding(investigation={}),
            finding(investigation={"status": "not_recorded"}),
            finding(investigation={"status": "blocked"}),
            finding(),
        ]
    )
    assert counts == {"completed": 1, "blocked": 1, "not_recorded": 2}
