"""Stable composition and CI-skill contracts for prose that leaves a workflow."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import git_env

ROOT = Path(__file__).resolve().parents[2]
LINTER = ROOT / "skills/reference/prose-editing/scripts/lint.py"
RPA_UPDATER = ROOT / "skills/ci/rhdh-konflux-rpa/scripts/update_rpa_tags.py"
RPA_RELATIVE_DIR = Path("config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhdh")
RPA_FILENAMES = (
    "rhdh-1-9-prod.yaml",
    "rhdh-1-9-stage.yaml",
    "rhdh-plugin-catalog-1-9-prod.yaml",
    "rhdh-plugin-catalog-1-9-stage.yaml",
)

STATIC_TEMPLATE_MANUAL_CHECKS = {
    "claim_preservation": "The fixed template is the source; substitutions are identifiers.",
    "voice_fidelity": "Automation templates have no supplied personal voice.",
    "terminology_consistency": "RHDH and RPM/RPA terms are fixed by their workflows.",
    "word_meaning_consistency": "The templates contain no ambiguous synonym swaps.",
    "active_subject_context": "Each action names the automation or changed artifact.",
    "one_instruction_per_sentence": "The templates report work; they give no instructions.",
    "article_use": "A maintainer reviewed article use in the fixed text.",
    "abbreviation_definition": "Titles use repository-standard RPM/RPA terminology.",
    "paragraph_focus": "Each short paragraph has one reporting purpose.",
    "safety_labels": "The templates contain no warning or safety procedure.",
    "heading_restatement": "The What/Why headings separate payload fields.",
    "hollow_paragraph": "Every paragraph names a change or release purpose.",
    "quotation_ownership": "The templates quote no person or external source.",
    "objection_context": "The templates make no objection or rebuttal.",
    "alternative_relevance": "The templates compare no alternatives.",
    "american_spelling": "The fixed templates use repository-standard US spelling.",
    "condition_before_command": "The templates contain no conditional commands.",
}


def _path(relative: str) -> Path:
    return ROOT / relative


def _text(relative: str) -> str:
    return _path(relative).read_text(encoding="utf-8")


def _named_skill_contexts(relative: str, name: str = "/prose-editing") -> list[str]:
    text = _text(relative)
    return [
        text[match.start() : match.start() + 240] for match in re.finditer(re.escape(name), text)
    ]


def _frontmatter(relative: str) -> str:
    parts = _text(relative).split("---", 2)
    assert len(parts) == 3
    return parts[1]


def _linter_module(name: str):
    spec = importlib.util.spec_from_file_location(name, LINTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rpa_updater_module(name: str):
    spec = importlib.util.spec_from_file_location(name, RPA_UPDATER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_rpa_repo(
    tmp_path: Path,
    content: str = 'tags: ["1.9", "1.9.6"]\n',
    remote: str = "https://gitlab.cee.redhat.com/releng/konflux-release-data.git",
) -> tuple[Path, Path]:
    repo = tmp_path / "konflux-release-data"
    rpa_dir = repo / RPA_RELATIVE_DIR
    rpa_dir.mkdir(parents=True)
    for name in RPA_FILENAMES:
        (rpa_dir / name).write_text(content, encoding="utf-8")

    env = git_env()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
        env=env,
    )
    return repo, rpa_dir


def _commit_fixture(repo: Path, message: str) -> None:
    env = git_env()
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            message,
        ],
        check=True,
        env=env,
    )


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")


def _run_rpa(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script.resolve()), "1.9.7", "--repo-dir", str(repo.resolve()), *args],
        check=False,
        capture_output=True,
        text=True,
        env=git_env(),
    )


def _assert_static_template(report: dict[str, object]) -> None:
    assert report["total"] == 0
    markers = report["markers"]
    assert isinstance(markers, dict)
    assert set(markers.values()) == {0}
    assert set(report["manual_checks"]) == set(STATIC_TEMPLATE_MANUAL_CHECKS)
    assert all(STATIC_TEMPLATE_MANUAL_CHECKS.values())


@pytest.mark.parametrize(
    ("relative", "register", "expected_calls"),
    [
        ("skills/plugins/rhdh-pr-review/workflows/review-code.md", "flavored", 1),
        ("skills/plugins/rhdh-operator-pr-test/workflows/test-operator-pr.md", "flavored", 1),
        ("skills/jira/rhdh-jira-create/workflows/create-issue.md", "flavored", 2),
        ("skills/jira/rhdh-jira-update/workflows/update-issue.md", "flavored", 1),
        ("skills/jira/rhdh-jira-refine/workflows/refine-issues.md", "flavored", 1),
        ("skills/release/rhdh-release-announce/workflows/freeze-announcement.md", "voiced", 1),
        ("skills/release/rhdh-release-sos/workflows/sos-report.md", "flavored", 0),
        ("skills/release/rhdh-test-plan-review/workflows/review-test-plan.md", "flavored", 1),
        ("skills/plugins/rhdh-pr-create/workflows/create-pull-request.md", "flavored", 1),
        ("skills/jira/rhdh-jira-link/SKILL.md", "flavored", 1),
        ("skills/plugins/rhdh-overlay/workflows/draft-notification.md", "voiced", 1),
        ("skills/plugins/rhdh-overlay/workflows/onboard-plugin.md", "flavored", 2),
        ("skills/plugins/rhdh-overlay/workflows/update-plugin.md", "flavored", 2),
        ("skills/plugins/rhdh-plugin-bug-fix/workflows/fix-bug.md", "flavored", 1),
        ("skills/plugins/rhdh-plugin-midstream-propagate/SKILL.md", "flavored", 1),
        ("skills/ci/rhdh-prow-release-branch/workflows/commission-release.md", "flavored", 1),
        ("skills/ci/rhdh-prow-release-branch/workflows/decommission-release.md", "flavored", 1),
    ],
)
def test_final_composers_name_one_register_per_artifact(
    relative: str, register: str, expected_calls: int
) -> None:
    calls = [
        call
        for call in _named_skill_contexts(relative)
        if re.search(rf"\b{register}\b", call, re.IGNORECASE)
    ]
    assert len(calls) == expected_calls


def test_shared_caller_policy_lives_at_final_composers() -> None:
    assert "/prose-editing" not in _text("skills/plugins/rhdh-pr-review/SKILL.md")
    assert "/prose-editing" not in _text("skills/release/rhdh-release-announce/SKILL.md")


def test_jira_authoring_edits_direct_handback_but_not_caller_handoff() -> None:
    text = _text("skills/reference/rhdh-jira-authoring/SKILL.md")
    calls = _named_skill_contexts("skills/reference/rhdh-jira-authoring/SKILL.md")
    assert len(calls) == 1
    assert re.search(r"\bflavored\b", calls[0], re.IGNORECASE)
    assert "/rhdh-jira-create" in text
    assert "/rhdh-jira-refine" in text


def test_jira_update_preserves_a_caller_finalized_comment() -> None:
    producer = _text("skills/release/rhdh-test-plan-review/workflows/review-test-plan.md")
    transport = _text("skills/jira/rhdh-jira-update/workflows/update-issue.md")

    assert "caller-finalized" in producer
    assert "caller-finalized" in transport
    assert transport.count("/prose-editing") == 1


def test_jira_refine_finalizes_comment_bodies_before_one_write_gate() -> None:
    workflow = _text("skills/jira/rhdh-jira-refine/workflows/refine-issues.md")

    assert workflow.count("/prose-editing") == 1
    assert workflow.count("/mutation-gate") == 1
    assert workflow.index("/prose-editing") < workflow.index("/mutation-gate")


def test_transport_layers_do_not_reedit_prose() -> None:
    for relative in (
        "skills/plugins/rhdh-pr-review/workflows/post-to-github.md",
        "skills/jira/rhdh-jira-link/scripts/create-pr-mr.js",
        "skills/jira/rhdh-jira-link/scripts/link-pr-mr.js",
        "skills/ci/rhdh-base-images/scripts/base-images-and-rpms.sh",
        "skills/ci/rhdh-konflux-rpa/scripts/update_rpa_tags.py",
    ):
        assert "/prose-editing" not in _text(relative)


def test_prow_uses_forge_payload_and_mutation_gate() -> None:
    skill = _text("skills/ci/rhdh-prow-release-branch/SKILL.md")
    assert "gh" in skill.partition("compatibility:")[2].partition("---")[0]
    assert not re.search(r"\bgh\s+auth\s+status\b", skill)
    assert "git remote get-url" not in skill
    gate_contexts = _named_skill_contexts(
        "skills/ci/rhdh-prow-release-branch/SKILL.md", "/mutation-gate"
    )
    assert len(gate_contexts) == 1
    assert "make update" not in gate_contexts[0]
    assert not re.search(
        r"(?:copy|edit|delet|make update)[^.]{0,160}/mutation-gate",
        skill,
        re.IGNORECASE,
    )
    assert all(
        operation in gate_contexts[0].casefold() for operation in ("commit", "push", "pull request")
    )
    for workflow in ("commission-release.md", "decommission-release.md"):
        text = _text(f"skills/ci/rhdh-prow-release-branch/workflows/{workflow}")
        assert text.count("/rhdh-forge") == 1
        assert text.count("/mutation-gate") == 1
        clean = text.index("git status --porcelain --untracked-files=all")
        branch = text.index("git switch -c")
        validate = text.index("git diff --check")
        forge = text.index("/rhdh-forge")
        gate = text.index("/mutation-gate")
        update_positions = [match.start() for match in re.finditer(r"`make update`", text)]
        assert clean < branch < validate < forge < gate
        assert any(branch < update < validate for update in update_positions)
        branch_command = re.search(r'git switch -c\s+"[^"]+"\s+"<base-branch>"', text)
        assert branch_command
        commit = text.index("git commit", gate)
        push = text.index("git push", gate)
        remote_head = text.index("git ls-remote", gate)
        forge_command = text.index("<forge-pr-command>", gate)
        assert commit < push < remote_head < forge_command


def test_overlay_triage_delegates_slack_drafting_without_a_fallback() -> None:
    triage = _text("skills/plugins/rhdh-overlay/workflows/triage-prs.md")
    owner = _text("skills/plugins/rhdh-overlay/workflows/draft-notification.md")

    assert triage.count("workflows/draft-notification.md") == 1
    assert "/prose-editing" not in triage
    assert not re.search(r"\bcompose\s+manually\b", triage, re.IGNORECASE)
    assert not re.search(r"(?m)^Hey\s+@", triage)
    assert owner.count("/prose-editing") == 1


def test_rpa_is_an_independently_installable_skill() -> None:
    task_skill = _text("skills/ci/rhdh-konflux-tasks/SKILL.md")
    assert "konflux-rpa" not in task_skill.lower()
    assert "ReleasePlanAdmission" not in task_skill
    assert not _path("skills/ci/rhdh-konflux-tasks/workflows/konflux-rpa-update.md").exists()
    assert not _path("skills/ci/rhdh-konflux-tasks/scripts/update-rpa-tags.sh").exists()

    rpa = _text("skills/ci/rhdh-konflux-rpa/SKILL.md")
    rpa_frontmatter = _frontmatter("skills/ci/rhdh-konflux-rpa/SKILL.md")
    interface = _text("skills/ci/rhdh-konflux-rpa/agents/openai.yaml")
    workflow = _text("skills/ci/rhdh-konflux-rpa/workflows/update-rpa.md")
    assert re.search(r"^name: rhdh-konflux-rpa$", rpa, re.MULTILINE)
    assert "ReleasePlanAdmission" in rpa_frontmatter
    assert "konflux-release-data" in rpa_frontmatter
    assert "rhdh-konflux-tasks" not in rpa_frontmatter
    compatibility = rpa_frontmatter.casefold()
    assert all(tool in compatibility for tool in ("glab", "python", "git"))
    assert "bash" not in compatibility
    scripts = [
        path for path in _path("skills/ci/rhdh-konflux-rpa/scripts").iterdir() if path.is_file()
    ]
    assert scripts == [RPA_UPDATER]
    assert "interface:" in interface
    forge_positions = [match.start() for match in re.finditer("/rhdh-forge", workflow)]
    gate_positions = [match.start() for match in re.finditer("/mutation-gate", workflow)]
    assert forge_positions and gate_positions
    assert any(forge < gate for forge in forge_positions for gate in gate_positions)
    assert "--dry-run" in workflow
    assert "--local-only" in workflow
    assert not _named_skill_contexts("skills/ci/rhdh-konflux-rpa/workflows/update-rpa.md")

    catalog = json.loads(_text("skills/meta/setup-rhdh-skills/assets/catalog.json"))
    entry = next(item for item in catalog["skills"] if item["name"] == "rhdh-konflux-rpa")
    assert set(entry["requiresSkills"]) == {"mutation-gate", "rhdh-forge"}


def test_rpa_local_only_mode_changes_files_without_publish_transport(tmp_path: Path) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    script = RPA_UPDATER
    dry_run = _run_rpa(script, repo, "--dry-run")
    assert dry_run.returncode == 0, dry_run.stderr
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "diff", "--quiet"], check=False, env=git_env()
        ).returncode
        == 0
    )

    result = _run_rpa(script, repo, "--local-only")
    assert result.returncode == 0, result.stderr
    assert "Local-only update complete" in result.stderr
    assert "1.9.7" in (rpa_dir / "rhdh-1-9-prod.yaml").read_text(encoding="utf-8")
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "diff", "--quiet"], check=False, env=git_env()
        ).returncode
        == 1
    )


def test_rpa_cli_ignores_ambient_git_repository_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_repo, target_rpa = _make_rpa_repo(tmp_path / "target")
    foreign_repo, _ = _make_rpa_repo(tmp_path / "foreign")
    monkeypatch.setenv("GIT_DIR", str(foreign_repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(foreign_repo))
    updater = _rpa_updater_module("rpa_updater_git_environment")

    result = updater.main(["1.9.7", "--repo-dir", str(target_repo), "--dry-run"])
    report = json.loads(capsys.readouterr().out)

    assert result == 0
    assert all(str(target_rpa) in path for path in report["files"])


def test_rpa_replacement_changes_only_literal_tag_values(tmp_path: Path) -> None:
    source = """metadata:
  annotations:
    release-note: "keep 1.9.6 and 1x9x6"
    tags: ["1.9.6"]
