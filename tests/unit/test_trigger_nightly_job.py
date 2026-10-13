"""Behavior tests for the OpenShift CI Gangway adapter."""

from __future__ import annotations

import http.client
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
def sleeps(monkeypatch):
    """Record backoff delays instead of sleeping."""
    delays: list[float] = []
    monkeypatch.setattr(NIGHTLY.time, "sleep", delays.append)
    return delays


@pytest.fixture
def live_cli(monkeypatch):
    """Stub an authenticated session whose configured-jobs pages list both test jobs."""
    monkeypatch.setattr(NIGHTLY, "ensure_capability", lambda _path: None)
    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", lambda _repo: [JOB, OVERLAY_JOB])


def read_preview(capsys) -> dict:
    """Parse the JSON document the dry run prints after its one-line header."""
    return json.loads(capsys.readouterr().out.split("\n", 1)[1])


def fake_adapter(submissions: list, response: dict | None = None):
    """A Gangway adapter that records submissions and reports a ready job URL."""
    return lambda _path: SimpleNamespace(
        trigger=lambda payload: (
            submissions.append(payload)
            or ({"id": "execution-123"} if response is None else response)
        ),
        status=lambda _id: {"job_url": "https://prow.example/run"},
    )


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
    preview = read_preview(capsys)
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
        "periodic-ci-redhat-developer-rhdh-operator-main-e2e-nightly",
        "periodic-ci-redhat-developer-rhdh-feature-x-e2e-ocp-helm-nightly",
        JOB + "\n",
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_unsupported_job_names_fail_offline(job, dry_run):
    assert not NIGHTLY.NIGHTLY_JOB_PATTERN.fullmatch(job)
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--job", job, *(["--dry-run"] if dry_run else [])])
    assert error.value.code == 1


@pytest.mark.parametrize("job", [JOB, OVERLAY_JOB])
def test_supported_job_names_pass_the_offline_pattern(job):
    assert NIGHTLY.NIGHTLY_JOB_PATTERN.fullmatch(job)


@pytest.mark.parametrize(
    "extra",
    [
        ["--dry-run"],
        ["--tag", "1.10-171"],
        ["--send-alerts"],
        ["--tag-filter", "1.10"],
        ["--skip-job-check"],
        ["--json"],
    ],
)
def test_status_rejects_trigger_flags(extra, capsys):
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--status", "execution-123", *extra])
    assert error.value.code == 1
    assert "--status" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--job", JOB], ["--list"], ["--list-tags"]])
def test_status_rejects_other_actions(extra):
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--status", "execution-123", *extra])
    assert error.value.code == 2


@pytest.mark.parametrize("flag", ["--dry-run", "--skip-job-check"])
def test_job_only_flags_require_a_job(monkeypatch, flag):
    monkeypatch.setattr(NIGHTLY, "list_jobs", lambda **_kw: pytest.fail("listed"))
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--list", flag])
    assert error.value.code == 1


def test_trigger_overrides_match_parser_override_flags():
    non_overrides = {
        "help",
        "list_jobs",
        "job",
        "list_tags",
        "status",
        "tag_filter",
        "dry_run",
        "skip_job_check",
        "json_output",
    }
    actions = NIGHTLY.build_parser()._actions
    assert {action.dest for action in actions} - non_overrides == set(NIGHTLY.TRIGGER_OVERRIDES)
    # The dry-run preview rebuilds each override flag from its dest name.
    flags = {flag for action in actions for flag in action.option_strings}
    assert {f"--{name.replace('_', '-')}" for name in NIGHTLY.TRIGGER_OVERRIDES} <= flags


@pytest.mark.parametrize("job_id", ["", "../executions", "id?job_name=other", "https://prow/id"])
def test_status_rejects_paths_and_urls(monkeypatch, job_id):
    monkeypatch.setattr(NIGHTLY, "ensure_capability", lambda _path: pytest.fail("authenticated"))
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--status", job_id])
    assert error.value.code == 1


def test_status_requires_a_session_before_reading(monkeypatch):
    def missing_session(_path):
        raise SystemExit(1)

    monkeypatch.setattr(NIGHTLY, "ensure_capability", missing_session)
    monkeypatch.setattr(NIGHTLY, "GangwayAdapter", lambda _path: pytest.fail("read"))
    with pytest.raises(SystemExit):
        NIGHTLY.main(["--status", "execution-123"])


def test_status_lookup_failure_exits_without_output(capsys):
    def status(_job_id):
        raise ADAPTER.GangwayAdapterError("HTTP 500")

    with pytest.raises(SystemExit) as error:
        NIGHTLY.show_job_status(SimpleNamespace(status=status), "execution-123")
    assert error.value.code == 1
    assert capsys.readouterr().out == ""


def test_status_without_a_url_still_prints_the_execution(capsys):
    NIGHTLY.show_job_status(SimpleNamespace(status=lambda job_id: {"id": job_id}), "execution-123")
    assert json.loads(capsys.readouterr().out) == {"id": "execution-123"}


