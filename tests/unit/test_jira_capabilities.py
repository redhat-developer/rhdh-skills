"""Behavior tests for Jira capability adapters."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
JIRA_SCRIPTS = PROJECT_ROOT / "skills" / "reference" / "rhdh-jira-api" / "scripts"


def load_script(name: str):
    path = JIRA_SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"jira_{path.stem}_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_detects_native_acli_without_inspecting_credentials(monkeypatch, capsys):
    setup = load_script("setup.py")
    monkeypatch.setattr(setup, "find_acli", lambda: "/tools/acli")
    monkeypatch.setattr(setup, "smoke_test", lambda _path: (True, "connected"))

    with pytest.raises(SystemExit) as exc:
        setup.main(["--json", "--quick"])

    assert exc.value.code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["adapters"] == ["acli"]
    assert result["connectivity"] is True
    assert result["token_file_found"] is False
    assert result["token_file_status"] == "not found"
    blob = json.dumps(result)
    assert not any(
        word in key.lower() for key in result for word in ("credential", "password", "secret")
    )
    assert "email:token" not in blob
    assert "@redhat.com" not in blob


def test_check_token_file_reports_status_without_printing_contents(tmp_path, monkeypatch):
    setup = load_script("setup.py")
    monkeypatch.delenv("JIRA_TOKEN_FILE", raising=False)
    token = tmp_path / ".jira-token"
    token.write_text("user@example.com:super-secret-token\n", encoding="utf-8")
    token.chmod(0o600)
    fake_acli = tmp_path / "acli"
    fake_acli.write_text("", encoding="utf-8")

    path, status, warnings = setup.check_token_file(str(fake_acli))
    assert path == str(token)
    assert status == "valid"
    assert warnings == []

    bare = tmp_path / "bare" / ".jira-token"
    bare.parent.mkdir()
    bare.write_text("only-a-token\n", encoding="utf-8")
    monkeypatch.setenv("JIRA_TOKEN_FILE", str(bare))
    path, status, _warnings = setup.check_token_file(str(fake_acli))
    assert path == str(bare)
    assert "email" in status


def test_greenhopper_get_uses_token_file_and_omits_it_from_output(monkeypatch, capsys, tmp_path):
    gh = load_script("greenhopper.py")
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    token = tmp_path / ".jira-token"
    secret = "agent@example.com:never-print-me"
    token.write_text(secret + "\n", encoding="utf-8")
    monkeypatch.setenv("JIRA_TOKEN_FILE", str(token))
    captured = {}

    class FakeResponse:
        def read(self):
            return json.dumps(
                {"contents": {"completedIssues": [], "issueKeysAddedDuringSprint": {}}}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def fake_urlopen(request, timeout=60):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        return FakeResponse()

    monkeypatch.setattr(gh.urllib.request, "urlopen", fake_urlopen)
    assert gh.main(["sprintreport", "--board", "11374", "--sprint", "68649"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["report"]["contents"]["completedIssues"] == []
    assert secret not in out
    assert "never-print-me" not in out
    assert captured["url"].endswith(
        "/rest/greenhopper/1.0/rapid/charts/sprintreport?rapidViewId=11374&sprintId=68649"
    )
    assert captured["auth"].startswith("Basic ")
    assert secret not in json.dumps(payload)


def test_greenhopper_missing_token_skips_without_secret(monkeypatch, capsys):
    gh = load_script("greenhopper.py")
    monkeypatch.setattr(gh, "find_token_file", lambda _acli=None: None)
    with pytest.raises(SystemExit) as exited:
        gh.main(["--board", "1", "--sprint", "2"])
    assert exited.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "skip Greenhopper" in payload["error"]


def test_greenhopper_http_error_is_status_only(monkeypatch, capsys, tmp_path):
    gh = load_script("greenhopper.py")
    token = tmp_path / ".jira-token"
    token.write_text("user@example.com:secret\n", encoding="utf-8")
    monkeypatch.setenv("JIRA_TOKEN_FILE", str(token))

    def fake_urlopen(_request, timeout=60):
        raise gh.urllib.error.HTTPError(
            "https://example.invalid/sprintreport", 404, "Not Found", hdrs=None, fp=None
        )

    monkeypatch.setattr(gh.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit):
        gh.main(["--board", "11374", "--sprint", "68649"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == 404
    assert "secret" not in json.dumps(payload)


def test_component_validation_reads_project_data_through_acli(monkeypatch):
    validator = load_script("validate_components.py")
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"components": [{"name": "Catalog"}, {"name": "Build"}]}),
            "",
        )

    monkeypatch.setattr(validator.subprocess, "run", fake_run)

    assert validator.fetch_components("/tools/acli", "RHIDP") == ["Build", "Catalog"]
    assert calls == [["/tools/acli", "jira", "project", "view", "--key", "RHIDP", "--json"]]
