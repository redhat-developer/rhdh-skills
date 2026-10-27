"""Behavior tests for the third-party skill sync script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYNC = PROJECT_ROOT / "scripts" / "sync_third_party.py"

UPSTREAM_TOML = """\
# provenance
source = "somebody/skills"
path = "skills/productivity/demo"
ref = "abc123"
mode = "{mode}"
"""


def load_sync():
    spec = importlib.util.spec_from_file_location("sync_third_party", SYNC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sync():
    return load_sync()


def make_skill(root: Path, mode: str = "tracked") -> Path:
    skill_dir = root / "demo"
    (skill_dir).mkdir(parents=True)
    (skill_dir / "UPSTREAM.toml").write_text(UPSTREAM_TOML.format(mode=mode), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("original\n", encoding="utf-8")
    return skill_dir


def upstream_map(content: str = "original\n") -> dict[Path, bytes]:
    return {Path("skills/productivity/demo/SKILL.md"): content.encode()}


class TestParseUpstreamToml:
    def test_parses_the_four_fixed_fields(self, sync):
        fields = sync.parse_upstream_toml(UPSTREAM_TOML.format(mode="tracked"), Path("x"))
        assert fields == {
            "source": "somebody/skills",
            "path": "skills/productivity/demo",
            "ref": "abc123",
            "mode": "tracked",
        }

    @pytest.mark.parametrize(
        ("line", "problem"),
        [
            ('mode = "forked"\n', "mode"),
            ("ref = 123\n", "not a"),
            ('bogus = "x"\n', "unknown field"),
        ],
    )
    def test_rejects_malformed_lines(self, sync, line, problem):
        text = UPSTREAM_TOML.format(mode="tracked").replace('ref = "abc123"\n', line)
        if line.startswith("bogus"):
            text = UPSTREAM_TOML.format(mode="tracked") + line
        with pytest.raises(sync.SyncError, match=problem):
            sync.parse_upstream_toml(text, Path("x"))

    def test_rejects_missing_fields(self, sync):
        text = 'source = "a/b"\npath = "p"\nmode = "tracked"\n'
        with pytest.raises(sync.SyncError, match="ref"):
            sync.parse_upstream_toml(text, Path("x"))

    def test_rejects_source_that_is_not_owner_repo(self, sync):
        text = UPSTREAM_TOML.format(mode="tracked").replace(
            '"somebody/skills"', '"github.com/somebody/skills"'
        )
        with pytest.raises(sync.SyncError, match="owner/repo"):
            sync.parse_upstream_toml(text, Path("x"))


class TestCompareSkill:
    def test_reports_changed_missing_and_local_only(self, sync, tmp_path):
        skill_dir = make_skill(tmp_path)
        (skill_dir / "SKILL.md").write_text("edited\n", encoding="utf-8")
        (skill_dir / "NOTES.md").write_text("ours\n", encoding="utf-8")
        fields = sync.parse_upstream_toml(
            UPSTREAM_TOML.format(mode="tracked"), skill_dir / "UPSTREAM.toml"
        )
        report = sync.compare_skill(
            skill_dir, fields, upstream_map() | {Path("skills/productivity/demo/NEW.md"): b"x"}
        )
        assert report["changed"] == ["SKILL.md"]
        assert report["missing"] == ["NEW.md"]
        assert report["local_only"] == ["NOTES.md"]

    def test_upstream_path_without_files_is_an_error(self, sync, tmp_path):
        skill_dir = make_skill(tmp_path)
        fields = sync.parse_upstream_toml(
            UPSTREAM_TOML.format(mode="tracked"), skill_dir / "UPSTREAM.toml"
        )
        with pytest.raises(sync.SyncError, match="no files"):
            sync.compare_skill(skill_dir, fields, {Path("elsewhere/SKILL.md"): b"x"})


class TestApplySkill:
    def test_overwrites_only_upstream_files(self, sync, tmp_path):
        skill_dir = make_skill(tmp_path)
        (skill_dir / "SKILL.md").write_text("edited\n", encoding="utf-8")
        (skill_dir / "NOTES.md").write_text("ours\n", encoding="utf-8")
        fields = sync.parse_upstream_toml(
            UPSTREAM_TOML.format(mode="tracked"), skill_dir / "UPSTREAM.toml"
        )
        written = sync.apply_skill(
            skill_dir, fields, upstream_map() | {Path("skills/productivity/demo/sub/NEW.md"): b"n"}
        )
        assert sorted(written) == ["SKILL.md", "sub/NEW.md"]
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "original\n"
        assert (skill_dir / "NOTES.md").read_text(encoding="utf-8") == "ours\n"


class TestSync:
    def test_tracked_drift_fails_check_and_write_refreshes(self, sync, tmp_path, monkeypatch):
        skill_dir = make_skill(tmp_path)
        (skill_dir / "SKILL.md").write_text("edited\n", encoding="utf-8")
        monkeypatch.setattr(sync, "fetch_upstream_files", lambda source, ref: upstream_map())

        reports, clean = sync.sync(tmp_path, write=False)
        assert clean is False
        assert reports[0]["action"] == "drift"

        reports, clean = sync.sync(tmp_path, write=True)
        assert clean is True  # the refresh repaired the drift in place
        assert reports[0]["action"] == "refreshed"
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "original\n"

        _, clean = sync.sync(tmp_path, write=False)
        assert clean is True

    def test_adapted_drift_is_reported_but_never_written(self, sync, tmp_path, monkeypatch):
        skill_dir = make_skill(tmp_path, mode="adapted")
        (skill_dir / "SKILL.md").write_text("our fork\n", encoding="utf-8")
        monkeypatch.setattr(sync, "fetch_upstream_files", lambda source, ref: upstream_map())

        reports, clean = sync.sync(tmp_path, write=True)
        assert clean is True
        assert reports[0]["action"] == "adapted-local-modifications"
        assert reports[0]["changed"] == ["SKILL.md"]
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "our fork\n"

    def test_a_skill_without_provenance_is_an_error(self, sync, tmp_path):
        (tmp_path / "demo").mkdir()
        (tmp_path / "demo" / "SKILL.md").write_text("x\n", encoding="utf-8")
        with pytest.raises(sync.SyncError, match="without UPSTREAM.toml"):
            sync.discover_skills(tmp_path)
