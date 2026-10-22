"""Unit tests for release-date transformations and mocked forge write guards."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from subprocess import CompletedProcess

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
        {"version": "2.1.0", "reason": "fields-not-supplied", "fields": ["backstage_version"]}
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


# ---------------------------------------------------------------------------
# A supplied date that is not YYYY-MM-DD is never written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_date", ["next Tuesday", "2026-13-45", "09/22/2026"])
def test_a_non_date_value_is_reported_invalid_not_rendered(mod, bad_date):
    gh_doc = load(GITHUB_FILE)
    gl_doc = load(GITLAB_FILE)
    source = {"2.2.0": {**COMPLETE_2_1, "feature_freeze": bad_date}}

    assert states(mod.diff_github(source, load(GITHUB_FILE))) == {"2.2.0": "invalid"}
    assert states(mod.diff_gitlab(source, load(GITLAB_FILE))) == {"2.2.0": "invalid"}

    gh_changed, gh_skipped = mod.render_github(source, gh_doc)
    gl_changed, gl_skipped = mod.render_gitlab(source, gl_doc)

    assert gh_changed is False and gl_changed is False
    assert gh_entry(gh_doc, "2.2.0") is None
    assert "2.2.0" not in gl_doc["releases"]
    assert gh_skipped[0]["reason"] == "invalid-date"
    assert gl_skipped[0]["reason"] == "invalid-date"


def test_trailing_whitespace_on_tbd_is_still_treated_as_tbd(mod):
    source = {"2.2.0": {**COMPLETE_2_1, "feature_freeze": "TBD "}}

    assert states(mod.diff_github(source, load(GITHUB_FILE))) == {"2.2.0": "skipped-tbd"}


def test_a_valid_iso_date_still_renders(mod):
    gh_doc = load(GITHUB_FILE)
    source = {"2.2.0": {**COMPLETE_2_1, "feature_freeze": "2027-01-05"}}

    changed, skipped = mod.render_github(source, gh_doc)

    assert changed is True
    assert skipped == []
    assert gh_entry(gh_doc, "2.2.0")["feature-freeze"] == "2027-01-05"


def test_an_existing_entrys_invalid_update_is_not_written(mod):
    gh_doc = load(GITHUB_FILE)
    source = {"2.1.0": {**COMPLETE_2_1, "feature_freeze": "not-a-date"}}

    changed, skipped = mod.render_github(source, gh_doc)

    assert changed is False
    assert skipped[0]["reason"] == "invalid-date"
    assert gh_entry(gh_doc, "2.1.0")["feature-freeze"] == "2026-09-22"


# ---------------------------------------------------------------------------
# A bare x.y (what the planned-release spreadsheet path normalizes to) is a
# transcription bug, not an out-of-scope z-stream
# ---------------------------------------------------------------------------


def test_a_bare_major_minor_version_is_reported_invalid(mod):
    source = {"2.2": {**COMPLETE_2_1}}

    report = mod.diff_github(source, load(GITHUB_FILE))

    assert report[0]["state"] == "invalid"
    assert "x.y.0" in report[0]["error"]


def test_a_genuine_zstream_is_still_skipped_not_invalid(mod):
    source = {"1.10.5": {**COMPLETE_2_1}}

    assert states(mod.diff_github(source, load(GITHUB_FILE))) == {"1.10.5": "skipped-zstream"}


def _forbid_subprocess_calls(*_args, **_kwargs):
    raise AssertionError("no subprocess call should happen")


# ---------------------------------------------------------------------------
# apply refuses to write to a protected or misconfigured base branch
# ---------------------------------------------------------------------------


def test_apply_github_refuses_the_configured_base_branch(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "BRANCH_NAME", mod.GITHUB_BASE_BRANCH)
    monkeypatch.setattr(mod, "_run", _forbid_subprocess_calls)

    result = mod.apply_github(tmp_path / "rendered.yaml")

    assert result == {
        "target": "github",
        "ok": False,
        "error": (
            f"refusing to apply: RELEASE_DATE_UPDATE_BRANCH='{mod.GITHUB_BASE_BRANCH}' is a "
            "protected branch, not an update branch"
        ),
    }


@pytest.mark.parametrize("protected", ["main", "master", "develop", "release-1.10"])
def test_apply_github_refuses_well_known_protected_names(mod, monkeypatch, tmp_path, protected):
    monkeypatch.setattr(mod, "BRANCH_NAME", protected)
    monkeypatch.setattr(mod, "_run", _forbid_subprocess_calls)

    result = mod.apply_github(tmp_path / "rendered.yaml")

    assert result["ok"] is False
    assert "protected branch" in result["error"]


def test_apply_gitlab_refuses_the_configured_base_branch(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "BRANCH_NAME", mod.GITLAB_BASE_BRANCH)
    monkeypatch.setattr(mod, "_run", _forbid_subprocess_calls)

    result = mod.apply_gitlab(tmp_path / "rendered.yaml")

    assert result["ok"] is False
    assert "protected branch" in result["error"]


# ---------------------------------------------------------------------------
# apply refuses when the base file moved since render ran
# ---------------------------------------------------------------------------


def test_refuse_source_drift_is_silent_when_nothing_expected(mod):
    assert mod._refuse_source_drift("github", None, "sha-current") is None


def test_refuse_source_drift_is_silent_when_revision_matches(mod):
    assert mod._refuse_source_drift("github", "sha-same", "sha-same") is None


def test_refuse_source_drift_flags_a_mismatch(mod):
    result = mod._refuse_source_drift("github", "sha-old", "sha-new")

    assert result["ok"] is False
    assert "sha-old" in result["error"]
    assert "sha-new" in result["error"]


def test_apply_github_refuses_on_source_drift_before_any_write(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "fetch_github_file", lambda ref=None: ("content", "sha-current"))
    monkeypatch.setattr(mod, "_run", _forbid_subprocess_calls)

    result = mod.apply_github(tmp_path / "rendered.yaml", expect_revision="sha-old")

    assert result["ok"] is False
    assert "sha-old" in result["error"]
    assert "sha-current" in result["error"]


def test_apply_gitlab_refuses_on_source_drift_before_any_write(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "fetch_gitlab_file", lambda ref=None: ("content", "commit-current"))
    monkeypatch.setattr(mod, "_run", _forbid_subprocess_calls)

    result = mod.apply_gitlab(tmp_path / "rendered.yaml", expect_revision="commit-old")

    assert result["ok"] is False
    assert "commit-old" in result["error"]
    assert "commit-current" in result["error"]


def test_apply_github_proceeds_past_the_drift_check_on_a_matching_revision(
    mod, monkeypatch, tmp_path
):
    """A matching --expect-source-revision must not be refused.

    Rather than mock the whole gh/glab call chain for a full success path,
    let the next subprocess call raise a distinguishable marker — reaching it
    proves the drift check passed silently, which is `_refuse_source_drift`'s
    documented behaviour on a match.
    """
    monkeypatch.setattr(mod, "fetch_github_file", lambda ref=None: ("content", "sha-same"))

    def _marker(*_args, **_kwargs):
        raise RuntimeError("past the drift check")

    monkeypatch.setattr(mod, "_run", _marker)

    with pytest.raises(RuntimeError, match="past the drift check"):
        mod.apply_github(tmp_path / "rendered.yaml", expect_revision="sha-same")


@pytest.mark.parametrize("target", ["github", "gitlab"])
def test_apply_requires_a_render_time_revision(mod, monkeypatch, tmp_path, target):
    monkeypatch.setattr(mod, "_run", _forbid_subprocess_calls)
    result = getattr(mod, f"apply_{target}")(tmp_path / "rendered.yaml")
    assert result["ok"] is False
    assert "revision is required" in result["error"]


@pytest.mark.parametrize("target", ["github", "gitlab"])
@pytest.mark.parametrize("branch_exists", [False, True])
@pytest.mark.parametrize("branch_revision", ["render-revision", "edited-revision", None])
def test_apply_checks_destination_before_put(
    mod, monkeypatch, tmp_path, target, branch_exists, branch_revision
):
    """Neither an existing branch edit nor a creation-time race may be overwritten."""
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text("approved YAML")
    calls = []

    def fetch(ref=None):
        if ref == mod.BRANCH_NAME:
            if branch_revision is None:
                raise RuntimeError("could not read update branch")
            return "branch content", branch_revision
        return "base content", "render-revision"

    def run(argv):
        calls.append(argv)
        if "git/ref/heads/" in argv[2]:
            return CompletedProcess(argv, 0, '{"object":{"sha":"base-head"}}', "")
        if "POST" in argv:
            error = "Reference already exists" if target == "github" else "already exists"
            return CompletedProcess(argv, 1 if branch_exists else 0, "{}", error)
        if "PUT" in argv or "merge_requests?" in argv[-1]:
            return CompletedProcess(argv, 0, "[]", "")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(mod, f"fetch_{target}_file", fetch)
    monkeypatch.setattr(mod, "_run", run)
    monkeypatch.setattr(mod, "_run_json", lambda argv: [])
    writes = []

    def gh_api(endpoint, method, fields):
        writes.append(fields)
        return {"commit": {"sha": "new-commit"}}

    monkeypatch.setattr(mod, "gh_api", gh_api)
    result = getattr(mod, f"apply_{target}")(rendered, expect_revision="render-revision")

    if branch_revision != "render-revision":
        assert result["ok"] is False
        assert "update branch" in result["error"]
        assert writes == []
        assert not any("PUT" in argv for argv in calls)
    else:
        assert result["ok"] is True
        if target == "github":
            assert writes[0]["sha"] == "render-revision"
        else:
            put = next(argv for argv in calls if "PUT" in argv)
            assert "last_commit_id=render-revision" in put