@pytest.mark.parametrize("jobs,lookups", [([], 3), ([JOB + "-other"], 1)])
def test_unverifiable_or_unknown_job_stops_before_submission(
    monkeypatch, live_cli, sleeps, jobs, lookups
):
    calls = []
    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", lambda repo: calls.append(repo) or jobs)
    monkeypatch.setattr(NIGHTLY, "GangwayAdapter", lambda _path: pytest.fail("submitted"))
    with pytest.raises(SystemExit) as error:
        NIGHTLY.main(["--job", JOB])
    assert error.value.code == 1
    assert len(calls) == lookups
    assert sleeps == [1, 2][: lookups - 1]


def test_configured_job_check_retries_a_transient_empty_page(monkeypatch, sleeps):
    pages = [[], [JOB]]
    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", lambda _repo: pages.pop(0))
    NIGHTLY.ensure_configured_job(JOB)
    assert sleeps == [1]


def test_authentication_is_checked_before_job_discovery(monkeypatch):
    def missing_session(_path):
        raise SystemExit(1)

    monkeypatch.setattr(NIGHTLY, "ensure_capability", missing_session)
    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", lambda _repo: pytest.fail("fetched"))
    with pytest.raises(SystemExit):
        NIGHTLY.main(["--job", JOB])


def test_skip_job_check_submits_without_job_discovery(monkeypatch, live_cli):
    submissions = []
    monkeypatch.setattr(NIGHTLY, "fetch_configured_jobs", lambda _repo: pytest.fail("fetched"))
    monkeypatch.setattr(NIGHTLY, "GangwayAdapter", fake_adapter(submissions))
    NIGHTLY.main(["--job", JOB, "--skip-job-check"])
    assert [payload["job_name"] for payload in submissions] == [JOB]


def test_skip_job_check_is_carried_into_the_preview_command(capsys):
    NIGHTLY.main(["--job", JOB, "--skip-job-check", "--dry-run"])
    preview = read_preview(capsys)
    assert NIGHTLY.parse_args(shlex.split(preview["execution_command"])[3:]).skip_job_check
    assert "--skip-job-check" in preview["validation"]["configured_job"]


class TruncatedResponse(io.BytesIO):
    """A response whose connection drops mid-body."""

    def read(self, *_args):
        raise http.client.IncompleteRead(b"test-token")


@pytest.mark.parametrize("truncated", [False, True])
def test_unreadable_configured_jobs_page_is_reported_not_raised(monkeypatch, truncated):
    body = TruncatedResponse() if truncated else io.BytesIO(b"\xff")
    monkeypatch.setattr(NIGHTLY.urllib.request, "urlopen", lambda *_a, **_kw: body)
    assert NIGHTLY.fetch_configured_jobs(NIGHTLY.RHDH_REPO) == []


def test_configured_jobs_page_tolerates_spaced_json(monkeypatch):
    page = f'{{"name" : "{JOB}"}} {{"name": "{JOB}"}} {{"name":"periodic-ci-x-presubmit"}}'
    monkeypatch.setattr(
        NIGHTLY.urllib.request, "urlopen", lambda *_a, **_kw: io.BytesIO(page.encode())
    )
    assert NIGHTLY.fetch_configured_jobs(NIGHTLY.RHDH_REPO) == [JOB]


@pytest.mark.parametrize(
    "response",
    [{"job_url": "https://prow.example/run"}, {}],
)
def test_submission_without_an_execution_id_does_not_poll(monkeypatch, live_cli, response):
    submissions = []
    adapter = fake_adapter(submissions, response)("ci-kubeconfig")
    adapter.status = lambda _id: pytest.fail("polled")
    monkeypatch.setattr(NIGHTLY, "GangwayAdapter", lambda _path: adapter)
    NIGHTLY.main(["--job", JOB])
    assert len(submissions) == 1


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


@pytest.mark.parametrize("status_code", [401, 403])
def test_polling_failure_keeps_submitted_id_and_safe_refresh(sleeps, capsys, status_code):
    calls = []

    def status(job_id):
        calls.append(job_id)
        raise ADAPTER.GangwayAdapterError(f"HTTP {status_code}: /setup-rhdh-skills openshift-ci")

    NIGHTLY.poll_job_status(SimpleNamespace(status=status), "execution-123")
    output = capsys.readouterr().err
    assert len(calls) == 1
    assert sleeps == []
    assert "execution-123" in output
    assert "--status execution-123" in output
    assert "/setup-rhdh-skills openshift-ci" in output


def test_polling_stops_when_the_session_expires_after_submission(monkeypatch, sleeps):
    monkeypatch.setattr(
        ADAPTER.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(returncode=1, stdout="")
    )
    requests = []
    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", lambda *a, **_kw: requests.append(a))
    NIGHTLY.poll_job_status(ADAPTER.GangwayAdapter("ci-kubeconfig"), "execution-123")
    assert sleeps == []
    assert requests == []


