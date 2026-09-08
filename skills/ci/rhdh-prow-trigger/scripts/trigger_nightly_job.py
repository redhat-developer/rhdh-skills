#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
"""Trigger RHDH nightly ProwJobs via the OpenShift CI Gangway REST API.

Supports both the rhdh and rhdh-plugin-export-overlays repositories.

Prerequisites:
  - oc CLI installed.
  - Python 3.9+.

Authentication:
  The script uses a dedicated kubeconfig (~/.config/openshift-ci/kubeconfig)
  to avoid interfering with your current cluster context.
  It consumes an existing OpenShift CLI session and never performs login.
  Run ``/setup-rhdh-skills openshift-ci`` when that session is unavailable.
  See: https://docs.ci.openshift.org/how-tos/triggering-prowjobs-via-rest/

Usage examples:
  # List all available nightly jobs:
  uv run trigger_nightly_job.py --list

  # Trigger the OCP Helm nightly job on the main branch:
  uv run trigger_nightly_job.py --job periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly

  # Trigger with a custom image (e.g. RC verification):
  uv run trigger_nightly_job.py \\
    --job periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly \\
    --image-repo rhdh/rhdh-hub-rhel9 \\
    --tag 1.9-123

  # Trigger an overlay nightly job:
  uv run trigger_nightly_job.py \\
    --job periodic-ci-redhat-developer-rhdh-plugin-export-overlays-main-e2e-ocp-helm-nightly

  # Dry-run mode (print the request without executing):
  uv run trigger_nightly_job.py \\
    --job periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly \\
    --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from gangway_adapter import GANGWAY_URL, GangwayAdapter, GangwayAdapterError

# --- Constants ---
CI_SERVER = "https://api.ci.l2s4.p1.openshiftapps.com:6443"

REPOS = [
    "redhat-developer/rhdh",
    "redhat-developer/rhdh-plugin-export-overlays",
]

OVERLAY_JOB_PREFIX = "periodic-ci-redhat-developer-rhdh-plugin-export-overlays-"
NIGHTLY_JOB_PATTERN = re.compile(
    r"periodic-ci-redhat-developer-rhdh-(?:plugin-export-overlays-)?"
    r"[a-zA-Z0-9][a-zA-Z0-9_.-]*-nightly"
)
TRIGGER_OVERRIDES = (
    "image_registry",
    "image_repo",
    "tag",
    "catalog_index_image",
    "chart_version",
    "playwright_version",
    "org",
    "repo",
    "branch",
    "send_alerts",
)


# --- Logging ---
def log_info(msg: str) -> None:
    print(f"[INFO] {msg}", file=sys.stderr)


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


# --- Job listing ---
def fetch_configured_jobs(repo: str) -> list[str]:
    """Fetch nightly job names from the Prow configured-jobs page.

    The page returns HTML with embedded JSON containing ``"name":"<job>"``
    entries. We extract job names ending in ``-nightly`` via regex.
    """
    url = f"https://prow.ci.openshift.org/configured-jobs/{repo}"
    req = urllib.request.Request(url, headers={"User-Agent": "rhdh-skills"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as exc:
        log_warn(f"Failed to fetch jobs from {url}: {exc}")
        return []

    # Extract job names from embedded JSON: "name":"periodic-ci-...-nightly"
    matches = re.findall(r'"name"\s*:\s*"(periodic-ci-[^"]*-nightly)"', html)
    return sorted(set(matches))


def ensure_configured_job(job: str) -> None:
    """Require membership in the owning repository's live job list before a POST."""
    repo = REPOS[1] if job.startswith(OVERLAY_JOB_PREFIX) else REPOS[0]
    jobs = fetch_configured_jobs(repo)
    if not jobs:
        log_error(f"Cannot verify configured nightly jobs for {repo}; no job was submitted.")
        log_error("Check the configured-jobs page and network access, then retry --list.")
        sys.exit(1)
    if job not in jobs:
        log_error(f"Job is not configured for {repo}: {job}")
        log_error("Run --list and select a configured nightly job. No job was submitted.")
        sys.exit(1)


