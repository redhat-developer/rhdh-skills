#!/usr/bin/env python3
"""Summarize Jira, GitHub, and catalog state for an OSL bump."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "references" / "osl-releases.json"


def command_exists(command: str) -> bool:
    """Return whether a command is available on PATH."""
    return shutil.which(command) is not None


def run_command(
    command: list[str],
    *,
    timeout: int = 30,
) -> tuple[bool, Any, str]:
    """Run a command and parse JSON output when possible."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, str(exc)

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        return (
            False,
            None,
            stderr or stdout or (f"command exited with status {completed.returncode}"),
        )

    if not stdout:
        return True, None, ""

    try:
        return True, json.loads(stdout), ""
    except json.JSONDecodeError:
        return True, stdout, ""


def read_json_file(path: str | None) -> tuple[bool, Any, str]:
    """Read JSON supplied by an MCP adapter or test fixture."""
    if not path:
        return False, None, "no input file supplied"

    input_path = Path(path)
    if not input_path.is_file():
        return False, None, f"input file does not exist: {input_path}"

    try:
        return True, json.loads(input_path.read_text()), ""
    except (OSError, json.JSONDecodeError) as exc:
        return False, None, f"could not read JSON input {input_path}: {exc}"


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: invalid configuration {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise SystemExit(f"error: configuration must be a JSON object: {path}")

    return value


def issue_keys(config: dict[str, Any], source_issue: str) -> list[str]:
    """Return the source issue plus configured related issue keys."""
    configured = config.get("jira", {}).get("reference_issues", [])
    keys = [source_issue]

    for key in configured:
        if key not in keys:
            keys.append(key)

    return keys


def fetch_jira_issue(
    issue: str,
    *,
    jira_json: str | None,
) -> dict[str, Any]:
    """
    Fetch Jira data.

    Preferred path:
      - MCP adapter output supplied through --jira-json.

    Fallback:
      - authenticated acli Jira read.

    This function is deliberately read-only.
    """
    if jira_json:
        ok, data, error = read_json_file(jira_json)
        if ok:
            return {
                "issue": issue,
                "source": "atlassian-mcp-json",
                "available": True,
                "data": data,
            }

        return {
            "issue": issue,
            "source": "atlassian-mcp-json",
            "available": False,
            "error": error,
        }

    if not command_exists("acli"):
        return {
            "issue": issue,
            "source": "acli",
            "available": False,
            "error": "acli is not installed",
        }

    ok, data, error = run_command(
        [
            "acli",
            "jira",
            "workitem",
            "view",
            issue,
            "--fields",
            "*all",
            "--json",
        ]
    )

    return {
        "issue": issue,
        "source": "acli",
        "available": ok,
        "data": data if ok else None,
        "error": error if not ok else None,
    }


def extract_pr_links(value: Any) -> list[str]:
    """Find GitHub pull-request URLs in arbitrary Jira JSON."""
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, list):
        values = value
    elif isinstance(value, str):
        values = [value]
    else:
        return []

    links: list[str] = []

    for item in values:
        if isinstance(item, str):
            words = item.replace("(", " ").replace(")", " ").split()
            for word in words:
                if "github.com/" in word and "/pull/" in word:
                    cleaned = word.strip("\"'<>[],.")
                    if cleaned not in links:
                        links.append(cleaned)
        else:
            for link in extract_pr_links(item):
                if link not in links:
                    links.append(link)

    return links


def fetch_github_prs(
    *,
    issue_keys: list[str],
    repositories: list[str],
    github_json: str | None,
) -> dict[str, Any]:
    """Find related PRs by Jira issue key using GitHub MCP JSON or gh."""
    if github_json:
        ok, data, error = read_json_file(github_json)
        return {
            "source": "github-mcp-json",
            "available": ok,
            "pull_requests": data if ok else [],
            "error": error if not ok else None,
        }

    if not command_exists("gh"):
        return {
            "source": "gh",
            "available": False,
            "pull_requests": [],
            "error": "gh is not installed",
        }

    all_prs: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()

    fields = (
        "number,title,state,isDraft,baseRefName,headRefName,"
        "mergedAt,labels,reviewDecision,statusCheckRollup,url"
    )

    for repository in repositories:
        for issue_key in issue_keys:
            ok, data, error = run_command(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repository,
                    "--state",
                    "all",
                    "--limit",
                    "100",
                    "--search",
                    f"{issue_key} in:title,body",
                    "--json",
                    fields,
                ],
                timeout=60,
            )

            if not ok:
                continue

            if not isinstance(data, list):
                continue

            for pr in data:
                if not isinstance(pr, dict):
                    continue

                identity = (repository, pr.get("number"))
                if identity in seen:
                    continue

                seen.add(identity)
                all_prs.append(
                    {
                        "repository": repository,
                        "matched_issue": issue_key,
                        **pr,
                    }
                )

    return {
        "source": "gh",
        "available": True,
        "pull_requests": all_prs,
        "error": None,
    }


