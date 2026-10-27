"""The write gate refuses to preview or log credential-shaped content.

The credential scanner is the only automated protection against a token
reaching a plan preview, a transcript, or a log, so it ships as the mutation
gate's own script.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
SCRIPT = PROJECT_ROOT / "skills" / "reference" / "mutation-gate" / "scripts" / "scan_credentials.py"


def run_scan(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def scan_payload(tmp_path: Path, payload: object) -> tuple[int, dict]:
    target = tmp_path / "plan.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    result = run_scan(str(target), "--json")
    return result.returncode, json.loads(result.stdout)


def plan(**overrides: object) -> dict:
    """A minimal stated write, in the shape the gate presents to the user."""
    operation = {
        "target": "redhat-developer/rhdh-skills#1",
        "command": "gh pr comment 1 --body 'ok'",
        "preview": {"commandOrRequest": {"body": "ok"}},
    }
    operation.update(overrides)
    return {"summary": "comment on one pull request", "operations": [operation]}


@pytest.mark.parametrize(
    "prose",
    [
        "basic auth is required",
        "a basic example of the bearer flow",
        "basic block layout",
        "basic auth-token setup notes",
    ],
)
def test_prose_that_merely_mentions_basic_or_bearer_is_clean(tmp_path, prose):
    payload = plan()
    payload["operations"][0]["preview"]["commandOrRequest"]["body"] = prose

    returncode, report = scan_payload(tmp_path, payload)

    assert returncode == 0, report
    assert report["clean"] is True


@pytest.mark.parametrize(
    "secret",
    [
        # PEM headers only, no key material: these assert the scanner rejects them.
        "-----BEGIN OPENSSH PRIVATE KEY-----",  # gitleaks:allow
        "-----BEGIN EC PRIVATE KEY-----",  # gitleaks:allow
        "-----BEGIN PGP PRIVATE KEY BLOCK-----",  # gitleaks:allow
        "Authorization: Bearer abc123",
        "Bearer eyJhbGciOi.J9x_1",
    ],
)
def test_private_keys_and_authorization_headers_are_rejected(tmp_path, secret):
    payload = plan()
    payload["operations"][0]["preview"]["commandOrRequest"]["body"] = secret

    returncode, report = scan_payload(tmp_path, payload)

    assert returncode == 1
    assert report["errors"][0]["code"] == "CREDENTIAL_VALUE"
    assert "contains credential-shaped content:" in report["errors"][0]["message"]


def test_a_credential_field_is_found_at_any_depth(tmp_path):
    payload = plan(token="should-never-be-previewed")

    returncode, report = scan_payload(tmp_path, payload)

    assert returncode == 1
    assert report["errors"] == [
        {
            "code": "CREDENTIAL_FIELD",
            "message": "operations[0].token is not allowed in a mutation preview",
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("privateKey", "private material", "CREDENTIAL_FIELD"),
        ("auth", "email:token", "CREDENTIAL_FIELD"),
        ("credential", "email:token", "CREDENTIAL_FIELD"),
        ("headers", ["Authorization: Bearer abc123"], "CREDENTIAL_VALUE"),
        ("X-Api-Key", "gh" + "p_this_is_a_secret_value", "CREDENTIAL_FIELD"),
        ("githubTokenValue", "opaque-secret-value", "CREDENTIAL_FIELD"),
    ],
)
def test_common_credential_shapes_are_rejected(tmp_path, field, value, code):
    payload = plan()
    payload[field] = value

    returncode, report = scan_payload(tmp_path, payload)

    assert returncode == 1
    assert report["errors"][0]["code"] == code


def test_a_compound_api_key_header_is_named_by_its_full_path(tmp_path):
    payload = plan()
    payload["operations"][0]["preview"]["headers"] = {
        "X-Api-Key": "gh" + "p_this_is_a_secret_value"
    }

    returncode, report = scan_payload(tmp_path, payload)

    assert returncode == 1
    assert report["errors"][0] == {
        "code": "CREDENTIAL_FIELD",
        "message": ("operations[0].preview.headers.X-Api-Key is not allowed in a mutation preview"),
    }


@pytest.mark.parametrize(
    "secret_data",
    [
        {"api": {"key": "opaque-value"}},
        {"value": "gh" + "p_this_is_a_secret_value"},
    ],
)
def test_credentials_split_across_paths_or_opaque_values_are_rejected(tmp_path, secret_data):
    payload = plan()
    payload["operations"][0]["preview"]["request"] = secret_data

    returncode, report = scan_payload(tmp_path, payload)

    assert returncode == 1
    assert report["errors"][0]["code"] in {"CREDENTIAL_FIELD", "CREDENTIAL_VALUE"}


def test_a_single_string_can_be_scanned_without_json(tmp_path):
    assert run_scan("--text", "a basic example", "--json").returncode == 0
    assert run_scan("--text", "Authorization: Bearer abc123", "--json").returncode == 1