def test_polling_retries_a_transient_server_error_with_backoff(sleeps, capsys):
    responses = [
        ADAPTER.GangwayAdapterError("HTTP 500", retryable=True),
        ADAPTER.GangwayAdapterError("network", retryable=True),
        {"job_url": "https://prow.example/run"},
    ]

    def status(_job_id):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    NIGHTLY.poll_job_status(SimpleNamespace(status=status), "execution-123")
    output = capsys.readouterr().err
    assert sleeps == [1, 2]
    assert "https://prow.example/run" in output


def test_polling_stops_after_five_reads_with_bounded_backoff(sleeps):
    calls = []

    def status(job_id):
        calls.append(job_id)
        raise ADAPTER.GangwayAdapterError("HTTP 500", retryable=True)

    NIGHTLY.poll_job_status(SimpleNamespace(status=status), "execution-123")
    assert len(calls) == 5
    assert sleeps == [1, 2, 4, 8]


def test_polling_without_a_url_reads_five_times(sleeps):
    calls = []
    NIGHTLY.poll_job_status(
        SimpleNamespace(status=lambda job_id: calls.append(job_id) or {}), "execution-123"
    )
    assert len(calls) == 5


def test_adapter_status_uses_get_without_a_request_body(monkeypatch, adapter):
    def urlopen(request, **_kwargs):
        assert request.method == "GET"
        assert request.full_url == f"{ADAPTER.GANGWAY_URL}/execution-123"
        assert request.data is None
        assert request.get_header("Authorization") == "Bearer test-token"
        return io.BytesIO(b'{"id":"execution-123"}')

    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", urlopen)
    assert adapter.status("execution-123") == {"id": "execution-123"}


def test_adapter_status_escapes_the_execution_id(monkeypatch, adapter):
    def urlopen(request, **_kwargs):
        assert request.full_url == f"{ADAPTER.GANGWAY_URL}/a%2Fb%3Fc"
        return io.BytesIO(b"{}")

    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", urlopen)
    adapter.status("a/b?c")


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


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
def test_status_http_errors_never_claim_an_unknown_outcome(monkeypatch, adapter, status):
    def urlopen(request, **_kwargs):
        raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(b""))

    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", urlopen)
    with pytest.raises(ADAPTER.GangwayAdapterError) as error:
        adapter.status("execution-123")
    assert f"HTTP {status}" in str(error.value)
    assert not error.value.outcome_unknown
    assert error.value.retryable is (status >= 500)


@pytest.mark.parametrize("method", ["trigger", "status"])
def test_dropped_connection_is_a_network_failure(monkeypatch, adapter, method):
    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", lambda *_a, **_kw: TruncatedResponse())
    with pytest.raises(ADAPTER.GangwayAdapterError) as error:
        if method == "trigger":
            adapter.trigger({"job_name": JOB})
        else:
            adapter.status("execution-123")
    assert error.value.outcome_unknown is (method == "trigger")
    assert error.value.retryable
    assert "test-token" not in str(error.value)


@pytest.mark.parametrize(
    "failure", [urllib.error.URLError("test-token"), TimeoutError("test-token")]
)
def test_network_failures_do_not_retry_and_point_to_prow_history(
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


def test_known_submission_failure_does_not_point_to_prow_history(monkeypatch, capsys):
    def trigger(_payload):
        raise ADAPTER.GangwayAdapterError("HTTP 401")

    with pytest.raises(SystemExit):
        NIGHTLY.trigger_job(SimpleNamespace(trigger=trigger), {"job_name": JOB})
    assert f"?job={JOB}" not in capsys.readouterr().err


@pytest.mark.parametrize("method", ["trigger", "status"])
@pytest.mark.parametrize("body", [b"test-token", b"[]", b"\xff"])
def test_unreadable_responses_are_unknown_only_for_submission(monkeypatch, adapter, body, method):
    monkeypatch.setattr(ADAPTER.urllib.request, "urlopen", lambda *_a, **_kw: io.BytesIO(body))
    with pytest.raises(ADAPTER.GangwayAdapterError) as error:
        if method == "trigger":
            adapter.trigger({"job_name": JOB})
        else:
            adapter.status("execution-123")
    assert error.value.outcome_unknown is (method == "trigger")
    assert not error.value.retryable
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


def test_missing_oc_executable_routes_to_setup(monkeypatch):
    def run(*_args, **_kwargs):
        raise FileNotFoundError("oc")

    monkeypatch.setattr(ADAPTER.subprocess, "run", run)
    with pytest.raises(ADAPTER.GangwayAdapterError) as error:
        ADAPTER.GangwayAdapter("ci-kubeconfig").status("execution-123")
    assert "/setup-rhdh-skills openshift-ci" in str(error.value)
    assert not error.value.outcome_unknown
    assert not error.value.retryable