def fetch_catalog(
    *,
    catalog_json: str | None,
    package_name: str,
    namespace: str,
) -> dict[str, Any]:
    """
    Read catalog data.

    Preferred path:
      - catalog JSON supplied by an MCP/oc adapter.

    Fallback:
      - oc get packagemanifest.
    """
    if catalog_json:
        ok, data, error = read_json_file(catalog_json)
        return {
            "source": "catalog-json",
            "available": ok,
            "package_name": package_name,
            "namespace": namespace,
            "data": data if ok else None,
            "error": error if not ok else None,
        }

    if not command_exists("oc"):
        return {
            "source": "oc",
            "available": False,
            "package_name": package_name,
            "namespace": namespace,
            "data": None,
            "error": "oc is not installed",
        }

    ok, data, error = run_command(
        [
            "oc",
            "get",
            "packagemanifest",
            package_name,
            "-n",
            namespace,
            "-o",
            "json",
        ],
        timeout=60,
    )

    return {
        "source": "oc",
        "available": ok,
        "package_name": package_name,
        "namespace": namespace,
        "data": data if ok else None,
        "error": error if not ok else None,
    }


def build_gates(config: dict[str, Any]) -> list[dict[str, Any]]:
    gates = config.get("human_gates", {})
    required = gates.get("requires_human_approval_for", [])

    return [
        {
            "name": action,
            "status": "human_approval_required",
        }
        for action in required
    ]


def build_summary(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(Path(args.config))

    jira_keys = issue_keys(config, args.issue)

    jira_results = [fetch_jira_issue(issue, jira_json=args.jira_json) for issue in jira_keys]

    repositories = [
        config["repositories"]["chart"]["github"],
        config["repositories"]["operator"]["github"],
    ]

    github_result = fetch_github_prs(
        issue_keys=jira_keys,
        repositories=repositories,
        github_json=args.github_json,
    )

    catalog_config = config["catalog"]
    catalog_result = fetch_catalog(
        catalog_json=args.catalog_json,
        package_name=catalog_config["package_name"],
        namespace=catalog_config["namespace"],
    )

    capabilities = {
        "jira": all(item["available"] for item in jira_results),
        "github": github_result["available"],
        "catalog": catalog_result["available"],
    }

    blockers: list[str] = []

    if not capabilities["jira"]:
        blockers.append("Jira data is unavailable")

    if not capabilities["github"]:
        blockers.append("GitHub PR data is unavailable")

    if not capabilities["catalog"]:
        blockers.append("catalog data is unavailable")

    return {
        "schema_version": 1,
        "status": "blocked" if blockers else "available",
        "issue": args.issue,
        "capabilities": capabilities,
        "blockers": blockers,
        "jira": jira_results,
        "github": github_result,
        "catalog": catalog_result,
        "human_gates": build_gates(config),
        "policy": {"jira_is_not_catalog_truth": catalog_config["jira_is_not_catalog_truth"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize OSL Jira, GitHub, and catalog state.")
    parser.add_argument(
        "--issue",
        required=True,
        help="root Jira issue, for example RHIDP-17562",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="path to osl-releases.json",
    )
    parser.add_argument(
        "--jira-json",
        help="JSON file produced by the Atlassian MCP adapter",
    )
    parser.add_argument(
        "--github-json",
        help="JSON file produced by the GitHub MCP adapter",
    )
    parser.add_argument(
        "--catalog-json",
        help="JSON file produced by oc or a catalog adapter",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )
    args = parser.parse_args()

    result = build_summary(args)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"OSL status for {result['issue']}: {result['status']}")

        for blocker in result["blockers"]:
            print(f"BLOCKED: {blocker}")

        print(
            "Jira issues read: "
            f"{sum(item['available'] for item in result['jira'])}/"
            f"{len(result['jira'])}"
        )

        print(f"Related pull requests: {len(result['github']['pull_requests'])}")

        print(
            "Catalog source: "
            f"{result['catalog']['source']} "
            f"available={result['catalog']['available']}"
        )

    return 0 if result["status"] == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
