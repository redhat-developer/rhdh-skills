#!/usr/bin/env python3
"""Plan, apply, and verify OpenShift Serverless Logic version bumps.

The script deliberately edits only the repository files that are part of the
RHDH chart/operator OSL release path. It is dependency-free and safe to run in
CI or from a checkout of either repository.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, NoReturn

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "references" / "osl-releases.json"

CHART_FILES = (
    "charts/orchestrator-infra/Chart.yaml",
    "charts/orchestrator-infra/README.md",
    "charts/orchestrator-infra/README.md.gotmpl",
    "charts/orchestrator-infra/values.yaml",
    "charts/orchestrator-infra/values.schema.json",
    "charts/orchestrator-infra/values.schema.tmpl.json",
)
OPERATOR_FILES = (
    "config/profile/rhdh/plugin-infra/serverless-logic.yaml",
    "config/profile/rhdh/plugin-infra/serverless-logic-v1.yaml",
    "config/profile/rhdh/plugin-deps/tekton.yaml",
    "bundle/rhdh/manifests/rhdh-plugin-deps_v1_configmap.yaml",
    "dist/rhdh/install.yaml",
)


@dataclass(frozen=True)
class Change:
    path: Path
    old: str
    new: str
    replacements: int


def fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def parse_version(value: str) -> str:
    if not SEMVER.fullmatch(value):
        fail(f"OSL version must be MAJOR.MINOR.PATCH, got {value!r}")
    return value


def require_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file():
        fail(f"missing expected file: {path}")
    return path


def replace_checked(path: Path, pattern: str, replacement: str, label: str) -> Change:
    text = path.read_text()
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count == 0:
        fail(f"could not find {label} in {path}")
    if count > 1 and path.name == "Chart.yaml":
        fail(f"found {count} chart versions in {path}; refusing to guess")
    return Change(path, text, updated, count)


def chart_version(path: Path) -> str:
    match = re.search(r"^version:\s*([^\s#]+)\s*$", path.read_text(), re.MULTILINE)
    if not match:
        fail(f"could not read chart version from {path}")
    return match.group(1)


def bump_patch(version: str) -> str:
    match = SEMVER.fullmatch(version)
    if not match:
        fail(f"chart version is not MAJOR.MINOR.PATCH: {version!r}")
    major, minor, patch = map(int, match.groups())
    return f"{major}.{minor}.{patch + 1}"


def release_branches(config_path: Path, release: str) -> dict[str, str]:
    """Return the expected branch per repository for a release line."""
    try:
        config = json.loads(Path(config_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"could not read {config_path}: {exc}")
    lines = config.get("release_lines", {})
    if release not in lines:
        fail(f"unknown release line {release!r}; expected one of {sorted(lines)}")
    return lines[release]


def current_branch(repo: Path) -> str | None:
    """Return the checked-out branch, or None for detached HEAD or a failed call."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return None if branch in {"", "HEAD"} else branch


def chart_changes(root: Path, osl: str, new_chart_version: str | None) -> list[Change]:
    paths = {relative: require_file(root, relative) for relative in CHART_FILES}
    current_chart = chart_version(paths[CHART_FILES[0]])
    chart = new_chart_version or bump_patch(current_chart)
    if not SEMVER.fullmatch(chart):
        fail(f"chart version must be MAJOR.MINOR.PATCH, got {chart!r}")

    replacements = {
        CHART_FILES[0]: [
            (r"^(version:)\s*[^\s#]+\s*$", rf"\g<1> {chart}", "chart version"),
        ],
        CHART_FILES[1]: [
            (r"(Version:\s*)\d+\.\d+\.\d+", rf"\g<1>{chart}", "README chart badge"),
            (r"(--version )\d+\.\d+\.\d+", rf"\g<1>{chart}", "README install version"),
            (r"(logic-operator\.v)\d+\.\d+\.\d+", rf"\g<1>{osl}", "README startingCSV"),
            (r"(serverless-operator-bundle:)\d+\.\d+\.\d+", rf"\g<1>{osl}", "README bundle tag"),
        ],
        CHART_FILES[2]: [
            (
                r"(serverless-operator-bundle:)\d+\.\d+\.\d+",
                rf"\g<1>{osl}",
                "README template bundle tag",
            ),
        ],
        CHART_FILES[3]: [
            (
                r"(startingCSV:\s*logic-operator\.v)\d+\.\d+\.\d+",
                rf"\g<1>{osl}",
                "values startingCSV",
            ),
        ],
        CHART_FILES[4]: [
            (
                r'("default":\s*"logic-operator\.v)\d+\.\d+\.\d+("?)',
                rf"\g<1>{osl}\g<2>",
                "schema startingCSV",
            ),
        ],
        CHART_FILES[5]: [
            (
                r'("default":\s*"logic-operator\.v)\d+\.\d+\.\d+("?)',
                rf"\g<1>{osl}\g<2>",
                "schema template startingCSV",
            ),
        ],
    }
    changes: list[Change] = []
    for relative, file_replacements in replacements.items():
        path = paths[relative]
        original = text = path.read_text()
        for pattern, replacement, label in file_replacements:
            text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
            if count == 0:
                fail(f"could not find {label} in {path}")
            if count > 1 and relative == CHART_FILES[0]:
                fail(f"found {count} chart versions in {path}; refusing to guess")
        changes.append(Change(path, original, text, sum(original != text for _ in [0])))
    return changes