spec:
  description: "keep 1.9.6"
  notes: |	# embedded examples are opaque
    tags:
      - "1.9.6"
  tags:
    - "1.9"
    - "1.9.6"
    - '1.9.6''note'
    - '1.9.6'
    - "1.9.6--1.20.2"
    - "1.9.*"
    - "1x9x6"
  nested:
    tags: ["1.9", "1.9.6", '1.9.6''note, keep', '1.9.6', "1.9.6--2.3.4", "1.9.*", "1x9x6"] # keep comment
  scalar:
    tags: '1.9.6--3.4.5' # keep scalar comment
  indentationless:
    tags:
    - "1.9.6"
  tag-mapping:
    tags:
      annotations:
        - "1.9.6"
"""
    expected = """metadata:
  annotations:
    release-note: "keep 1.9.6 and 1x9x6"
    tags: ["1.9.6"]
spec:
  description: "keep 1.9.6"
  notes: |	# embedded examples are opaque
    tags:
      - "1.9.6"
  tags:
    - "1.9"
    - "1.9.7"
    - '1.9.6''note'
    - '1.9.7'
    - "1.9.7--1.20.2"
    - "1.9.*"
    - "1x9x6"
  nested:
    tags: ["1.9", "1.9.7", '1.9.6''note, keep', '1.9.7', "1.9.7--2.3.4", "1.9.*", "1x9x6"] # keep comment
  scalar:
    tags: '1.9.7--3.4.5' # keep scalar comment
  indentationless:
    tags:
    - "1.9.7"
  tag-mapping:
    tags:
      annotations:
        - "1.9.6"
