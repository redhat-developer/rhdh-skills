#!/usr/bin/env python3
"""Verify an RHDH smoke-test namespace: pods, logs, Guest token, packages API.

Requires: oc. Python 3.9+ stdlib only. A current oc session (KUBECONFIG).
The Guest JWT is held in memory for the packages request and is never printed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BAD_POD_RE = re.compile(r"ImagePullBackOff|ErrImagePull|CrashLoopBackOff|OOMKilled")
DEPLOY_RE = re.compile(r"redhat-developer-hub|backstage")
PLUGIN_AUTH_RE = re.compile(r"401|403")
HTTP_TIMEOUT = 30


def log_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def guest_token(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    ident = data.get("backstageIdentity") or {}
    if not isinstance(ident, dict):
        ident = {}
    token = ident.get("token") or data.get("token") or ""
    return str(token) if token else ""


def packages_len(data: Any) -> int:
    """Count catalog packages from /api/extensions/packages.

    Current API is ``{items, totalItems}``. Prefer ``totalItems``, then
    ``len(items)``, then a bare JSON array.
    """
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict):
        return 0
    total = data.get("totalItems")
    if isinstance(total, int) and not isinstance(total, bool):
        return total
    if isinstance(total, str) and total.isdigit():
        return int(total)
    items = data.get("items")
    if isinstance(items, list):
        return len(items)
    return 0


def first_matching_line(text: str, pattern: re.Pattern[str]) -> str:
    for line in text.splitlines():
        if pattern.search(line):
            return line.strip()
    return ""


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def http_body(url: str, *, method: str = "GET", token: str | None = None) -> str:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers)
    if method == "POST":
        req.data = b""
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return ""


def run_oc(oc: str, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run([oc, *args], check=check, text=True, capture_output=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify pods, Guest sign-in, and the extensions packages API in an RHDH "
            "smoke-test namespace."
        ),
    )
    parser.add_argument("-n", "--namespace", required=True, help="Namespace to check")
    parser.add_argument("--url", default="", help="RHDH base URL (default: first matching Route)")
    parser.add_argument(
        "--min-packages",
        type=int,
        default=1,
        help="packages totalItems (or items length) must be >= N (default: 1)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="JSON object on stdout (warnings still on stderr)",
    )
    return parser.parse_args(argv)


def emit_result(
    *,
    as_json: bool,
    namespace: str,
    url: str,
    deploy: str,
    packages: int,
    failures: list[str],
) -> None:
    if as_json:
        json.dump(
            {
                "namespace": namespace,
                "url": url,
                "packages": packages,
                "ok": not failures,
                "failures": failures,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return
    print(f"namespace: {namespace}")
    print(f"url: {url}")
    print(f"deploy: {deploy}")
    print(f"Total items: {packages}")
    if failures:
        print(f"failures: {' '.join(failures)}")
    else:
        print("ok: true")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    oc = shutil.which("oc")
    if not oc:
        log_err(f"{Path(__file__).name}: oc is not on PATH")
        return 2

    failures: list[str] = []
    packages = 0
    deploy = ""
    rhdh_url = args.url
    ns = args.namespace

    if run_oc(oc, ["get", "ns", ns]).returncode != 0:
        log_err(f"namespace not found: {ns}")
        failures.append("namespace-missing")

    pods = run_oc(
        oc,
        [
            "-n",
            ns,
            "get",
            "pods",
            "-o",
            "jsonpath={range .items[*].status.containerStatuses[*]}"
            '{.state.waiting.reason}{"\\n"}{.lastState.terminated.reason}{"\\n"}{end}',
        ],
    )
    bad_reasons = pods.stdout or ""
    if BAD_POD_RE.search(bad_reasons):
        log_err(f"bad pod reason in {ns}:")
        log_err(bad_reasons)
        failures.append("bad-pod")

    deploys = run_oc(
        oc,
        ["-n", ns, "get", "deploy", "-o", 'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}'],
    )
    deploy = first_matching_line(deploys.stdout or "", DEPLOY_RE)
    if not deploy:
        log_err(f"no redhat-developer-hub/backstage Deployment in {ns}")
        failures.append("no-deploy")
    else:
        plugin_log = run_oc(
            oc,
            ["-n", ns, "logs", f"deploy/{deploy}", "-c", "install-dynamic-plugins", "--tail=200"],
        )
        plugin_text = plugin_log.stdout or ""
        if plugin_text:
            print(plugin_text, file=sys.stderr, end="" if plugin_text.endswith("\n") else "\n")
            if PLUGIN_AUTH_RE.search(plugin_text):
                log_err("401/403 in install-dynamic-plugins logs")
                failures.append("plugin-auth")
        else:
            all_logs = run_oc(
                oc,
                ["-n", ns, "logs", f"deploy/{deploy}", "--all-containers", "--tail=50"],
            )
            if all_logs.stdout:
                print(all_logs.stdout, file=sys.stderr, end="")
        backend = run_oc(
            oc,
            ["-n", ns, "logs", f"deploy/{deploy}", "-c", "backstage-backend", "--tail=50"],
        )
        if backend.stdout:
            print(backend.stdout, file=sys.stderr, end="")

    if not rhdh_url:
        routes = run_oc(
            oc,
            ["-n", ns, "get", "route", "-o", 'jsonpath={range .items[*]}{.spec.host}{"\\n"}{end}'],
        )
        host = first_matching_line(routes.stdout or "", DEPLOY_RE)
        if host:
            rhdh_url = f"https://{host}"

    if not rhdh_url:
        log_err("no Route host and --url not set")
        failures.append("no-url")
    else:
        refresh = parse_json(http_body(f"{rhdh_url}/api/auth/guest/refresh", method="POST"))
        token = guest_token(refresh)
        if not token:
            log_err("Guest refresh returned no token (Guest may be off)")
            failures.append("no-guest-token")
        else:
            pack_json = parse_json(http_body(f"{rhdh_url}/api/extensions/packages", token=token))
            packages = packages_len(pack_json)
            if packages < args.min_packages:
                log_err(f"Total items {packages} < {args.min_packages}")
                failures.append("packages-low")

    emit_result(
        as_json=args.as_json,
        namespace=ns,
        url=rhdh_url,
        deploy=deploy,
        packages=packages,
        failures=failures,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
