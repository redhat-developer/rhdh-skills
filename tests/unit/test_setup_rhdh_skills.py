"""Behavior tests for the setup router's deterministic setup script."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = PROJECT_ROOT / "skills" / "meta" / "setup-rhdh-skills" / "scripts" / "setup.py"
CATALOG = PROJECT_ROOT / "skills" / "meta" / "setup-rhdh-skills" / "assets" / "catalog.json"


def load_setup_module():
    spec = importlib.util.spec_from_file_location("setup_rhdh_skills_script", SETUP_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def every_packaged_skill(catalog: dict) -> list[str]:
    return sorted(entry["name"] for entry in catalog["skills"])


def run_setup(*args: str) -> subprocess.CompletedProcess[str]:
    # The script is self-contained: standard library only, no shared package.
    return subprocess.run(
        [sys.executable, str(SETUP_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def install_fake_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"---\nname: {name}\ndescription: fake installed skill for setup tests\n---\n",
        encoding="utf-8",
    )
    return skill_file


def test_doctor_discovers_dependencies_across_supported_host_layouts(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    install_fake_skill(home / ".agents" / "skills", "grilling")
    install_fake_skill(home / ".claude" / "skills", "mutation-gate")
    install_fake_skill(project / ".cursor" / "skills", "ask-rhdh")

    result = run_setup(
        "doctor",
        "--catalog",
        str(CATALOG),
        "--home",
        str(home),
        "--project-root",
        str(project),
        "--no-tool-probes",
        "--json",
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert "contract" not in report
    assert set(report["installedSkills"]) == {"ask-rhdh", "grilling", "mutation-gate"}
    assert report["capabilities"]["tools"]["oc"] == "not-probed"
    assert report["capabilities"]["tools"]["gog"] == "not-probed"
    assert "setup-rhdh-skills" in report["missingSkills"]
    assert all("credential" not in key.lower() for key in report)


def test_install_plan_uses_one_pack_command_for_the_whole_collection():
    result = run_setup(
        "install-plan",
        "--catalog",
        str(CATALOG),
        "--pack-url",
        "https://skills.sh/p/rhdh-complete-test",
        "--agent",
        "codex",
        "--scope",
        "global",
        "--json",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    plan = json.loads(result.stdout)
    assert set(plan) == {"summary", "operations"}
    assert len(plan["operations"]) == 1

    operation = plan["operations"][0]
    assert set(operation) == {"order", "target", "command", "preview", "installs", "onFailure"}
    assert operation["order"] == 1
    assert operation["target"] == "global:codex"
    assert operation["command"] == [
        "npx",
        "skills",
        "add",
        "https://skills.sh/p/rhdh-complete-test",
        "--agent",
        "codex",
        "--global",
        "--yes",
    ]
    assert operation["installs"] == every_packaged_skill(read_catalog())
    assert operation["preview"].strip()
    assert operation["onFailure"].strip()


def test_install_plan_fallback_installs_the_whole_pack_from_the_repo():
    result = run_setup(
        "install-plan",
        "--catalog",
        str(CATALOG),
        "--agent",
        "codex",
        "--scope",
        "project",
        "--json",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    operations = json.loads(result.stdout)["operations"]
    assert [operation["command"][3] for operation in operations] == [
        "redhat-developer/rhdh-skills",
    ]
    assert operations[0]["command"][4:6] == ["--skill", "*"]
    assert "prose-editing" in operations[0]["installs"]


def test_apply_runs_nothing_until_the_stated_plan_is_confirmed(monkeypatch):
    setup = load_setup_module()
    plan = setup.install_plan(read_catalog(), "codex", "project", "https://skills.sh/p/test")
    calls = []
    monkeypatch.setattr(
        setup.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    result, returncode = setup.apply_plan(plan, confirmed=False)

    assert returncode == 1
    assert result["errors"][0]["code"] == "NOT_CONFIRMED"
    assert calls == []


def test_apply_validates_every_operation_before_executing_any(monkeypatch):
    setup = load_setup_module()
    plan = {
        "summary": "Install skills",
        "operations": [
            {
                "order": 1,
                "target": "project:codex",
                "command": ["npx", "skills", "add", "example/skills"],
                "preview": "Install example skills",
                "installs": ["example"],
                "onFailure": "Stop and report.",
            },
            {
                "order": 2,
                "target": "project:codex",
                "command": ["powershell", "Invoke-Anything"],
                "preview": "Run something else entirely",
                "installs": [],
                "onFailure": "Stop and report.",
            },
        ],
    }
    calls = []
    monkeypatch.setattr(
        setup.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    result, returncode = setup.apply_plan(plan, confirmed=True)

    assert returncode == 1
    assert result["errors"][0]["code"] == "OPERATION_NOT_ALLOWED"
    assert calls == []


def test_windows_npx_wrapper_resolves_to_node_without_a_shell(tmp_path, monkeypatch):
    setup = load_setup_module()
    node_dir = tmp_path / "nodejs"
    cli = node_dir / "node_modules" / "npm" / "bin" / "npx-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    npx = node_dir / "npx.cmd"
    npx.write_text("", encoding="utf-8")
    node = node_dir / "node.exe"
    node.write_text("", encoding="utf-8")

    monkeypatch.setattr(setup.sys, "platform", "win32")

    def fake_which(name):
        if name in {"npx", "npx.cmd"}:
            return str(npx)
        if name in {"node", "node.exe"}:
            return str(node)
        return None

    monkeypatch.setattr(setup.shutil, "which", fake_which)

    command = setup._resolve_npx_command(["npx", "skills", "add", "example/skills"])

    assert command == [
        str(node),
        str(cli),
        "skills",
        "add",
        "example/skills",
    ]


def test_apply_executes_argument_arrays_without_a_command_shell(monkeypatch):
    setup = load_setup_module()
    plan = setup.install_plan(
        read_catalog(),
        agent="codex",
        scope="project",
        pack_url="https://skills.sh/p/rhdh-complete-test",
    )
    calls = []

    monkeypatch.setattr(
        setup,
        "_resolve_npx_command",
        lambda argv: ["node", "npx-cli.js", *argv[1:]],
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="installed", stderr="")

    monkeypatch.setattr(setup.subprocess, "run", fake_run)

    report, returncode = setup.apply_plan(plan, confirmed=True)

    assert returncode == 0
    assert report["valid"] is True
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        "node",
        "npx-cli.js",
        "skills",
        "add",
        "https://skills.sh/p/rhdh-complete-test",
        "--agent",
        "codex",
        "--yes",
    ]
    assert kwargs["shell"] is False
    assert report["outcomes"] == [
        {
            "order": 1,
            "target": "project:codex",
            "preview": plan["operations"][0]["preview"],
            "status": "completed",
            "returnCode": 0,
            "stdout": "installed",
            "stderr": "",
        }
    ]


def test_apply_reports_an_outcome_for_every_operation_including_skipped_ones(monkeypatch):
    setup = load_setup_module()
    plan = setup.install_plan(read_catalog(), agent="codex", scope="project", pack_url=None)
    assert len(plan["operations"]) == 1

    monkeypatch.setattr(
        setup,
        "_resolve_npx_command",
        lambda argv: ["node", "npx-cli.js", *argv[1:]],
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="network unreachable")

    monkeypatch.setattr(setup.subprocess, "run", fake_run)

    report, returncode = setup.apply_plan(plan, confirmed=True)

    assert returncode == 1
    assert report["valid"] is False
    assert [outcome["order"] for outcome in report["outcomes"]] == [1]
    assert [outcome["status"] for outcome in report["outcomes"]] == [
        "failed",
    ]
    assert report["outcomes"][0]["stderr"] == "network unreachable"