def _short_name(job: str, repo: str) -> str:
    """Extract the human-readable test name from a full job name.

    E.g. ``periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly``
    -> ``e2e-ocp-helm-nightly``
    """
    # The prefix is: periodic-ci-{org}-{repo}-{branch}-
    # We need to strip the prefix up to and including the branch segment.
    org_repo = repo.replace("/", "-")
    prefix = f"periodic-ci-{org_repo}-"
    if not job.startswith(prefix):
        return job

    remainder = job[len(prefix) :]
    # remainder is e.g. "main-e2e-ocp-helm-nightly" or "release-1.9-e2e-ocp-helm-nightly"
    # Find the first "e2e-" segment to split branch from test name.
    match = re.search(r"(e2e-.+)$", remainder)
    if match:
        return match.group(1)
    return remainder


def _extract_branch(job: str, repo: str) -> str:
    """Extract the branch name from a full job name."""
    org_repo = repo.replace("/", "-")
    prefix = f"periodic-ci-{org_repo}-"
    if not job.startswith(prefix):
        return "?"

    remainder = job[len(prefix) :]
    match = re.search(r"(e2e-.+)$", remainder)
    if match:
        branch = remainder[: match.start()].rstrip("-")
        return branch if branch else "?"
    return "?"


def list_jobs(*, json_output: bool = False) -> None:
    """Fetch and print available nightly jobs from all repos."""
    # Collect all jobs grouped by (repo, short_name) -> set of branches
    table: dict[tuple[str, str], set[str]] = {}
    all_branches: set[str] = set()
    # Also collect full job names for JSON output.
    full_names: dict[tuple[str, str, str], str] = {}

    for repo in REPOS:
        log_info(f"Fetching jobs from {repo}...")
        jobs = fetch_configured_jobs(repo)
        for job in jobs:
            short = _short_name(job, repo)
            branch = _extract_branch(job, repo)
            key = (repo, short)
            table.setdefault(key, set()).add(branch)
            all_branches.add(branch)
            full_names[(repo, short, branch)] = job

    if not table:
        log_error("No nightly jobs found.")
        sys.exit(1)

    if json_output:
        result: list[dict] = []
        for (repo, short), branches in sorted(table.items()):
            for branch in sorted(branches):
                result.append(
                    {
                        "repo": repo,
                        "job": short,
                        "branch": branch,
                        "full_name": full_names[(repo, short, branch)],
                    }
                )
        print(json.dumps(result, indent=2))
        return

    # Sort branches: main first, then release-* in descending order
    def branch_sort_key(b: str) -> tuple[int, str]:
        if b == "main":
            return (0, "")
        return (1, b)

    sorted_branches = sorted(all_branches, key=branch_sort_key)

    # Print table
    repo_col = "Repo"
    job_col = "Job"
    max_repo = max(len(repo_col), max(len(r.split("/")[-1]) for r, _ in table))
    max_job = max(len(job_col), max(len(s) for _, s in table))
    branch_widths = {b: max(len(b), 1) for b in sorted_branches}

    header = f"| {'Repo':<{max_repo}} | {'Job':<{max_job}} |"
    for b in sorted_branches:
        header += f" {b:<{branch_widths[b]}} |"
    sep = f"|{'-' * (max_repo + 2)}|{'-' * (max_job + 2)}|"
    for b in sorted_branches:
        sep += f"{'-' * (branch_widths[b] + 2)}|"

    print(header)
    print(sep)

    for (repo, short), branches in sorted(table.items()):
        repo_short = repo.split("/")[-1]
        row = f"| {repo_short:<{max_repo}} | {short:<{max_job}} |"
        for b in sorted_branches:
            mark = "x" if b in branches else ""
            row += f" {mark:<{branch_widths[b]}} |"
        print(row)


# --- Tag listing ---
DEFAULT_IMAGE_REPO = "rhdh/rhdh-hub-rhel9"