def operator_changes(root: Path, osl: str, kn_version: str | None) -> list[Change]:
    """Plan edits for the operator checkout.

    ``kn_version`` is the kn-workflow tool tag, which is *not* the operator
    version: OSL rebuilds have shipped a CSV newer than the tool (SRVLOGIC-1303).
    ``None`` means preserve whatever pin is checked in.
    """
    paths = {relative: require_file(root, relative) for relative in OPERATOR_FILES}
    changes: list[Change] = []

    # Required: OLM v0 Subscription.
    changes.append(
        replace_checked(
            paths[OPERATOR_FILES[0]],
            r"(startingCSV:\s*logic-operator\.v)\d+\.\d+\.\d+",
            rf"\g<1>{osl}",
            "operator startingCSV",
        )
    )

    # Required: OLM v1 ClusterExtension. Same fact, different schema.
    changes.append(
        replace_checked(
            paths[OPERATOR_FILES[1]],
            r'(version:\s*")\d+\.\d+\.\d+(")',
            rf"\g<1>{osl}\g<2>",
            "operator OLM v1 version",
        )
    )

    # Conditional: the kn-workflow tool tag in source and its two generated copies.
    kn_files = (OPERATOR_FILES[2], OPERATOR_FILES[3], OPERATOR_FILES[4])
    labels = {
        OPERATOR_FILES[2]: "plugin dependency kn-workflow URL",
        OPERATOR_FILES[3]: "generated bundle kn-workflow URL",
        OPERATOR_FILES[4]: "generated install kn-workflow URL",
    }
    for relative in kn_files:
        path = paths[relative]
        original = text = path.read_text()
        if kn_version is None:
            # Keep the checked-in pin; only refresh the note naming the operator.
            text, _ = re.subn(
                r"(OSL Operator needed to be bumped to )\d+\.\d+\.\d+",
                rf"\g<1>{osl}",
                text,
                flags=re.MULTILINE,
            )
        else:
            text, count = re.subn(
                r"(serverless-logic/)\d+\.\d+\.\d+(/kn-workflow-linux-amd64\.tar\.gz)",
                rf"\g<1>{kn_version}\g<2>",
                text,
                flags=re.MULTILINE,
            )
            if count == 0:
                fail(f"could not find {labels[relative]} in {path}")
        changes.append(Change(path, original, text, 1 if original != text else 0))

    return changes


def apply_changes(changes: Iterable[Change], write: bool) -> None:
    seen: set[Path] = set()
    for change in changes:
        if change.path in seen:
            continue
        seen.add(change.path)
        if change.old == change.new:
            print(f"unchanged {change.path}")
            continue
        if write:
            change.path.write_text(change.new)
            print(f"updated {change.path}")
        else:
            print(f"would update {change.path}")


def verify_chart(root: Path, osl: str) -> list[str]:
    errors: list[str] = []
    for relative in CHART_FILES:
        path = require_file(root, relative)
        text = path.read_text()
        if relative.endswith("Chart.yaml"):
            continue
        if "README" in relative and "gotmpl" not in relative:
            expected = [f"logic-operator.v{osl}", f"serverless-operator-bundle:{osl}"]
        elif "gotmpl" in relative:
            expected = [f"serverless-operator-bundle:{osl}"]
        else:
            expected = [f"logic-operator.v{osl}"]
        for token in expected:
            if token not in text:
                errors.append(f"{root / relative}: missing {token}")
    return errors