"""
    repo, rpa_dir = _make_rpa_repo(tmp_path, content=source)
    script = RPA_UPDATER

    result = _run_rpa(script, repo, "--local-only")

    assert result.returncode == 0, result.stderr
    for name in RPA_FILENAMES:
        assert (rpa_dir / name).read_text(encoding="utf-8") == expected


@pytest.mark.parametrize(
    "unsupported",
    (
        'tags: ["1.9",\n  "1.9.6"]\n',
        'tags:\n  ["1.9",\n  "1.9.6"]\n',
    ),
)
def test_rpa_rejects_multiline_flow_tags_without_writing_any_file(
    tmp_path: Path, unsupported: str
) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    (rpa_dir / RPA_FILENAMES[-1]).write_text(unsupported, encoding="utf-8")
    _commit_fixture(repo, "unsupported fixture")
    originals = {path: path.read_bytes() for path in rpa_dir.iterdir()}
    script = RPA_UPDATER

    result = _run_rpa(script, repo, "--local-only")

    assert result.returncode != 0
    assert {path: path.read_bytes() for path in rpa_dir.iterdir()} == originals


@pytest.mark.parametrize(
    "unsupported",
    (
        "tags: '1.9.6\n  continued'\n",
        'tags: "1.9.6\n  continued"\n',
        "tags:\n  - '1.9.6\n    continued'\n",
        'tags:\n  - "1.9.6\n    continued"\n',
    ),
)
def test_rpa_rejects_multiline_quoted_tag_values_without_writing_any_file(
    tmp_path: Path, unsupported: str
) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    (rpa_dir / RPA_FILENAMES[-1]).write_text(unsupported, encoding="utf-8")
    _commit_fixture(repo, "unsupported quoted fixture")
    originals = {path: path.read_bytes() for path in rpa_dir.iterdir()}
    script = RPA_UPDATER

    result = _run_rpa(script, repo, "--local-only")

    assert result.returncode != 0
    assert {path: path.read_bytes() for path in rpa_dir.iterdir()} == originals


def test_rpa_rejects_a_symlinked_canonical_directory(tmp_path: Path) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    physical = repo / "physical-rpa"
    rpa_dir.rename(physical)
    _symlink_or_skip(rpa_dir, physical, directory=True)
    script = RPA_UPDATER

    result = _run_rpa(script, repo, "--dry-run")

    assert result.returncode != 0


def test_rpa_rejects_a_symlinked_target_file(tmp_path: Path) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    target = rpa_dir / RPA_FILENAMES[0]
    physical = repo / "outside-rpa.yaml"
    target.rename(physical)
    _symlink_or_skip(target, physical)
    script = RPA_UPDATER

    result = _run_rpa(script, repo, "--dry-run")

    assert result.returncode != 0


def test_rpa_write_restores_all_files_when_a_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    paths = tuple(rpa_dir / name for name in RPA_FILENAMES)
    originals = {path: path.read_bytes() for path in paths}
    original_modes = {path: path.stat().st_mode for path in paths}
    updater = _rpa_updater_module("rpa_updater_atomic_failure")
    real_replace = updater.os.replace
    attempts = 0

    def fail_third_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal attempts
        if Path(destination).name in RPA_FILENAMES:
            attempts += 1
            if attempts == 3:
                raise OSError("injected replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(updater.os, "replace", fail_third_replace)

    result = updater.main(["1.9.7", "--repo-dir", str(repo), "--local-only"])

    assert result == 2
    assert {path: path.read_bytes() for path in paths} == originals
    assert {path: path.stat().st_mode for path in paths} == original_modes
    assert {path.name for path in rpa_dir.iterdir()} == set(RPA_FILENAMES)


def test_rpa_write_restores_all_files_when_replacement_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    paths = tuple(rpa_dir / name for name in RPA_FILENAMES)
    originals = {path: path.read_bytes() for path in paths}
    original_modes = {path: path.stat().st_mode for path in paths}
    updater = _rpa_updater_module("rpa_updater_atomic_interrupt")
    real_replace = updater.os.replace
    attempts = 0

    def interrupt_third_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal attempts
        if Path(destination).name in RPA_FILENAMES:
            attempts += 1
            if attempts == 3:
                raise KeyboardInterrupt
        real_replace(source, destination)

    monkeypatch.setattr(updater.os, "replace", interrupt_third_replace)

    with pytest.raises(KeyboardInterrupt):
        updater.main(["1.9.7", "--repo-dir", str(repo), "--local-only"])

    assert {path: path.read_bytes() for path in paths} == originals
    assert {path: path.stat().st_mode for path in paths} == original_modes
    assert {path.name for path in rpa_dir.iterdir()} == set(RPA_FILENAMES)


def test_rpa_local_edit_rejects_untracked_files(tmp_path: Path) -> None:
    repo, rpa_dir = _make_rpa_repo(tmp_path)
    (repo / "untracked.txt").write_text("keep", encoding="utf-8")
    script = RPA_UPDATER

    result = _run_rpa(script, repo, "--local-only")

    assert result.returncode != 0
    assert "1.9.6" in (rpa_dir / RPA_FILENAMES[0]).read_text(encoding="utf-8")


def test_rpa_local_edit_requires_the_upstream_repository(tmp_path: Path) -> None:
    repo, rpa_dir = _make_rpa_repo(
        tmp_path, remote="https://gitlab.cee.redhat.com/example/konflux-release-data.git"
    )
    script = RPA_UPDATER

    result = _run_rpa(script, repo, "--local-only")

    assert result.returncode != 0
    assert "1.9.6" in (rpa_dir / RPA_FILENAMES[0]).read_text(encoding="utf-8")


def test_rpa_local_edit_requires_the_canonical_rpa_directory(tmp_path: Path) -> None:
    repo, _ = _make_rpa_repo(tmp_path)
    decoy = repo / "decoy"
    decoy.mkdir()
    for name in RPA_FILENAMES:
        (decoy / name).write_text('tags: ["1.9", "1.9.6"]\n', encoding="utf-8")
    script = RPA_UPDATER

    result = _run_rpa(script, decoy, "--dry-run")

    assert result.returncode != 0
    assert "1.9.6" in (decoy / RPA_FILENAMES[0]).read_text(encoding="utf-8")


def test_rpa_script_contains_no_publish_transport() -> None:
    script = RPA_UPDATER.read_text(encoding="utf-8")
    assert "glab" not in script
    for command in ("push", "commit", "fetch"):
        assert not re.search(rf"[\"']{command}[\"']", script)


def test_base_image_automation_pr_payload_passes_static_prose_lint() -> None:
    script = _text("skills/ci/rhdh-base-images/scripts/base-images-and-rpms.sh")
    payload = {field: re.search(rf'--{field}\s+"([^"]+)"', script) for field in ("title", "body")}
    assert all(payload.values()), "expected the fixed automation PR title and body"

    linter = _linter_module("prose_editing_lint_callers")
    for match in payload.values():
        assert match
        rendered = re.sub(r"\$\{[^}]+\}", "release-1.10", match.group(1))
        _assert_static_template(linter.lint(rendered, register="flavored"))


def test_rpa_automation_mr_body_passes_static_prose_lint() -> None:
    template = _text("skills/ci/rhdh-konflux-rpa/references/mr-body.md")
    rendered = re.sub(r"\{[^}]+\}", "VALUE", template)
    report = _linter_module("prose_editing_lint_rpa").lint(rendered, register="flavored")
    _assert_static_template(report)