def _fetch_quay_tags(image_repo: str, like_filter: str) -> list[dict]:
    """Fetch tags from the Quay API with a ``like:`` substring filter."""
    encoded_repo = urllib.request.quote(image_repo, safe="")
    encoded_filter = urllib.request.quote(like_filter, safe="")
    url = (
        f"https://quay.io/api/v1/repository/{encoded_repo}/tag/"
        f"?limit=100&onlyActiveTags=true&filter_tag_name=like:{encoded_filter}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "rhdh-skills"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as exc:
        log_warn(f"Failed to fetch tags (filter={like_filter!r}): {exc}")
        return []
    return data.get("tags", [])


def _fetch_version_tags(image_repo: str, tag_filter: str = "") -> list[str]:
    """Fetch version tags from quay.io for the given image repo.

    If *tag_filter* is provided (e.g. ``1.10``), a single Quay request with
    ``filter_tag_name=like:<tag_filter>`` is issued — fast and precise.

    Without a filter, two requests are made for the ``1.`` and ``2.`` major
    version prefixes and the results are merged, covering current and upcoming
    RHDH releases.

    In both cases the results are filtered locally by a strict version regex
    (``MAJOR.MINOR`` or ``MAJOR.MINOR-BUILD``) to discard digest artifacts
    that happen to match the substring filter.
    """
    version_re = re.compile(r"^[0-9]+\.[0-9]+(-[0-9]+)?$")

    if tag_filter:
        prefixes = [tag_filter]
    else:
        prefixes = ["1.", "2."]

    seen: set[str] = set()
    tags: list[str] = []
    for prefix in prefixes:
        for t in _fetch_quay_tags(image_repo, prefix):
            name = t.get("name", "")
            if name not in seen and version_re.match(name):
                seen.add(name)
                tags.append(name)

    tags.sort(key=lambda t: [int(x) for x in re.split(r"[-.]", t)])
    return tags


def list_tags(
    image_repo: str, limit: int = 20, *, tag_filter: str = "", json_output: bool = False
) -> None:
    """Fetch and print available image tags from quay.io."""
    tags = _fetch_version_tags(image_repo, tag_filter=tag_filter)

    if not tags:
        log_error(f"No matching tags found for {image_repo}")
        sys.exit(1)

    # JSON always returns all tags; human output shows the latest N.
    if json_output:
        print(json.dumps({"image_repo": image_repo, "tags": tags}, indent=2))
        return

    display_tags = tags[-limit:]
    log_info(f"Available tags for {image_repo} (latest {len(display_tags)}):")
    for i, tag in enumerate(display_tags, 1):
        print(f"  {i}. {tag}")


# --- Authentication ---
def ensure_capability(kubeconfig: str) -> None:
    """Verify an existing OpenShift CI CLI session without reading credentials."""
    if not shutil.which("oc"):
        log_error("OpenShift CI capability is unavailable.")
        log_error("Run /setup-rhdh-skills openshift-ci, then retry.")
        sys.exit(1)

    oc_base = ["oc", "--kubeconfig", kubeconfig]

    result = subprocess.run(
        [*oc_base, "whoami", "--show-server"],
        capture_output=True,
        text=True,
    )
    current_server = result.stdout.strip() if result.returncode == 0 else ""
    if current_server != CI_SERVER:
        if current_server:
            log_warn(f"Currently logged in to {current_server}, need {CI_SERVER}")
        log_error("OpenShift CI authentication is missing or expired.")
        log_error("Run /setup-rhdh-skills openshift-ci, then retry.")
        sys.exit(1)

    result = subprocess.run(
        [*oc_base, "whoami"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log_error("OpenShift CI authentication is missing or expired.")
        log_error("Run /setup-rhdh-skills openshift-ci, then retry.")
        sys.exit(1)


# --- Payload ---
def build_payload(args: argparse.Namespace) -> dict:
    """Build the Gangway API request payload."""
    envs: dict[str, str] = {}

    is_overlay = args.job.startswith(OVERLAY_JOB_PREFIX)

    if is_overlay:
        # Overlay jobs support fork overrides, catalog index, and playwright version.
        # Image overrides, chart version, and alerts are not supported.
        unsupported: list[str] = []
        if args.image_repo:
            unsupported.append("--image-repo")
        if args.image_registry:
            unsupported.append("--image-registry")
        if args.tag:
            unsupported.append("--tag")
        if args.chart_version:
            unsupported.append("--chart-version")
        if args.send_alerts:
            unsupported.append("--send-alerts")
        if unsupported:
            log_error(
                f"Overlay jobs do not support: {', '.join(unsupported)}. "
                "These flags only work with rhdh repo jobs."
            )
            sys.exit(1)

        if args.org:
            envs["MULTISTAGE_PARAM_OVERRIDE_GITHUB_ORG_NAME"] = args.org
        if args.repo:
            envs["MULTISTAGE_PARAM_OVERRIDE_GITHUB_REPOSITORY_NAME"] = args.repo
        if args.branch:
            envs["MULTISTAGE_PARAM_OVERRIDE_RELEASE_BRANCH_NAME"] = args.branch
        if args.catalog_index_image:
            envs["MULTISTAGE_PARAM_OVERRIDE_CATALOG_INDEX_IMAGE"] = args.catalog_index_image
        if args.playwright_version:
            envs["MULTISTAGE_PARAM_OVERRIDE_PLAYWRIGHT_VERSION"] = args.playwright_version
    else:
        # RHDH repo jobs do not support playwright version.
        if args.playwright_version:
            log_error("--playwright-version is only supported for overlay jobs.")
            sys.exit(1)

        # RHDH repo jobs support full overrides.
        if args.image_repo:
            envs["MULTISTAGE_PARAM_OVERRIDE_IMAGE_REPO"] = args.image_repo
        if args.image_registry:
            envs["MULTISTAGE_PARAM_OVERRIDE_IMAGE_REGISTRY"] = args.image_registry
        if args.tag:
            envs["MULTISTAGE_PARAM_OVERRIDE_TAG_NAME"] = args.tag
        if args.org:
            envs["MULTISTAGE_PARAM_OVERRIDE_GITHUB_ORG_NAME"] = args.org
        if args.repo:
            envs["MULTISTAGE_PARAM_OVERRIDE_GITHUB_REPOSITORY_NAME"] = args.repo
        if args.branch:
            envs["MULTISTAGE_PARAM_OVERRIDE_RELEASE_BRANCH_NAME"] = args.branch
        if args.catalog_index_image:
            envs["MULTISTAGE_PARAM_OVERRIDE_CATALOG_INDEX_IMAGE"] = args.catalog_index_image
        if args.chart_version:
            envs["MULTISTAGE_PARAM_OVERRIDE_CHART_VERSION"] = args.chart_version

        skip_alert = "false" if args.send_alerts else "true"
        envs["MULTISTAGE_PARAM_OVERRIDE_SKIP_SEND_ALERT"] = skip_alert

    payload: dict = {
        "job_name": args.job,
        "job_execution_type": "1",
    }
    if envs:
        payload["pod_spec_options"] = {"envs": envs}

    return payload


# --- Trigger ---
def trigger_job(adapter: GangwayAdapter, payload: dict) -> dict:
    """Send a credential-free request through the Gangway adapter."""
    log_info("Triggering job...")
    try:
        body = adapter.trigger(payload)
    except GangwayAdapterError as error:
        log_error(str(error))
        if error.outcome_unknown:
            log_warn(
                "Submission outcome is unknown; a job may have been created. "
                "Inspect Prow job history before retrying the trigger: "
                f"https://prow.ci.openshift.org/?job={payload['job_name']}"
            )
        sys.exit(1)

    log_info("Response:")
    print(json.dumps(body, indent=2), file=sys.stderr)
    return body


def command_line(*arguments: str) -> str:
    """Render a shell-safe command that also works outside the skill directory."""
    return shlex.join(["uv", "run", os.path.abspath(__file__), *arguments])


def show_job_status(adapter: GangwayAdapter, job_id: str) -> None:
    """Read one existing execution without ever submitting a job."""
    log_info(f"Job ID: {job_id}")
    try:
        response = adapter.status(job_id)
    except GangwayAdapterError as error:
        log_error(str(error))
        sys.exit(1)
    print(json.dumps(response, indent=2))
    if response.get("job_url"):
        log_info(f"Job URL: {response['job_url']}")
    else:
        log_warn("Job URL not yet available; repeat --status with this execution ID.")


def poll_job_status(adapter: GangwayAdapter, job_id: str) -> None:
    """Poll the Gangway API for the job URL."""
    print("", file=sys.stderr)
    log_info(f"Job ID: {job_id}")
    log_info(f"Refresh status: {command_line('--status', job_id)}")
    log_info("Waiting for Prow URL...")

    job_url = ""
    for attempt in range(5):
        print(".", end="", flush=True, file=sys.stderr)
        try:
            data = adapter.status(job_id)
            job_url = data.get("job_url", "")
            if job_url:
                break
        except GangwayAdapterError as error:
            print("", file=sys.stderr)
            log_warn(f"Job was submitted, but status lookup failed: {error}")
            return
        if attempt < 4:
            time.sleep(2)

    print("", file=sys.stderr)
    if job_url:
        log_info(f"Job URL: {job_url}")
    else:
        log_warn("Job URL not yet available.")


# --- CLI ---
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trigger RHDH nightly ProwJobs via the OpenShift CI Gangway REST API.",
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Job name patterns:
  RHDH:     periodic-ci-redhat-developer-rhdh-{BRANCH}-e2e-{PLATFORM}-{METHOD}-nightly
  Overlays: periodic-ci-redhat-developer-rhdh-plugin-export-overlays-{BRANCH}-e2e-{PLATFORM}-{METHOD}-nightly

Examples:
  %(prog)s --list
  %(prog)s --status <EXECUTION_ID>
  %(prog)s --job periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly
  %(prog)s --job periodic-ci-redhat-developer-rhdh-plugin-export-overlays-main-e2e-ocp-helm-nightly
  %(prog)s --job periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly --tag 1.9-123
""",
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "-l",
        "--list",
        action="store_true",
        dest="list_jobs",
        help="List available nightly jobs from all repos.",
    )
    action.add_argument(
        "-j",
        "--job",
        dest="job",
        help="Full ProwJob name to trigger.",
    )
    action.add_argument(
        "-T",
        "--list-tags",
        action="store_true",
        dest="list_tags",
        help="List available image tags from quay.io. Use --image-repo to specify the repo.",
    )
    action.add_argument(
        "--status",
        metavar="EXECUTION_ID",
        help="Read an existing execution's status and URL without triggering a job.",
    )
    parser.add_argument(
        "--tag-filter",
        dest="tag_filter",
        default="",
        help="Filter tags by version prefix (e.g. '1.10'). Used with --list-tags.",
    )

    shared = parser.add_argument_group("Shared overrides (both rhdh and overlay jobs)")
    shared.add_argument(
        "-o",
        "--org",
        dest="org",
        default="",
        help="Override the GitHub org (default: redhat-developer).",
    )
    shared.add_argument(
        "-r",
        "--repo",
        dest="repo",
        default="",
        help="Override the GitHub repo name (default: rhdh).",
    )
    shared.add_argument(
        "-b",
        "--branch",
        dest="branch",
        default="",
        help="Override the branch name.",
    )
    shared.add_argument(
        "--catalog-index-image",
        dest="catalog_index_image",
        default="",
        help="Override the catalog index image (e.g. quay.io/rhdh/plugin-catalog-index:1.9-60).",
    )

    rhdh_only = parser.add_argument_group("RHDH-only overrides (not supported for overlay jobs)")
    rhdh_only.add_argument(
        "-I",
        "--image-registry",
        dest="image_registry",
        default="",
        help="Override the image registry (default: quay.io).",
    )
    rhdh_only.add_argument(
        "-q",
        "--image-repo",
        dest="image_repo",
        default="",
        help="Override the image repository (e.g. rhdh/rhdh-hub-rhel9). Requires --tag.",
    )
    rhdh_only.add_argument(
        "-t",
        "--tag",
        dest="tag",
        default="",
        help="Override the image tag (e.g. 1.9-123).",
    )
    rhdh_only.add_argument(
        "--chart-version",
        dest="chart_version",
        default="",
        help="Override the Helm chart version (e.g. 1.9-227-CI).",
    )
    rhdh_only.add_argument(
        "-S",
        "--send-alerts",
        action="store_true",
        help="Send Slack alerts (default: alerts are skipped).",
    )

    overlay_only = parser.add_argument_group("Overlay-only overrides (not supported for rhdh jobs)")
    overlay_only.add_argument(
        "--playwright-version",
        dest="playwright_version",
        default="",
        help="Override the Playwright version (overlay jobs only).",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print the request payload without executing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output structured JSON instead of human-readable text (for --list and --list-tags).",
    )

    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    """Validate parsed arguments."""
    if args.dry_run and not args.job:
        log_error("--dry-run requires --job.")
        sys.exit(1)

    if args.status is not None:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", args.status):
            log_error("--status requires an execution ID, not a URL or path.")
            sys.exit(1)
        if any(getattr(args, name) for name in TRIGGER_OVERRIDES) or args.tag_filter:
            log_error("--status cannot be combined with trigger overrides or --tag-filter.")
            sys.exit(1)

    if args.tag_filter and not args.list_tags:
        log_warn("--tag-filter is only used with --list-tags, ignoring.")

    if args.job is not None:
        if not NIGHTLY_JOB_PATTERN.fullmatch(args.job):
            log_error(
                "Expected a periodic-ci-redhat-developer-rhdh-*-nightly or "
                f"periodic-ci-redhat-developer-rhdh-plugin-export-overlays-*-nightly job, got: {args.job}"
            )
            sys.exit(1)

        if args.image_repo and not args.tag:
            log_error("--image-repo requires --tag to be set.")
            sys.exit(1)


def print_summary(args: argparse.Namespace, payload: dict) -> None:
    """Print a summary of the job to be triggered."""
    log_info(f"Job:     {args.job}")
    log_info("Payload:")
    print(json.dumps(payload, indent=2), file=sys.stderr)
    print("", file=sys.stderr)


def print_dry_run(args: argparse.Namespace, payload: dict) -> None:
    """Print the proposed command, request, impact, and recovery without I/O."""
    arguments = ["--job", args.job]
    for name in TRIGGER_OVERRIDES:
        value = getattr(args, name)
        if value:
            arguments.append(f"--{name.replace('_', '-')}")
            if not isinstance(value, bool):
                arguments.append(value)
    print("[DRY RUN] No job submitted. Proposed authenticated adapter request:")
    print(
        json.dumps(
            {
                "adapter": "openshift-ci-gangway/v1",
                "operation": "gangway.execution.create",
                "target": GANGWAY_URL,
                "authentication": "native oc kubeconfig (redacted)",
                "execution_command": command_line(*arguments),
                "payload": payload,
                "validation": {
                    "job_name_and_flags": "passed",
                    "configured_job": "unchecked offline; required before live submission",
                    "authentication": "unchecked",
                    "images_and_chart": "unchecked",
                },
                "impact": (
                    "Creates one ProwJob, consuming CI compute and the configured test cluster "
                    "or cloud resources. Tests deploy workloads and may change cluster state. "
                    "Duration and monetary cost are unknown; no resources are reserved by this preview."
                ),
                "abort": (
                    "Before submission, decline to run the execution command. After submission, "
                    "stopping this client does not cancel the job. Give the execution ID/URL to "
                    "an OpenShift CI administrator to abort the run and check resource cleanup; "
                    "this CLI has no cancellation operation."
                ),
                "failure_behavior": (
                    "Stop if job discovery, authentication, or submission fails; no automatic "
                    "POST retry. A network failure, server error, or invalid response can leave "
                    "submission outcome unknown. Inspect Prow job history before retrying."
                ),
                "verification": (
                    "Report the API response and execution ID/URL. Read the existing execution with "
                    f"{command_line('--status', '<EXECUTION_ID>')}. "
                    "If neither ID nor URL is returned, report that verification is incomplete."
                ),
            },
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> None:
    # Use a dedicated kubeconfig to avoid interfering with current cluster context.
    config_home = os.environ.get(
        "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
    )
    kubeconfig = os.path.join(config_home, "openshift-ci", "kubeconfig")

    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    validate_args(args)

    if args.list_jobs:
        list_jobs(json_output=args.json_output)
        return

    if args.list_tags:
        list_tags(
            args.image_repo or DEFAULT_IMAGE_REPO,
            tag_filter=args.tag_filter,
            json_output=args.json_output,
        )
        return

    if args.status is not None:
        ensure_capability(kubeconfig)
        show_job_status(GangwayAdapter(kubeconfig), args.status)
        return

    payload = build_payload(args)
    print_summary(args, payload)

    if args.dry_run:
        print_dry_run(args, payload)
        return

    ensure_configured_job(args.job)
    ensure_capability(kubeconfig)
    log_info(f"Command: {command_line(*argv)}")
    adapter = GangwayAdapter(kubeconfig)
    response = trigger_job(adapter, payload)

    job_id = response.get("id", "")
    if job_id:
        poll_job_status(adapter, job_id)
    elif response.get("job_url"):
        log_info(f"Job URL: {response['job_url']}")
        log_warn("Gangway returned no execution ID; --status is unavailable for this response.")
    else:
        log_warn(
            "Gangway returned no execution ID or URL; verification is incomplete. "
            "Inspect Prow job history before submitting another job."
        )


if __name__ == "__main__":
    main()
