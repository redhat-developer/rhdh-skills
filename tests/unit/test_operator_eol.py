"""Contracts and wrapper behavior for /rhdh-operator-eol."""

from __future__ import annotations

import importlib.util
import json
import re
import stat
import subprocess
import sys
from pathlib import Path

from conftest import git_env

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/ci/rhdh-operator-eol/scripts/eol_operator.py"
SKILL = "skills/ci/rhdh-operator-eol/SKILL.md"
WORKFLOW = "skills/ci/rhdh-operator-eol/workflows/eol-release.md"
TEMPLATE = "skills/ci/rhdh-operator-eol/references/pr-body.md"
LINTER = ROOT / "skills/reference/prose-editing/scripts/lint.py"

STUB_SCRIPT = """\
#!/usr/bin/env bash
set -euo pipefail
tag=""
root=""
write=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) tag="$2"; shift 2 ;;
    --root) root="$2"; shift 2 ;;
    --write) write=1; shift ;;
    *) shift ;;
  esac
done
printf '%s\\n' "--tag ${tag} --root ${root} write=${write}" > "${root}/.eol-args"
echo "tag=${tag} eol=release-1.9"
echo "update     .github/workflows/nightly.yaml"
echo "update     .github/workflows/nightly-upgrade-test.yaml"
echo "EOL_BRANCH=release-1.9"
echo "CHANGED=true"
"""

STATIC_TEMPLATE_MANUAL_CHECKS = {
    "claim_preservation": "The fixed template is the source; substitutions are identifiers.",
    "voice_fidelity": "Automation templates have no supplied personal voice.",
    "terminology_consistency": "RHDH and EOL terms are fixed by the workflow.",
    "word_meaning_consistency": "The template contains no ambiguous synonym swaps.",
    "active_subject_context": "Each action names the automation or changed artifact.",
    "one_instruction_per_sentence": "The template reports work; it gives no instructions.",
    "article_use": "A maintainer reviewed article use in the fixed text.",
    "abbreviation_definition": "Titles use repository-standard CI terminology.",
    "paragraph_focus": "Each short paragraph has one reporting purpose.",
    "safety_labels": "The template contains no warning or safety procedure.",
    "heading_restatement": "The What/Why headings separate payload fields.",
    "hollow_paragraph": "Every paragraph names a change or release purpose.",
    "quotation_ownership": "The template quotes no person or external source.",
    "objection_context": "The template makes no objection or rebuttal.",
    "alternative_relevance": "The template compares no alternatives.",
    "american_spelling": "The fixed template uses repository-standard US spelling.",
    "condition_before_command": "The template contains no conditional commands.",
}


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_operator_repo(
    tmp_path: Path, tags: tuple[str, ...] = ("1.8.0", "1.9.0", "1.10.0", "2.1.0")
) -> Path:
    repo = tmp_path / "rhdh-operator"
    (repo / ".github").mkdir(parents=True)
    (repo / "hack").mkdir()
    script = repo / "hack" / "eol-release.sh"
    script.write_text(STUB_SCRIPT, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    env = git_env()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        env=env,
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True, env=env)
    for tag in tags:
        subprocess.run(["git", "-C", str(repo), "tag", tag], check=True, env=env)
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        env=git_env(),
    )


