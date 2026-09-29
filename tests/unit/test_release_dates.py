"""Unit tests for rhdh-release-date-update diff and render logic.

The four functions under test are pure: they take the source-JSON dict and an
already-loaded YAML document, and touch no network. Everything that talks to
gh/glab lives in separate functions and is not exercised here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ruamel_yaml = pytest.importorskip("ruamel.yaml")

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "release"
    / "rhdh-release-date-update"
    / "scripts"
    / "release_dates.py"
)

GITHUB_FILE = """\
releases:
  - rhdh-version: "2.1.0"
    backstage-version: "1.54.0"
    feature-freeze: "2026-09-22"
"""

GITLAB_FILE = """\
releases:
  "2.1.0":
    feature_freeze: "2026-09-22"
    code_freeze: "2026-10-13"
    ga_push: "2026-10-28"
    backstage_version: "1.54.0"
"""

COMPLETE_2_1 = {
    "feature_freeze": "2026-09-22",
    "code_freeze": "2026-10-13",
    "ga_push": "2026-10-28",
    "backstage_version": "1.54.0",
}


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("release_dates", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["release_dates"] = module
    spec.loader.exec_module(module)
    return module


def load(text: str):
    yaml = ruamel_yaml.YAML()
    yaml.preserve_quotes = True
    return yaml.load(text)


def states(report):
    return {entry["version"]: entry["state"] for entry in report}


def gh_entry(doc, version):
    for entry in doc["releases"]:
        if str(entry["rhdh-version"]) == version:
            return entry
    return None


# ---------------------------------------------------------------------------
# Regression: an unsupplied field must never be written as the string "None"
# ---------------------------------------------------------------------------


def test_github_render_preserves_backstage_version_when_source_omits_it(mod):
    doc = load(GITHUB_FILE)
    source = {"2.1.0": {"feature_freeze": "2026-09-22"}}

    changed, skipped = mod.render_github(source, doc)

    assert gh_entry(doc, "2.1.0")["backstage-version"] == "1.54.0"
    assert changed is False
    assert skipped == [
        {"version": "2.1.0", "reason": "field-not-supplied", "field": "backstage_version"}
    ]


def test_gitlab_render_preserves_unsupplied_fields(mod):
    doc = load(GITLAB_FILE)
    source = {"2.1.0": {"feature_freeze": "2026-09-22"}}

    changed, skipped = mod.render_gitlab(source, doc)

    entry = doc["releases"]["2.1.0"]
    assert entry["backstage_version"] == "1.54.0"
    assert entry["code_freeze"] == "2026-10-13"
    assert entry["ga_push"] == "2026-10-28"
    assert changed is False
    assert skipped[0]["reason"] == "fields-not-supplied"
    assert set(skipped[0]["fields"]) == {"code_freeze", "ga_push", "backstage_version"}


@pytest.mark.parametrize("absent", [None, "", "TBD", "tbd"])
def test_no_target_ever_renders_the_placeholder_none(mod, absent):
    gh_doc = load(GITHUB_FILE)
    gl_doc = load(GITLAB_FILE)
    source = {"2.1.0": {**COMPLETE_2_1, "backstage_version": absent}}

    mod.render_github(source, gh_doc)
    mod.render_gitlab(source, gl_doc)

    assert gh_entry(gh_doc, "2.1.0")["backstage-version"] == "1.54.0"
    assert gl_doc["releases"]["2.1.0"]["backstage_version"] == "1.54.0"


def test_diff_does_not_call_an_entry_stale_over_an_unsupplied_field(mod):
    source = {"2.1.0": {"feature_freeze": "2026-09-22"}}

    assert states(mod.diff_github(source, load(GITHUB_FILE))) == {"2.1.0": "match"}
    assert states(mod.diff_gitlab(source, load(GITLAB_FILE))) == {"2.1.0": "match"}


# ---------------------------------------------------------------------------
# A new entry is withheld rather than created partial
# ---------------------------------------------------------------------------


def test_github_new_entry_without_backstage_version_is_incomplete(mod):
    source = {"2.2.0": {"feature_freeze": "2027-01-05"}}

    report = mod.diff_github(source, load(GITHUB_FILE))

    assert report[0]["state"] == "incomplete"
    assert report[0]["missing_fields"] == ["backstage_version"]


def test_gitlab_new_entry_missing_fields_are_named(mod):
    source = {"2.2.0": {"feature_freeze": "2027-01-05", "code_freeze": "2027-01-26"}}

    report = mod.diff_gitlab(source, load(GITLAB_FILE))

    assert report[0]["state"] == "incomplete"
    assert report[0]["missing_fields"] == ["ga_push", "backstage_version"]


def test_incomplete_new_entry_is_not_written(mod):
    gh_doc = load(GITHUB_FILE)
    gl_doc = load(GITLAB_FILE)
    source = {"2.2.0": {"feature_freeze": "2027-01-05"}}

    gh_changed, gh_skipped = mod.render_github(source, gh_doc)
    gl_changed, gl_skipped = mod.render_gitlab(source, gl_doc)

    assert gh_changed is False and gl_changed is False
    assert gh_entry(gh_doc, "2.2.0") is None
    assert "2.2.0" not in gl_doc["releases"]
    assert gh_skipped[0]["reason"] == "incomplete"
    assert gl_skipped[0]["reason"] == "incomplete"


# ---------------------------------------------------------------------------
# Happy paths still work
# ---------------------------------------------------------------------------


def test_complete_new_entry_is_created_on_both_targets(mod):
    gh_doc = load(GITHUB_FILE)
    gl_doc = load(GITLAB_FILE)
    source = {
        "2.2.0": {
            "feature_freeze": "2027-01-05",
            "code_freeze": "2027-01-26",
            "ga_push": "2027-02-17",
            "backstage_version": "1.58.0",
        }
    }

    assert mod.render_github(source, gh_doc)[0] is True
    assert mod.render_gitlab(source, gl_doc)[0] is True

    assert gh_entry(gh_doc, "2.2.0")["backstage-version"] == "1.58.0"
    assert gh_entry(gh_doc, "2.2.0")["feature-freeze"] == "2027-01-05"
    assert gl_doc["releases"]["2.2.0"]["ga_push"] == "2027-02-17"


def test_supplied_field_that_differs_is_still_updated(mod):
    gh_doc = load(GITHUB_FILE)
    gl_doc = load(GITLAB_FILE)
    source = {"2.1.0": {**COMPLETE_2_1, "feature_freeze": "2026-10-06"}}

    assert mod.render_github(source, gh_doc)[0] is True
    assert mod.render_gitlab(source, gl_doc)[0] is True

    assert gh_entry(gh_doc, "2.1.0")["feature-freeze"] == "2026-10-06"
    assert gl_doc["releases"]["2.1.0"]["feature_freeze"] == "2026-10-06"
    assert states(mod.diff_github(source, load(GITHUB_FILE))) == {"2.1.0": "stale"}


# ---------------------------------------------------------------------------
# Versions the target files do not track
# ---------------------------------------------------------------------------


def test_zstream_is_reported_and_never_written(mod):
    gh_doc = load(GITHUB_FILE)
    gl_doc = load(GITLAB_FILE)
    source = {"1.10.5": {**COMPLETE_2_1}}

    assert states(mod.diff_github(source, load(GITHUB_FILE))) == {"1.10.5": "skipped-zstream"}
    assert states(mod.diff_gitlab(source, load(GITLAB_FILE))) == {"1.10.5": "skipped-zstream"}

    assert mod.render_github(source, gh_doc) == (
        False,
        [{"version": "1.10.5", "reason": "zstream"}],
    )
    assert mod.render_gitlab(source, gl_doc) == (
        False,
        [{"version": "1.10.5", "reason": "zstream"}],
    )
    assert gh_entry(gh_doc, "1.10.5") is None
    assert "1.10.5" not in gl_doc["releases"]


@pytest.mark.parametrize("tbd", [None, "", "TBD", "tbd"])
def test_undecided_feature_freeze_is_skipped(mod, tbd):
    gh_doc = load(GITHUB_FILE)
    source = {"2.2.0": {**COMPLETE_2_1, "feature_freeze": tbd}}

    assert states(mod.diff_github(source, load(GITHUB_FILE))) == {"2.2.0": "skipped-tbd"}
    assert mod.render_github(source, gh_doc) == (False, [{"version": "2.2.0", "reason": "tbd"}])
    assert gh_entry(gh_doc, "2.2.0") is None


def test_versions_absent_from_the_source_are_left_alone(mod):
    gh_doc = load(GITHUB_FILE)
    source = {"2.2.0": {**COMPLETE_2_1, "feature_freeze": "2027-01-05"}}

    mod.render_github(source, gh_doc)

    assert gh_entry(gh_doc, "2.1.0")["feature-freeze"] == "2026-09-22"
