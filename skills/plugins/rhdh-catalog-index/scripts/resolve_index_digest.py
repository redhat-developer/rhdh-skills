#!/usr/bin/env python3
"""Resolve plugin-catalog-index digests for an RHDH stream or tag.

Prints the manifest-list digest, which is what the Helm chart and the Operator
pin, alongside the per-architecture children so the two are never confused.

    resolve_index_digest.py --stream 1.10
    resolve_index_digest.py --tag 1.10.4-1788447603
    resolve_index_digest.py --stream 1.10 --compare-to sha256:51d12fc0...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys

DEFAULT_REPO = "registry.access.redhat.com/rhdh/plugin-catalog-index"


def inspect_raw(ref: str) -> tuple[dict | None, str | None]:
    """Return (manifest, error). Uses skopeo, which every RHDH runner ships."""
    proc = subprocess.run(
        ["skopeo", "inspect", "--raw", f"docker://{ref}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip()
        return None, err.splitlines()[-1] if err else "skopeo failed"
    return json.loads(proc.stdout), None


def digest_of(ref: str) -> tuple[str | None, str | None]:
    """The manifest-list digest: sha256 over the raw manifest bytes.

    `skopeo inspect --format {{.Digest}}` cannot be used here - it resolves an
    image instance for the host platform, so it fails outright on a darwin/arm64
    workstation against a linux-only index.
    """
    proc = subprocess.run(
        ["skopeo", "inspect", "--raw", f"docker://{ref}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        return None, err.splitlines()[-1] if err else "skopeo failed"
    return "sha256:" + hashlib.sha256(proc.stdout).hexdigest(), None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--stream", help='Release stream, e.g. "1.10". Resolves the floating tag.')
    src.add_argument("--tag", help='Exact tag, e.g. "1.10.4-1788447603".')
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"Index repository (default: {DEFAULT_REPO})")
    ap.add_argument("--compare-to", metavar="DIGEST",
                    help="A digest already deployed. Exit 2 when it differs from the resolved one.")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    tag = args.tag or args.stream
    ref = f"{args.repo}:{tag}"

    listed, err = digest_of(ref)
    if err:
        print(f"error: cannot resolve {ref}: {err}", file=sys.stderr)
        return 1

    manifest, err = inspect_raw(ref)
    children = []
    if manifest and "manifests" in manifest:
        for m in manifest["manifests"]:
            p = m.get("platform", {})
            children.append({
                "os": p.get("os"), "architecture": p.get("architecture"), "digest": m["digest"],
            })

    result = {
        "reference": ref,
        "manifest_list_digest": listed,
        "bare_digest": listed.removeprefix("sha256:"),
        "children": children,
    }

    drift = None
    if args.compare_to:
        normalized = args.compare_to if args.compare_to.startswith("sha256:") else f"sha256:{args.compare_to}"
        drift = normalized != listed
        result["deployed_digest"] = normalized
        result["drift"] = drift

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"reference           {ref}")
        print(f"manifest list       {listed}")
        print(f"bare digest         {result['bare_digest']}   <- Helm --set value")
        for c in children:
            print(f"  child {c['os']}/{c['architecture']:<8} {c['digest']}   <- do NOT pin this")
        if drift is not None:
            print(f"deployed            {result['deployed_digest']}")
            print(f"drift               {'YES - deployment is behind' if drift else 'no - already current'}")

    return 2 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
