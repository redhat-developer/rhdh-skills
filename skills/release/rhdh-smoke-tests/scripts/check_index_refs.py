#!/usr/bin/env python3
"""Assert every plugin the catalog index names is pullable from RHEC.

Run before installing. install-dynamic-plugins falls back from
registry.access.redhat.com to quay.io when a manifest is missing, so an index
naming refs that were never pushed to RHEC still installs cleanly and quietly
serves whatever quay has. Nothing downstream reveals it, which is how RHDH
1.10.4 shipped. Checking the index itself is the only place this is visible
before it reaches a customer.

    check_index_refs.py --index registry.access.redhat.com/rhdh/plugin-catalog-index:1.10
    check_index_refs.py --index <ref> --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

RHEC = "registry.access.redhat.com/rhdh/"
FALLBACK = "quay.io/rhdh/"
OCI_REF = re.compile(r"oci://(\S+?)(?:!|\s|$)")


def run(*args: str) -> tuple[int, bytes, str]:
    p = subprocess.run(args, capture_output=True)
    return p.returncode, p.stdout, p.stderr.decode(errors="replace")


def extract_default_yaml(index: str, workdir: Path) -> str | None:
    """Pull the index and return dynamic-plugins.default.yaml from its layers."""
    rc, _, err = run(
        "skopeo",
        "copy",
        "--override-os",
        "linux",
        "--override-arch",
        "amd64",
        "--quiet",
        f"docker://{index}",
        f"dir:{workdir}",
    )
    if rc != 0:
        print(
            f"error: cannot pull {index}: {err.strip().splitlines()[-1] if err else rc}",
            file=sys.stderr,
        )
        return None

    manifest = json.loads((workdir / "manifest.json").read_text())
    for layer in manifest["layers"]:
        blob = workdir / layer["digest"].split(":")[1]
        try:
            with tarfile.open(blob) as tar:
                for member in tar.getnames():
                    if member.endswith("dynamic-plugins.default.yaml"):
                        handle = tar.extractfile(member)
                        if handle:
                            return handle.read().decode(errors="replace")
        except tarfile.TarError:
            continue
    return None


def pullable(ref: str) -> bool:
    rc, _, _ = run("skopeo", "inspect", "--raw", f"docker://{ref}")
    return rc == 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--index", required=True, help="Catalog index image reference")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        content = extract_default_yaml(args.index, Path(tmp))
    if content is None:
        print("error: no dynamic-plugins.default.yaml in the index", file=sys.stderr)
        return 1

    refs = sorted({m for m in OCI_REF.findall(content) if m.startswith(RHEC)})
    unpullable = [r for r in refs if not pullable(r)]
    quay_only = [r for r in unpullable if pullable(r.replace(RHEC, FALLBACK, 1))]

    result = {
        "index": args.index,
        "rhec_refs": len(refs),
        "unpullable": unpullable,
        "reachable_only_via_quay": quay_only,
        "ok": not unpullable,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"index               {args.index}")
        print(f"RHEC refs           {len(refs)}")
        print(f"not pullable        {len(unpullable)}")
        for ref in unpullable:
            tail = ref.split("/")[-1]
            note = "   (present on quay - the fallback would hide this)" if ref in quay_only else ""
            print(f"  {tail}{note}")
        if result["ok"]:
            print("result              OK - every ref resolves from RHEC")
        else:
            print("result              FAIL - do not ship this index")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