def verify_operator(root: Path, osl: str, kn_version: str | None) -> list[str]:
    """Check the operator checkout agrees with itself about target version."""
    errors: list[str] = []

    csv_path = require_file(root, OPERATOR_FILES[0])
    if f"logic-operator.v{osl}" not in csv_path.read_text():
        errors.append(f"{csv_path}: missing logic-operator.v{osl}")

    v1_path = require_file(root, OPERATOR_FILES[1])
    if not re.search(rf'version:\s*"{re.escape(osl)}"', v1_path.read_text()):
        errors.append(f'{v1_path}: missing version: "{osl}"')

    kn_pattern = re.compile(r"serverless-logic/(\d+\.\d+\.\d+)/kn-workflow-linux-amd64\.tar\.gz")
    seen_tags: set[str] = set()
    for relative in (OPERATOR_FILES[2], OPERATOR_FILES[3], OPERATOR_FILES[4]):
        path = require_file(root, relative)
        tags = set(kn_pattern.findall(path.read_text()))
        if not tags:
            errors.append(f"{path}: missing kn-workflow URL")
            continue
        if len(tags) > 1:
            errors.append(f"{path}: inconsistent kn-workflow tags {sorted(tags)}")
        seen_tags |= tags
        if kn_version is not None and tags != {kn_version}:
            errors.append(f"{path}: kn-workflow is {sorted(tags)}, expected {kn_version}")

    if len(seen_tags) > 1:
        errors.append(
            f"kn-workflow tags disagree across source and generated files: {sorted(seen_tags)}"
        )

    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "verify"))
    parser.add_argument("--version", required=True, help="new OSL version, for example 1.38.1")
    parser.add_argument("--chart-repo", type=Path, help="checkout of redhat-developer/rhdh-chart")
    parser.add_argument(
        "--operator-repo", type=Path, help="checkout of redhat-developer/rhdh-operator"
    )
    parser.add_argument(
        "--chart-version", help="chart version; defaults to incrementing its patch version"
    )
    parser.add_argument(
        "--kn-workflow-version",
        help="kn-workflow tool tag; defaults to preserving the checked-in pin",
    )
    parser.add_argument(
        "--release",
        choices=("1.9", "1.10", "main"),
        help="release line; validates each checkout is on its expected branch",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="path to osl-releases.json",
    )
    parser.add_argument("--write", action="store_true", help="required by apply to modify files")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable plan summary")
    args = parser.parse_args(argv)
    osl = parse_version(args.version)
    kn_version = parse_version(args.kn_workflow_version) if args.kn_workflow_version else None
    if not args.chart_repo and not args.operator_repo:
        fail("provide --chart-repo, --operator-repo, or both")
    if args.action == "apply" and not args.write:
        fail("apply is dry-run by default; pass --write to modify files")
    if args.release:
        expected = release_branches(args.config, args.release)
        for kind, repo in (("chart", args.chart_repo), ("operator", args.operator_repo)):
            if repo is None:
                continue
            want = expected.get(f"{kind}_branch")
            branch = current_branch(repo)
            if branch is None:
                print(f"note: cannot read the branch of {repo}; release check skipped")
            elif branch != want:
                fail(f"{repo} is on {branch!r}; release {args.release} expects {want!r}")
    changes: list[Change] = []
    if args.chart_repo:
        changes.extend(chart_changes(args.chart_repo, osl, args.chart_version))
    if args.operator_repo:
        changes.extend(operator_changes(args.operator_repo, osl, kn_version))

    if args.action in ("plan", "apply"):
        apply_changes(changes, write=args.write)
        if args.json:
            print(
                json.dumps(
                    {"version": osl, "files": sorted({str(c.path) for c in changes})}, indent=2
                )
            )
        return 0

    errors: list[str] = []
    if args.chart_repo:
        errors.extend(verify_chart(args.chart_repo, osl))
    if args.operator_repo:
        errors.extend(verify_operator(args.operator_repo, osl, kn_version))
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: all selected OSL references are {osl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
