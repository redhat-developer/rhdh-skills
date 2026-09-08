#!/usr/bin/env python3
"""Report which catalog index an RHDH deployment actually used.

"It installed" is not a result. install-dynamic-plugins falls back from
registry.access.redhat.com/rhdh/ to quay.io/rhdh/ when a manifest is missing,
so a stale index installs with no error and quietly serves older plugin builds.
The fallback count is the only signal that this happened.

    verify_index.py --namespace rhdh-test
    verify_index.py --namespace rhdh-test --expect-digest sha256:65a60ffc...
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

INDEX_RE = re.compile(r"Extracting catalog index from (\S+)")
FALLBACK_RE = re.compile(r"Using fallback image: (\S+)")
INSTALLED_RE = re.compile(r"Successfully installed dynamic plugin (\S+)")


def oc(*args: str) -> tuple[str, int]:
    proc = subprocess.run(["oc", *args], capture_output=True, text=True)
    return proc.stdout, proc.returncode


def newest_pod(namespace: str, selector: str | None) -> str | None:
    args = ["get", "pods", "-n", namespace, "--sort-by=.metadata.creationTimestamp",
            "--no-headers", "-o", "custom-columns=:metadata.name"]
    if selector:
        args += ["-l", selector]
    out, rc = oc(*args)
    if rc != 0:
        return None
    # Sorting by AGE returns the oldest first, which during a rollout is the pod
    # that already failed. creationTimestamp plus last() is the live one.
    names = [n for n in out.split() if "developer-hub" in n or "backstage" in n]
    return names[-1] if names else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--pod", help="Pod name; defaults to the newest RHDH pod in the namespace")
    ap.add_argument("--selector", help="Label selector to narrow the pod search")
    ap.add_argument("--expect-digest", help="Exit 2 unless the index used matches this digest")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pod = args.pod or newest_pod(args.namespace, args.selector)
    if not pod:
        print(f"error: no RHDH pod found in {args.namespace}", file=sys.stderr)
        return 1

    log, rc = oc("logs", "-n", args.namespace, pod, "-c", "install-dynamic-plugins")
    if rc != 0 or not log:
        print(f"error: no install-dynamic-plugins log on {pod}; is the init container still running?",
              file=sys.stderr)
        return 1

    index = INDEX_RE.search(log)
    fallbacks = FALLBACK_RE.findall(log)
    result = {
        "pod": pod,
        "index_used": index.group(1) if index else None,
        "plugins_installed": len(INSTALLED_RE.findall(log)),
        "quay_fallbacks": len(fallbacks),
        "fallback_images": sorted(set(fallbacks)),
    }

    mismatch = False
    if args.expect_digest:
        want = args.expect_digest if args.expect_digest.startswith("sha256:") else f"sha256:{args.expect_digest}"
        result["expected_digest"] = want
        mismatch = not (result["index_used"] or "").endswith(want)
        result["matches_expected"] = not mismatch

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"pod                 {result['pod']}")
        print(f"index used          {result['index_used'] or '(not found in log)'}")
        print(f"plugins installed   {result['plugins_installed']}")
        print(f"quay.io fallbacks   {result['quay_fallbacks']}"
              f"{'   <- stale index: older builds were served' if result['quay_fallbacks'] else ''}")
        if args.expect_digest:
            print(f"matches expected    {'yes' if not mismatch else 'NO'}")

    if mismatch:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
