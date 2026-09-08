"""Behavior tests for the OpenShift CI Gangway adapter."""

from __future__ import annotations

import importlib.util
import io
import json
import shlex
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "skills" / "ci" / "rhdh-prow-trigger" / "scripts" / "trigger_nightly_job.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("trigger_nightly_job", SCRIPT)
assert SPEC and SPEC.loader
NIGHTLY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NIGHTLY)
ADAPTER = sys.modules["gangway_adapter"]
JOB = "periodic-ci-redhat-developer-rhdh-release-1.10-e2e-ocp-helm-nightly"
OVERLAY_JOB = "periodic-ci-redhat-developer-rhdh-plugin-export-overlays-main-e2e-ocp-helm-nightly"


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Every test must opt in to simulated network and native CLI responses."""

    def unexpected_io(*_args, **_kwargs):
        pytest.fail("Unexpected network or credential access")

    monkeypatch.setattr(NIGHTLY.urllib.request, "urlopen", unexpected_io)
    monkeypatch.setattr(NIGHTLY.subprocess, "run", unexpected_io)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture
def live_cli(monkeypatch):
    monkeypatch.setattr(NIGHTLY, "ensure_capability", lambda _path: None)
    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", lambda _repo: [JOB, OVERLAY_JOB])


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(ADAPTER.GangwayAdapter, "_token", lambda _self: "test-token")
    return ADAPTER.GangwayAdapter("ci-kubeconfig")


def test_existing_native_cli_session_is_consumed_without_login(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        if argv[-1] == "--show-server":
            return SimpleNamespace(returncode=0, stdout=NIGHTLY.CI_SERVER)
        if argv[-1] == "whoami":
            return SimpleNamespace(returncode=0, stdout="developer")
        raise AssertionError(argv)

    monkeypatch.setattr(NIGHTLY.shutil, "which", lambda _name: "oc")
    monkeypatch.setattr(NIGHTLY.subprocess, "run", fake_run)

    assert NIGHTLY.ensure_capability("ci-kubeconfig") is None
    assert all("login" not in argv for argv in calls)
    assert all("-t" not in argv for argv in calls)


def test_missing_session_routes_to_human_setup_without_login(monkeypatch, capsys):
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(NIGHTLY.shutil, "which", lambda _name: "oc")
    monkeypatch.setattr(NIGHTLY.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        NIGHTLY.ensure_capability("ci-kubeconfig")

    assert "/setup-rhdh-skills openshift-ci" in capsys.readouterr().err
    assert all("login" not in argv for argv in calls)


def test_dry_run_is_an_offline_preview_with_a_replayable_command(tmp_path, capsys):
    NIGHTLY.main(
        [
            "--job",
            JOB,
            "--tag",
            "1.10-171",
            "--catalog-index-image",
            "registry.access.redhat.com/rhdh/plugin-catalog-index:1.10.4-1788447603",
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    preview = json.loads(output.split("\n", 1)[1])
    assert preview["operation"] == "gangway.execution.create"
    assert preview["target"] == NIGHTLY.GANGWAY_URL
    assert preview["payload"] == {
        "job_name": JOB,
        "job_execution_type": "1",
        "pod_spec_options": {
            "envs": {
                "MULTISTAGE_PARAM_OVERRIDE_TAG_NAME": "1.10-171",
                "MULTISTAGE_PARAM_OVERRIDE_CATALOG_INDEX_IMAGE": "registry.access.redhat.com/rhdh/plugin-catalog-index:1.10.4-1788447603",
                "MULTISTAGE_PARAM_OVERRIDE_SKIP_SEND_ALERT": "true",
            }
        },
    }
    command = shlex.split(preview["execution_command"])
    assert command[:3] == ["uv", "run", str(SCRIPT)]
    replay = NIGHTLY.parse_args(command[3:])
    assert not replay.dry_run
    assert NIGHTLY.build_payload(replay) == preview["payload"]
    assert {"validation", "impact", "abort", "failure_behavior", "verification"} <= preview.keys()
    assert "--status" in preview["verification"]
    assert "Bearer" not in output
    assert "whoami -t" not in output
    assert not (tmp_path / "config").exists()


def test_preview_command_preserves_quoted_values_and_boolean_flags(capsys):
    NIGHTLY.main(["-j", JOB, "--branch", "literal $value `text` 'quoted'", "-Sn"])
    preview = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    replay = NIGHTLY.parse_args(shlex.split(preview["execution_command"])[3:])
    assert replay.branch == "literal $value `text` 'quoted'"
    assert replay.send_alerts
    assert not replay.dry_run
    assert NIGHTLY.build_payload(replay) == preview["payload"]


@pytest.mark.parametrize(
    "job",
    [
        "",
        "periodic-ci-openshift-release-main-e2e-nightly",
        "periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm",
        "periodic-ci-redhat-developer-rhdh--nightly",
        JOB + "\n",
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_unsupported_job_names_fail_offline(job, dry_run):
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--job", job, *(["--dry-run"] if dry_run else [])])
    assert error.value.code != 0


@pytest.mark.parametrize(
    "extra",
    [
        ["--job", JOB],
        ["--dry-run"],
        ["--tag", "1.10-171"],
        ["--send-alerts"],
        ["--list"],
        ["--list-tags"],
    ],
)
def test_status_rejects_conflicting_actions_and_overrides(extra):
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--status", "execution-123", *extra])
    assert error.value.code != 0


@pytest.mark.parametrize("job_id", ["", "../executions", "id?job_name=other", "https://prow/id"])
def test_status_rejects_paths_and_urls(job_id):
    with pytest.raises(SystemExit):
        NIGHTLY.main(["--status", job_id])


@pytest.mark.parametrize("jobs", [[], [JOB + "-other"]])
def test_unverifiable_or_unknown_job_stops_before_authentication(monkeypatch, jobs):
    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", lambda _repo: jobs)
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--job", JOB])
    assert error.value.code == 1


@pytest.mark.parametrize(
    "job,repo",
    [
        (JOB, "redhat-developer/rhdh"),
        (OVERLAY_JOB, "redhat-developer/rhdh-plugin-export-overlays"),
    ],
)
def test_live_submission_verifies_owning_repo_and_submits_once(monkeypatch, live_cli, job, repo):
    lookups, submissions = [], []

    def configured_jobs(requested_repo):
        lookups.append(requested_repo)
        return [job]

    def trigger(payload):
        assert lookups == [repo]
        submissions.append(payload)
        return {"id": "execution-123"}

    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", configured_jobs)
    monkeypatch.setattr(
        NIGHTLY,
        "GangwayAdapter",
        lambda _path: SimpleNamespace(
            trigger=trigger,
            status=lambda _id: {"job_url": "https://prow.example/run"},
        ),
    )
    NIGHTLY.main(["--job", job])
    assert [payload["job_name"] for payload in submissions] == [job]


def test_printed_refresh_command_only_reads_existing_execution(monkeypatch, live_cli, capsys):
    reads = []
    fake_adapter = SimpleNamespace(
        status=lambda job_id: (
            reads.append(job_id)
            or {
                "id": job_id,
                "job_status": "PENDING",
                "job_url": "https://prow.example/run",
            }
        )
    )
    NIGHTLY.poll_job_status(fake_adapter, "execution-123")
    output = capsys.readouterr().err
    command = next(line.split(": ", 1)[1] for line in output.splitlines() if "uv run" in line)
    monkeypatch.setattr(NIGHTLY, "GangwayAdapter", lambda _path: fake_adapter)
    NIGHTLY.main(shlex.split(command)[3:])
    assert reads == ["execution-123", "execution-123"]
    assert json.loads(capsys.readouterr().out)["job_status"] == "PENDING"


def test_polling_failure_keeps_submitted_id_and_safe_refresh(monkeypatch, capsys):
    def status(_job_id):
        raise ADAPTER.GangwayAdapterError("HTTP 401: /setup-rhdh-skills openshift-ci")

    NIGHTLY.poll_job_status(SimpleNamespace(status=status), "execution-123")
    output = capsys.readouterr().err
    assert "execution-123" in output
    assert "--status execution-123" in output
    assert "/setup-rhdh-skills openshift-ci" in output


def test_adapter_status_uses_get_without_a_request_body(monkeypatch, adapter):
    def urlopen(request, **_kwargs):
        assert request.method == "GET"
        assert request.full_url == f"{ADAPTER.GANGWAY_URL}/execution-123"
        assert request.data is None
        assert request.get_header("Authorization") == "Bearer test-token"
        return io.BytesIO(b'{"id":"execution-123"}')

    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", urlopen)
    assert adapter.status("execution-123") == {"id": "execution-123"}


@pytest.mark.parametrize(
    "status,uncertain",
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (408, True),
        (429, False),
        (503, True),
    ],
)
def test_http_errors_are_actionable_and_do_not_expose_response_data(
    monkeypatch,
    adapter,
    status,
    uncertain,
):
    def urlopen(request, **_kwargs):
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "test-token",
            {"X-Secret": "test-token"},
            io.BytesIO(b"test-token"),
        )

    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", urlopen)
    with pytest.raises(ADAPTER.GangwayAdapterError) as error:
        adapter.trigger({"job_name": JOB})
    assert f"HTTP {status}" in str(error.value)
    assert ("/setup-rhdh-skills openshift-ci" in str(error.value)) is (status == 401)
    assert error.value.outcome_unknown is uncertain
    assert "test-token" not in str(error.value)


@pytest.mark.parametrize(
    "failure", [urllib.error.URLError("test-token"), TimeoutError("test-token")]
)
def test_network_failures_do_not_retry_or_claim_job_rejection(
    monkeypatch, adapter, capsys, failure
):
    requests = []

    def urlopen(request, **_kwargs):
        requests.append(request)
        raise failure

    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", urlopen)
    with pytest.raises(SystemExit):
        NIGHTLY.trigger_job(adapter, {"job_name": JOB})
    assert len(requests) == 1
    output = capsys.readouterr().err
    assert f"?job={JOB}" in output
    assert "test-token" not in output


@pytest.mark.parametrize("body", [b"test-token", b"[]", b"\xff"])
def test_unreadable_submission_responses_have_unknown_outcome(monkeypatch, adapter, body):
    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", lambda *_a, **_kw: io.BytesIO(body))
    with pytest.raises(ADAPTER.GangwayAdapterError) as error:
        adapter.trigger({"job_name": JOB})
    assert error.value.outcome_unknown
    assert "test-token" not in str(error.value)


def test_credential_retrieval_failure_routes_to_setup(monkeypatch):
    monkeypatch.setattr(
        ADAPTER.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=1,
            stdout="test-token",
            stderr="test-token",
        ),
    )
    with pytest.raises(ADAPTER.GangwayAdapterError) as error:
        ADAPTER.GangwayAdapter("ci-kubeconfig").trigger({"job_name": JOB})
    assert "/setup-rhdh-skills openshift-ci" in str(error.value)
    assert not error.value.outcome_unknown
    assert "test-token" not in str(error.value)
