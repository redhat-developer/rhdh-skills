"""Unit tests for rhdh-release-fixversions sync logic."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "release"
    / "rhdh-release-fixversions"
    / "scripts"
)
CORE_PATH = SKILL_SCRIPTS / "_fixversions_core.py"
RELEASE_DATES_PATH = SKILL_SCRIPTS / "_release_dates.py"
STREAM_VERSIONS_PATH = SKILL_SCRIPTS / "_stream_versions.py"


def load_core():
    spec = importlib.util.spec_from_file_location("fixversions_core", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["fixversions_core"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def core():
    return load_core()


def load_release_dates():
    spec = importlib.util.spec_from_file_location("release_dates", RELEASE_DATES_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["release_dates"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release_dates():
    return load_release_dates()


def load_stream_versions():
    spec = importlib.util.spec_from_file_location("stream_versions", STREAM_VERSIONS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["stream_versions"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stream_versions():
    return load_stream_versions()


def _version(name: str, **kwargs):
    base = {
        "id": f"id-{name}",
        "name": name,
        "description": "",
        "startDate": "",
        "releaseDate": "",
        "released": False,
        "archived": False,
    }
    base.update(kwargs)
    return base


def test_compute_plan_creates_missing_projects(core):
    by_project = {
        "RHIDP": {"1.11.0": _version("1.11.0", releaseDate="2026-03-15")},
        "RHDHPLAN": {},
        "RHDHBUGS": {},
    }
    ops = core.compute_plan(by_project)
    creates = [op for op in ops if op["action"] == "create"]
    assert len(creates) == 2
    assert {op["project"] for op in creates} == {"RHDHPLAN", "RHDHBUGS"}


def test_compute_plan_updates_drift(core):
    by_project = {
        "RHIDP": {"1.11.0": _version("1.11.0", released=True)},
        "RHDHPLAN": {"1.11.0": _version("1.11.0", released=False)},
        "RHDHBUGS": {"1.11.0": _version("1.11.0", released=True)},
    }
    ops = core.compute_plan(by_project)
    updates = [op for op in ops if op["action"] == "update"]
    assert len(updates) == 1
    assert updates[0]["project"] == "RHDHPLAN"


def test_ensure_creates_everywhere_when_absent(core):
    by_project = {"RHIDP": {}, "RHDHPLAN": {}, "RHDHBUGS": {}}
    ops = core.compute_plan(
        by_project,
        only_name="2.0.0",
        override_meta={"releaseDate": "2026-06-01"},
    )
    assert len(ops) == 3
    assert all(op["action"] == "create" for op in ops)
    assert ops[0]["fields"]["releaseDate"] == "2026-06-01"


def test_diff_report_flags_missing_and_drift(core):
    by_project = {
        "RHIDP": {"1.10.0": _version("1.10.0")},
        "RHDHPLAN": {"1.10.0": _version("1.10.0", archived=True)},
        "RHDHBUGS": {},
    }
    rows = core.diff_report(by_project)
    row = next(r for r in rows if r["name"] == "1.10.0")
    assert row["canonical_lifecycle"] == "unreleased"
    assert row["projects"]["RHDHBUGS"]["sync"] == "missing"
    assert row["projects"]["RHDHBUGS"]["lifecycle"] is None
    assert row["projects"]["RHDHPLAN"]["lifecycle"] == "archived"
    assert row["projects"]["RHDHPLAN"]["sync"] == "drift"
    assert row["in_sync"] is False
    assert row["lifecycle_aligned"] is False


def test_version_lifecycle_precedence(core):
    assert core.version_lifecycle(_version("1.0", archived=True, released=True)) == "archived"
    assert core.version_lifecycle(_version("1.0", released=True)) == "released"
    assert core.version_lifecycle(_version("1.0")) == "unreleased"


def test_status_report_cross_project(core):
    by_project = {
        "RHIDP": {"1.11.0": _version("1.11.0", released=True, releaseDate="2026-03-01")},
        "RHDHPLAN": {"1.11.0": _version("1.11.0", released=False)},
        "RHDHBUGS": {},
    }
    report = core.status_report(by_project, "1.11.0")
    assert report["found"] is True
    assert report["canonical_lifecycle"] == "released"
    assert report["projects"]["RHIDP"]["lifecycle"] == "released"
    assert report["projects"]["RHDHPLAN"]["lifecycle"] == "unreleased"
    assert report["projects"]["RHDHBUGS"]["present"] is False
    assert report["lifecycle_aligned"] is False


def test_status_report_not_found(core):
    report = core.status_report({"RHIDP": {}, "RHDHPLAN": {}, "RHDHBUGS": {}}, "9.9.9")
    assert report["found"] is False


def test_recency_includes_unreleased_and_drops_old_ga(core):
    from datetime import date

    today = date(2026, 9, 9)
    by_project = {
        "RHIDP": {
            "1.11.0": _version("1.11.0"),
            "1.8.0": _version("1.8.0", released=True, releaseDate="2024-01-15"),
        },
        "RHDHPLAN": {},
        "RHDHBUGS": {},
    }
    names = core.filter_names_by_recency(
        by_project,
        {"1.11.0", "1.8.0"},
        within_days=365,
        today=today,
    )
    assert names == {"1.11.0"}


def test_apply_release_doc_dates_fills_empty_fields(core):
    meta = {
        "name": "1.9.8",
        "description": "",
        "startDate": "",
        "releaseDate": "",
        "released": False,
        "archived": False,
    }
    doc = {
        "issue_key": "RHDHPLAN-1634",
        "milestones": {
            "feature_freeze": "TBD",
            "code_freeze": "2026-08-03",
            "ga_announce": "2026-08-10",
            "go_no_go": "2026-08-10",
        },
    }
    enriched, sources = core.apply_release_doc_dates(meta, doc)
    assert enriched["releaseDate"] == "2026-08-10"
    assert enriched["startDate"] == "2026-08-03"
    assert "RHDHPLAN-1634" in sources["releaseDate"]


def test_apply_release_doc_respects_existing_dates(core):
    meta = {
        "name": "1.9.8",
        "startDate": "2026-01-01",
        "releaseDate": "2026-02-01",
        "released": False,
        "archived": False,
        "description": "",
    }
    doc = {
        "issue_key": "RHDHPLAN-1634",
        "milestones": {"ga_announce": "2026-08-10"},
    }
    enriched, sources = core.apply_release_doc_dates(meta, doc)
    assert enriched["releaseDate"] == "2026-02-01"
    assert sources == {}


def test_extract_milestone_dates_from_adf_table(release_dates):
    description = {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "GA Announce"}],
                                    }
                                ],
                            },
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "2026-08-10"}],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }
    dates = release_dates.extract_milestone_dates(description)
    assert dates["ga_announce"] == "2026-08-10"


def test_compute_plan_uses_release_doc_for_new_version(core):
    by_project = {"RHIDP": {}, "RHDHPLAN": {}, "RHDHBUGS": {}}
    release_docs = {
        "2.2.0": {
            "issue_key": "RHDHPLAN-9999",
            "milestones": {"ga_announce": "2026-12-01", "feature_freeze": "2026-10-01"},
        }
    }
    ops = core.compute_plan(
        by_project,
        only_name="2.2.0",
        release_docs=release_docs,
    )
    assert len(ops) == 3
    assert ops[0]["fields"]["releaseDate"] == "2026-12-01"
    assert ops[0]["fields"]["startDate"] == "2026-10-01"
    assert ops[0]["date_sources"]["releaseDate"] == "RHDHPLAN-9999 (ga announce)"


def test_close_out_report_blocks_unreleased(core):
    by_project = {
        "RHIDP": {"1.9.8": _version("1.9.8", released=True, releaseDate="2026-08-10")},
        "RHDHPLAN": {"1.9.8": _version("1.9.8", released=False)},
        "RHDHBUGS": {"1.9.8": _version("1.9.8", released=True, releaseDate="2026-08-10")},
    }
    report = core.close_out_report(
        by_project,
        "1.9.8",
        {
            "found": True,
            "issue_key": "RHDHPLAN-1634",
            "status": "Release Pending",
            "status_category": "indeterminate",
            "is_closed": False,
        },
    )
    assert report["ok"] is False
    assert report["fix_versions_released"] is False
    assert any("RHDHPLAN" in blocker for blocker in report["blockers"])
    assert report["suggested_command"] is not None


def test_close_out_report_ok_when_all_released(core):
    by_project = {
        "RHIDP": {"1.9.8": _version("1.9.8", released=True, releaseDate="2026-08-10")},
        "RHDHPLAN": {"1.9.8": _version("1.9.8", released=True, releaseDate="2026-08-10")},
        "RHDHBUGS": {"1.9.8": _version("1.9.8", released=True, releaseDate="2026-08-10")},
    }
    report = core.close_out_report(
        by_project,
        "1.9.8",
        {
            "found": True,
            "issue_key": "RHDHPLAN-1634",
            "status": "Release Pending",
            "is_closed": False,
        },
    )
    assert report["ok"] is True
    assert report["ready_to_close_release_feature"] is True
    assert report["blockers"] == []


def test_next_z_stream_version(stream_versions):
    assert stream_versions.next_z_stream_version("1.9.8") == "1.9.9"
    assert stream_versions.next_z_stream_version("1.11.0") == "1.11.1"
    assert stream_versions.next_z_stream_version("1.11") is None


def test_next_z_stream_follow_up_prompts_when_supported(core):
    by_project = {"RHIDP": {}, "RHDHPLAN": {}, "RHDHBUGS": {}}
    follow_up = core.next_z_stream_follow_up(
        by_project,
        "1.9.8",
        next_version="1.9.9",
        stream_lifecycle={"stream": "1.9", "supported": True},
        next_release_feature=None,
        release_feature_summary="RHDH 1.9.9 Release",
    )
    assert follow_up is not None
    assert follow_up["prompt_user"] is True
    assert follow_up["needs_fix_version"] is True
    assert follow_up["needs_release_feature"] is True
    assert "1.9.9" in follow_up["prompt_message"]


def test_next_z_stream_follow_up_skips_when_eol(core):
    by_project = {
        "RHIDP": {"1.9.9": _version("1.9.9")},
        "RHDHPLAN": {"1.9.9": _version("1.9.9")},
        "RHDHBUGS": {"1.9.9": _version("1.9.9")},
    }
    follow_up = core.next_z_stream_follow_up(
        by_project,
        "1.9.8",
        next_version="1.9.9",
        stream_lifecycle={"stream": "1.9", "supported": False, "type": "End of life"},
        next_release_feature={"found": True, "issue_key": "RHDHPLAN-9999"},
        release_feature_summary="RHDH 1.9.9 Release",
    )
    assert follow_up["prompt_user"] is False
    assert follow_up["needs_fix_version"] is False


def test_close_out_report_includes_next_z_stream(core):
    by_project = {"RHIDP": {}, "RHDHPLAN": {}, "RHDHBUGS": {}}
    next_z = {
        "next_version": "1.9.9",
        "prompt_user": True,
        "prompt_message": "Create fix version 1.9.9?",
    }
    report = core.close_out_report(
        by_project,
        "1.9.8",
        {"issue_key": "RHDHPLAN-1634", "is_closed": False},
        next_z_stream=next_z,
    )
    assert report["prompt_user"] is True
    assert report["next_z_stream"]["next_version"] == "1.9.9"


def test_release_feature_is_closed(release_dates):
    assert release_dates.release_feature_is_closed({"status_category": "done"}) is True
    assert release_dates.release_feature_is_closed({"status": "Closed"}) is True
    assert release_dates.release_feature_is_closed({"status": "Release Pending"}) is False


def test_recency_includes_recently_released(core):
    from datetime import date

    today = date(2026, 9, 9)
    by_project = {
        "RHIDP": {
            "1.10.3": _version("1.10.3", released=True, releaseDate="2026-03-01"),
        },
        "RHDHPLAN": {},
        "RHDHBUGS": {},
    }
    names = core.filter_names_by_recency(
        by_project,
        {"1.10.3"},
        within_days=365,
        today=today,
    )
    assert names == {"1.10.3"}
