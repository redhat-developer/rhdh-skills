#!/usr/bin/env python3
"""Patch an RHDH OLM Subscription's channel / startingCSV and approve the InstallPlan.

CatalogSource install is a different script (install-rhdh-catalog-source.sh).

Requires: oc. Python 3.9+ stdlib only.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_SUB_NS = "rhdh-operator"
DEFAULT_SUB_NAME = "rhdh"


def log_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def subscription_patch(channel: str, starting_csv: str | None) -> dict[str, Any]:
    spec: dict[str, Any] = {"channel": channel}
    if starting_csv:
        spec["startingCSV"] = starting_csv
    return {"spec": spec}


def unapproved_installplans(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    names: list[str] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        spec = item.get("spec") or {}
        if not isinstance(spec, dict) or spec.get("approved") is not False:
            continue
        name = (item.get("metadata") or {}).get("name") or ""
        if name:
            names.append(str(name))
    return names


def result_payload(
    *,
    dry_run: bool,
    namespace: str,
    name: str,
    channel: str,
    starting_csv: str | None,
    ok: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dryRun": dry_run,
        "subscriptionNamespace": namespace,
        "subscriptionName": name,
        "channel": channel,
        "startingCSV": starting_csv or None,
    }
    if ok is not None:
        payload["ok"] = ok
    return payload


def format_oc(args: list[str]) -> str:
    return "oc " + " ".join(shlex.quote(a) for a in args)


def run_oc(
    oc: str,
    args: list[str],
    *,
    dry_run: bool,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    if dry_run:
        print(format_oc(args))
        return subprocess.CompletedProcess(["oc", *args], 0, "", "")
    return subprocess.run(
        [oc, *args],
        check=check,
        text=True,
        capture_output=capture,
    )


def emit_result(payload: dict[str, Any], *, as_json: bool, starting_csv: str | None) -> None:
    if as_json:
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
        return
    if payload["dryRun"]:
        print("dry-run: true")
    else:
        print("ok: true")
    print(f"subscription: {payload['subscriptionNamespace']}/{payload['subscriptionName']}")
    print(f"channel: {payload['channel']}")
    if starting_csv:
        print(f"startingCSV: {starting_csv}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch the RHDH operator Subscription and approve a pending InstallPlan.",
    )
    parser.add_argument("--channel", required=True, help="Subscription spec.channel")
    parser.add_argument(
        "--starting-csv", default="", help="Subscription spec.startingCSV (optional)"
    )
    parser.add_argument(
        "--subscription-namespace",
        default=DEFAULT_SUB_NS,
        help=f"Namespace of the Subscription (default: {DEFAULT_SUB_NS})",
    )
    parser.add_argument(
        "--subscription-name",
        default=DEFAULT_SUB_NAME,
        help=f"Subscription name (default: {DEFAULT_SUB_NAME})",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=300,
        help="Seconds to wait for CSV (default: 300)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print oc commands; do not run them")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON object on stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    starting_csv = args.starting_csv or None
    oc = shutil.which("oc")
    if not args.dry_run and not oc:
        log_err(f"{Path(__file__).name}: oc is not on PATH")
        return 2
    oc_bin = oc or "oc"

    patch = json.dumps(subscription_patch(args.channel, starting_csv), separators=(",", ":"))
    try:
        return _run(args, oc_bin, starting_csv, patch)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        if err:
            log_err(err)
        return 1


def _run(args: argparse.Namespace, oc_bin: str, starting_csv: str | None, patch: str) -> int:
    run_oc(
        oc_bin,
        [
            "-n",
            args.subscription_namespace,
            "patch",
            "subscription",
            args.subscription_name,
            "--type",
            "merge",
            "-p",
            patch,
        ],
        dry_run=args.dry_run,
    )

    if args.dry_run:
        emit_result(
            result_payload(
                dry_run=True,
                namespace=args.subscription_namespace,
                name=args.subscription_name,
                channel=args.channel,
                starting_csv=starting_csv,
            ),
            as_json=args.as_json,
            starting_csv=starting_csv,
        )
        return 0

    listed = run_oc(
        oc_bin,
        ["-n", args.subscription_namespace, "get", "installplan", "-o", "json"],
        dry_run=False,
        check=False,
        capture=True,
    )
    try:
        payload = json.loads(listed.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    for ip in unapproved_installplans(payload):
        run_oc(
            oc_bin,
            [
                "-n",
                args.subscription_namespace,
                "patch",
                "installplan",
                ip,
                "--type",
                "merge",
                "-p",
                '{"spec":{"approved":true}}',
            ],
            dry_run=False,
        )
        phase = run_oc(
            oc_bin,
            [
                "-n",
                args.subscription_namespace,
                "get",
                "installplan",
                ip,
                "-o",
                "jsonpath={.status.phase}",
            ],
            dry_run=False,
            check=False,
            capture=True,
        )
        if (phase.stdout or "").strip() == "Failed":
            log_err(f"InstallPlan {ip} is Failed")
            return 1

    csv_name = starting_csv
    if not csv_name:
        installed = run_oc(
            oc_bin,
            [
                "-n",
                args.subscription_namespace,
                "get",
                "subscription",
                args.subscription_name,
                "-o",
                "jsonpath={.status.installedCSV}",
            ],
            dry_run=False,
            check=False,
            capture=True,
        )
        csv_name = (installed.stdout or "").strip() or None
    if not csv_name:
        log_err(
            "no startingCSV / installedCSV to wait on in "
            f"{args.subscription_namespace}/{args.subscription_name}"
        )
        return 1

    waited = run_oc(
        oc_bin,
        [
            "-n",
            args.subscription_namespace,
            "wait",
            f"csv/{csv_name}",
            "--for=jsonpath={.status.phase}=Succeeded",
            f"--timeout={args.wait_seconds}s",
        ],
        dry_run=False,
        check=False,
    )
    if waited.returncode != 0:
        log_err(f"CSV {csv_name} did not reach Succeeded")
        return 1

    emit_result(
        result_payload(
            dry_run=False,
            namespace=args.subscription_namespace,
            name=args.subscription_name,
            channel=args.channel,
            starting_csv=starting_csv,
            ok=True,
        ),
        as_json=args.as_json,
        starting_csv=starting_csv,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