def test_operator_eol_is_an_independently_installable_skill() -> None:
    skill = _text(SKILL)
    frontmatter = skill.split("---", 2)[1]
    workflow = _text(WORKFLOW)
    assert re.search(r"^name: rhdh-operator-eol$", skill, re.MULTILINE)
    assert "hack/eol-release.sh" in frontmatter
    assert "rhdh-operator" in frontmatter
    assert "/rhdh-pr-mr" in skill
    assert "/mutation-gate" in skill
    assert "/rhdh-context" in skill
    assert "/rhdh-pr-mr" in workflow
    assert "/mutation-gate" in workflow
    assert "/rhdh-context" in workflow
    assert "create-github-app-token" not in workflow
    assert "RHDH_BOT_TOKEN" in workflow
    assert "x-access-token" in workflow
    assert "--label lgtm" in workflow
    assert "--json" in workflow
    assert "--write" in workflow
    dry = workflow.index("eol_operator.py")
    write = workflow.index("--write --json")
    gate = workflow.index("/mutation-gate")
    opener = workflow.rindex("/rhdh-pr-mr")
    assert dry < write < gate < opener

    catalog = json.loads(_text("skills/meta/setup-rhdh-skills/assets/catalog.json"))
    entry = next(item for item in catalog["skills"] if item["name"] == "rhdh-operator-eol")
    assert entry["category"] == "ci"
    assert entry["invocation"] == "model"
    assert set(entry["requiresSkills"]) == {"mutation-gate", "rhdh-pr-mr", "rhdh-context"}


def test_wrapper_contains_no_publish_transport() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "git commit" not in source
    assert "git push" not in source
    assert "create-pr-mr" not in source
    assert "create-github-app-token" not in source


def test_branch_resolves_to_the_tag_two_releases_ahead(tmp_path: Path) -> None:
    repo = _make_operator_repo(tmp_path)
    result = _run(repo, "--branch", "release-1.9")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["tag"] == "2.1.0"
    assert payload["eol_branch"] == "release-1.9"
    assert payload["changed"] is True
    assert payload["write"] is False
    assert payload["files"] == [
        ".github/workflows/nightly.yaml",
        ".github/workflows/nightly-upgrade-test.yaml",
    ]
    recorded = (repo / ".eol-args").read_text(encoding="utf-8")
    assert "--tag 2.1.0" in recorded
    assert "write=0" in recorded


def test_bare_version_is_a_release_branch(tmp_path: Path) -> None:
    repo = _make_operator_repo(tmp_path)
    result = _run(repo, "--branch", "1.9")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tag"] == "2.1.0"


def test_tag_is_passed_through(tmp_path: Path) -> None:
    repo = _make_operator_repo(tmp_path)
    result = _run(repo, "--tag", "2.1.0", "--write")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["tag"] == "2.1.0"
    assert payload["write"] is True
    assert "write=1" in (repo / ".eol-args").read_text(encoding="utf-8")


def test_missing_history_fails_before_the_operator_script(tmp_path: Path) -> None:
    repo = _make_operator_repo(tmp_path)
    result = _run(repo, "--branch", "release-2.1")
    assert result.returncode == 2
    assert "not enough release history" in result.stderr
    assert not (repo / ".eol-args").exists()


def test_missing_operator_script_fails(tmp_path: Path) -> None:
    repo = _make_operator_repo(tmp_path)
    (repo / "hack" / "eol-release.sh").unlink()
    result = _run(repo, "--tag", "2.1.0")
    assert result.returncode == 2
    assert "missing" in result.stderr


def test_tag_and_branch_are_mutually_exclusive(tmp_path: Path) -> None:
    repo = _make_operator_repo(tmp_path)
    result = _run(repo, "--tag", "2.1.0", "--branch", "release-1.9")
    assert result.returncode == 2


def test_wrapper_does_not_commit(tmp_path: Path) -> None:
    repo = _make_operator_repo(tmp_path)
    result = _run(repo, "--tag", "2.1.0", "--write")
    assert result.returncode == 0, result.stderr
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        env=git_env(),
    )
    assert ".eol-args" in status.stdout
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"],
        check=True,
        capture_output=True,
        text=True,
        env=git_env(),
    )
    assert log.stdout.strip() == "fixture"


def test_pr_body_passes_static_prose_lint() -> None:
    template = _text(TEMPLATE)
    rendered = re.sub(r"\{[^}]+\}", "VALUE", template)
    report = _load(LINTER, "prose_editing_lint_eol").lint(rendered, register="flavored")
    assert report["total"] == 0
    markers = report["markers"]
    assert isinstance(markers, dict)
    assert set(markers.values()) == {0}
    assert set(report["manual_checks"]) == set(STATIC_TEMPLATE_MANUAL_CHECKS)
