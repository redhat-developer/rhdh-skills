#!/usr/bin/env python3
"""Derive OpenShift router base, token-display URL, and API server from a console URL.

Requires: Python 3.9+ stdlib only. No oc.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import urlparse

CONSOLE_PREFIX = "console-openshift-console."
APPS_PREFIX = "apps."


def log_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def hostname_from_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    return (parsed.hostname or "").rstrip(".").lower()


def cluster_from_hostname(host: str) -> dict[str, str]:
    if host.startswith(CONSOLE_PREFIX):
        router = host[len(CONSOLE_PREFIX) :]
    elif host.startswith(APPS_PREFIX) or host.startswith("oauth-openshift."):
        router = host[len("oauth-openshift.") :] if host.startswith("oauth-openshift.") else host
    else:
        return {}
    if not router.startswith(APPS_PREFIX):
        return {}
    rest = router[len(APPS_PREFIX) :]
    if not rest:
        return {}
    return {
        "clusterRouterBase": router,
        "tokenDisplayUrl": f"https://oauth-openshift.{router}/oauth/token/display",
        "apiServer": f"https://api.{rest}:6443",
    }


def parse_console_url(raw: str) -> dict[str, str]:
    host = hostname_from_url(raw)
    if not host:
        return {}
    return cluster_from_hostname(host)


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
        return
    for key in ("clusterRouterBase", "tokenDisplayUrl", "apiServer"):
        print(f"{key}={payload[key]}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse an OpenShift console URL into clusterRouterBase, "
            "oauth/token/display URL, and API server."
        ),
    )
    parser.add_argument(
        "url",
        help="Console URL, e.g. https://console-openshift-console.apps.example.com/",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="JSON object on stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    derived = parse_console_url(args.url)
    if not derived:
        log_err(f"not an OpenShift console URL: {args.url}")
        return 2
    emit(derived, as_json=args.as_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
