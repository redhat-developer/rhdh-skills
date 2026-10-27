"""Behavior tests for the third-party skill sync script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYNC = PROJECT_ROOT / "scripts" / "sync_third_party.py"

REGISTRY = {
    "schemaVersion": 1,
    "sources": {
        "somebody/skills": {
            "directory": "somebody-skills",
            "ref": "abc123",
            "license": "MIT",
            "skills": [
                {
                    "name": "demo",
                    "path": "skills/productivity/demo",
                    "mode": "tracked",
                }
            ],
        },
    },
}


def load_sync():
    spec = importlib.util.spec_from_file_location("sync_third_party", SYNC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sync():
    return load_sync()


def write_registry(root: Path, mode: str = "tracked") -> Path:
    registry = json.loads(json.dumps(REGISTRY))
    registry["sources"]["somebody/skills"]["skills"][0]["mode"] = mode
    registry_file = root / "registry.json"
    registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    skill_dir = root / "somebody-skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("original\n", encoding="utf-8")
    return skill_dir


def upstream_map(content: str = "original\n") -> dict[Path, bytes]:
    return {Path("skills/productivity/demo/SKILL.md"): content.encode()}


class TestLoadRegistry:
    def test_joins_skills_with_their_source_ref_and_license(self, sync, tmp_path):
        write_registry(tmp_path)
        entries = sync.load_registry(tmp_path)
        assert entries == [
            {
                "name": "demo",
                "source": "somebody/skills",
                "path": "skills/productivity/demo",
                "mode": "tracked",
                "directory": "somebody-skills",
                "ref": "abc123",
                "license": "MIT",
            }
        ]

    def test_a_source_without_skills_is_rejected(self, sync, tmp_path):
        write_registry(tmp_path)
        registry_file = tmp_path / "registry.json"
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        del registry["sources"]["somebody/skills"]["skills"]
        registry_file.write_text(json.dumps(registry), encoding="utf-8")
        with pytest.raises(sync.SyncError, match="non-empty array"):
            sync.load_registry(tmp_path)

    def test_a_duplicate_name_across_sources_is_rejected(self, sync, tmp_path):
        write_registry(tmp_path)
        registry_file = tmp_path / "registry.json"
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        registry["sources"]["someone-else/skills"] = {
            "directory": "someone-else-skills",
            "ref": "def456",
            "license": "MIT",
            "skills": [dict(registry["sources"]["somebody/skills"]["skills"][0])],
        }
        registry_file.write_text(json.dumps(registry), encoding="utf-8")
        with pytest.raises(sync.SyncError, match="duplicate skill"):
            sync.load_registry(tmp_path)

    def test_a_source_without_a_directory_is_rejected(self, sync, tmp_path):
        write_registry(tmp_path)
        registry_file = tmp_path / "registry.json"
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        del registry["sources"]["somebody/skills"]["directory"]
        registry_file.write_text(json.dumps(registry), encoding="utf-8")
        with pytest.raises(sync.SyncError, match="directory"):
            sync.load_registry(tmp_path)

    def test_a_source_without_a_ref_is_rejected(self, sync, tmp_path):
        write_registry(tmp_path)
        registry_file = tmp_path / "registry.json"
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        del registry["sources"]["somebody/skills"]["ref"]
        registry_file.write_text(json.dumps(registry), encoding="utf-8")
        with pytest.raises(sync.SyncError, match="ref"):
            sync.load_registry(tmp_path)

    def test_an_unknown_skill_field_is_rejected(self, sync, tmp_path):
        write_registry(tmp_path)
        registry_file = tmp_path / "registry.json"
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        registry["sources"]["somebody/skills"]["skills"][0]["ref"] = (
            "per-skill refs are not allowed"
        )
        registry_file.write_text(json.dumps(registry), encoding="utf-8")
        with pytest.raises(sync.SyncError, match="unknown fields: ref"):
            sync.load_registry(tmp_path)

    def test_a_bad_mode_is_rejected(self, sync, tmp_path):
        write_registry(tmp_path, mode="forked")
        with pytest.raises(sync.SyncError, match="mode"):
            sync.load_registry(tmp_path)


class TestCompareSkill:
    def test_reports_changed_missing_and_local_only(self, sync, tmp_path):
        skill_dir = write_registry(tmp_path)
        (skill_dir / "SKILL.md").write_text("edited\n", encoding="utf-8")
        (skill_dir / "NOTES.md").write_text("ours\n", encoding="utf-8")
        entry = sync.load_registry(tmp_path)[0]
        report = sync.compare_skill(
            skill_dir, entry, upstream_map() | {Path("skills/productivity/demo/NEW.md"): b"x"}
        )
        assert report["changed"] == ["SKILL.md"]
        assert report["missing"] == ["NEW.md"]
        assert report["local_only"] == ["NOTES.md"]

    def test_upstream_path_without_files_is_an_error(self, sync, tmp_path):
        skill_dir = write_registry(tmp_path)
        entry = sync.load_registry(tmp_path)[0]
        with pytest.raises(sync.SyncError, match="no files"):
            sync.compare_skill(skill_dir, entry, {Path("elsewhere/SKILL.md"): b"x"})


class TestApplySkill:
    def test_overwrites_only_upstream_files(self, sync, tmp_path):
        skill_dir = write_registry(tmp_path)
        (skill_dir / "SKILL.md").write_text("edited\n", encoding="utf-8")
        (skill_dir / "NOTES.md").write_text("ours\n", encoding="utf-8")
        entry = sync.load_registry(tmp_path)[0]
        written = sync.apply_skill(
            skill_dir,
            entry,
            upstream_map()
            | {Path("skills/productivity/demo/sub/NEW.md"): b"n"}
            | {Path("skills/productivity/demo/scripts/helper.py"): b"print('up')\n"},
        )
        # The whole upstream directory copies, not just SKILL.md: scripts and
        # other files a skill needs ride along.
        assert sorted(written) == ["SKILL.md", "scripts/helper.py", "sub/NEW.md"]
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "original\n"
        assert (skill_dir / "scripts" / "helper.py").read_bytes() == b"print('up')\n"
        assert (skill_dir / "NOTES.md").read_text(encoding="utf-8") == "ours\n"


class TestSync:
    def test_tracked_drift_fails_check_and_write_refreshes(self, sync, tmp_path, monkeypatch):
        skill_dir = write_registry(tmp_path)
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
        skill_dir = write_registry(tmp_path, mode="adapted")
        (skill_dir / "SKILL.md").write_text("our fork\n", encoding="utf-8")
        monkeypatch.setattr(sync, "fetch_upstream_files", lambda source, ref: upstream_map())

        reports, clean = sync.sync(tmp_path, write=True)
        assert clean is True
        assert reports[0]["action"] == "adapted-local-modifications"
        assert reports[0]["changed"] == ["SKILL.md"]
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "our fork\n"

    def test_a_skill_dir_missing_from_the_registry_is_an_error(self, sync, tmp_path):
        write_registry(tmp_path)
        unregistered = tmp_path / "somebody-skills" / "stray"
        unregistered.mkdir()
        (unregistered / "SKILL.md").write_text("x\n", encoding="utf-8")
        with pytest.raises(sync.SyncError, match="stray"):
            sync.sync(tmp_path, write=False)

    def test_a_registry_skill_without_a_directory_is_an_error(self, sync, tmp_path):
        write_registry(tmp_path)
        (tmp_path / "somebody-skills" / "demo" / "SKILL.md").unlink()
        with pytest.raises(sync.SyncError, match="no directory"):
            sync.sync(tmp_path, write=False)
