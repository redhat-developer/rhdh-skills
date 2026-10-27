#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Inspect RHDH skill setup and state installation plans for the write gate.

`install-plan` states every operation the installer would run: its target, its
exact command, a preview of the change, and what happens on failure. A human
approves that stated set in the conversation, and `apply --confirm` executes it
and reports one outcome for every operation, including the ones it skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_CATALOG = Path(__file__).parent.parent / "assets" / "catalog.json"
HOST_LAYOUTS = (
    Path(".agents/skills"),
    Path(".claude/skills"),
    Path(".cursor/skills"),
    Path(".codex/skills"),
)
OPERATION_FIELDS = frozenset({"order", "target", "command", "preview", "installs", "onFailure"})


def _load_catalog(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("skills"), list):
        raise ValueError(f"Unsupported catalog schema: {path}")
    return payload


def _skill_roots(home: Path, project_root: Path) -> list[Path]:
    roots: list[Path] = []
    for base in (project_root, home):
        roots.extend(base / relative for relative in HOST_LAYOUTS)
    return roots


def _installed_skills(home: Path, project_root: Path) -> dict[str, str]:
    installed: dict[str, str] = {}
    for root in _skill_roots(home, project_root):
        if not root.is_dir():
            continue
        candidates = [*root.glob("*/SKILL.md"), *root.glob("*/*/SKILL.md")]
        for skill_file in candidates:
            installed.setdefault(skill_file.parent.name, str(skill_file.resolve()))
    return installed


def _tool_status(probe: bool) -> dict[str, str]:
    tools = ("npx", "gh", "acli", "gog", "oc", "podman", "docker")
    if not probe:
        return {name: "not-probed" for name in tools}
    return {name: "installed" if shutil.which(name) else "missing" for name in tools}


def setup_status(
    catalog: dict[str, Any], home: Path, project_root: Path, probe_tools: bool
) -> dict[str, Any]:
    installed = _installed_skills(home, project_root)
    promoted = [entry["name"] for entry in catalog["skills"]]
    missing = sorted(name for name in promoted if name not in installed)
    return {
        "installedSkills": sorted(installed),
        "installedSkillLocations": installed,
        "missingSkills": missing,
        "capabilities": {
            "tools": _tool_status(probe_tools),
            "projectConfiguration": "present"
            if (project_root / ".rhdh" / "config.json").is_file()
            else "missing",
            "userConfiguration": "present"
            if (home / ".config" / "rhdh-skills" / "config.json").is_file()
            else "missing",
        },
    }


def _install_flags(agent: str, scope: str) -> list[str]:
    flags = ["--agent", agent]
    if scope == "global":
        flags.append("--global")
    flags.append("--yes")
    return flags


def _on_failure(skill_names: list[str], agent: str, scope: str) -> str:
    removal = " ".join(
        [
            "npx",
            "skills",
            "remove",
            *sorted(skill_names),
            "--agent",
            agent,
            *(["--global"] if scope == "global" else []),
            "--yes",
        ]
    )
    return (
        "Nothing is installed by this operation and every later operation is reported as "
        f"skipped. Undo a partial install with: {removal}"
    )


def _install_operation(
    *,
    order: int,
    command: list[str],
    source: str,
    target: str,
    skill_names: list[str],
    agent: str,
    scope: str,
) -> dict[str, Any]:
    names = sorted(skill_names)
    return {
        "order": order,
        "target": target,
        "command": command,
        "preview": f"Install {len(names)} skills from {source} into {target}: " + ", ".join(names),
        "installs": names,
        "onFailure": _on_failure(names, agent, scope),
    }


def install_plan(
    catalog: dict[str, Any], agent: str, scope: str, pack_url: str | None
) -> dict[str, Any]:
    pack = catalog["pack"]
    resolved_pack_url = pack_url or os.environ.get("RHDH_SKILLS_PACK_URL") or pack.get("url")
    flags = _install_flags(agent, scope)
    target = f"{scope}:{agent}"
    operations: list[dict[str, Any]] = []
    promoted_names = [entry["name"] for entry in catalog["skills"]]

    if resolved_pack_url:
        operations.append(
            _install_operation(
                order=1,
                command=["npx", "skills", "add", resolved_pack_url, *flags],
                source=resolved_pack_url,
                target=target,
                skill_names=promoted_names,
                agent=agent,
                scope=scope,
            )
        )
    else:
        operations.append(
            _install_operation(
                order=1,
                command=[
                    "npx",
                    "skills",
                    "add",
                    pack["source"],
                    "--skill",
                    "*",
                    *flags,
                ],
                source=pack["source"],
                target=target,
                skill_names=promoted_names,
                agent=agent,
                scope=scope,
            )
        )

    return {
        "summary": f"Install the complete RHDH skill set for {agent} ({scope})",
        "operations": operations,
    }


def _operation_error(operation: Any, index: int) -> dict[str, str] | None:
    """Reject anything but a stated `npx skills add` operation.

    The plan arrives as a file, so nothing here trusts it: a command that is not
    an argument array of plain strings, or that names a different program, is a
    way to run something the user never approved.
    """
    rejected = {
        "code": "OPERATION_NOT_ALLOWED",
        "message": f"operation {index} is not an allowed npx skills add operation",
    }
    if not isinstance(operation, dict) or set(operation) != OPERATION_FIELDS:
        return rejected

    command = operation["command"]
    if (
        operation["order"] != index
        or not isinstance(operation["target"], str)
        or not operation["target"].strip()
        or not isinstance(operation["preview"], str)
        or not operation["preview"].strip()
        or not isinstance(operation["onFailure"], str)
        or not operation["onFailure"].strip()
        or not isinstance(operation["installs"], list)
        or not all(isinstance(name, str) and name.strip() for name in operation["installs"])
        or not isinstance(command, list)
        or len(command) < 4
        or command[:3] != ["npx", "skills", "add"]
        or not all(isinstance(item, str) and "\x00" not in item for item in command)
        or not command[3]
        or command[3].startswith("-")
    ):
        return rejected
    return None


def _plan_errors(plan: Any) -> list[dict[str, str]]:
    """Validate a plan read back from a file before any of it runs."""
    if not isinstance(plan, dict) or set(plan) != {"summary", "operations"}:
        return [{"code": "PLAN_INVALID", "message": "plan must state a summary and operations"}]
    if not isinstance(plan["summary"], str) or not plan["summary"].strip():
        return [{"code": "PLAN_INVALID", "message": "plan summary must be a non-empty string"}]
    operations = plan["operations"]
    if not isinstance(operations, list) or not operations:
        return [{"code": "PLAN_INVALID", "message": "plan must state at least one operation"}]
    for index, operation in enumerate(operations, start=1):
        error = _operation_error(operation, index)
        if error:
            return [error]
    return []


def _resolve_npx_command(argv: list[str]) -> list[str]:
    """Resolve npx without passing plan material through a command shell."""
    npx = (
        shutil.which("npx.cmd") or shutil.which("npx")
        if sys.platform == "win32"
        else shutil.which("npx")
    )
    if not npx:
        raise OSError("npx not found on PATH")

    npx_path = Path(npx)
    if sys.platform != "win32" or npx_path.suffix.lower() not in {".cmd", ".bat"}:
        return [npx, *argv[1:]]

    node = shutil.which("node.exe") or shutil.which("node")
    candidates = [
        npx_path.parent / "node_modules" / "npm" / "bin" / "npx-cli.js",
        npx_path.resolve().parent / "node_modules" / "npm" / "bin" / "npx-cli.js",
    ]
    npx_cli = next((candidate for candidate in candidates if candidate.is_file()), None)
    if not node or not npx_cli:
        raise OSError("cannot safely resolve the Windows npx wrapper to node and npx-cli.js")
    return [node, str(npx_cli), *argv[1:]]


def apply_plan(plan: dict[str, Any], *, confirmed: bool) -> tuple[dict[str, Any], int]:
    """Run a confirmed plan and report one outcome for every stated operation."""
    errors = _plan_errors(plan)
    if errors:
        return {"valid": False, "errors": errors}, 1
    if not confirmed:
        return {
            "valid": False,
            "errors": [
                {
                    "code": "NOT_CONFIRMED",
                    "message": "state the plan, get approval, then re-run with --confirm",
                }
            ],
        }, 1

    operations = plan["operations"]
    outcomes: list[dict[str, Any]] = []
    for operation in operations:
        command = _resolve_npx_command(operation["command"])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )
        outcomes.append(
            {
                "order": operation["order"],
                "target": operation["target"],
                "preview": operation["preview"],
                "status": "completed" if completed.returncode == 0 else "failed",
                "returnCode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        if completed.returncode != 0:
            break

    for operation in operations[len(outcomes) :]:
        outcomes.append(
            {
                "order": operation["order"],
                "target": operation["target"],
                "preview": operation["preview"],
                "status": "skipped",
                "returnCode": None,
                "stdout": "",
                "stderr": "not attempted after an earlier operation failed",
            }
        )

    succeeded = all(outcome["status"] == "completed" for outcome in outcomes)
    return {
        "summary": plan["summary"],
        "outcomes": outcomes,
        "valid": succeeded,
    }, 0 if succeeded else 1


def _add_shared_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--catalog", type=Path, default=DEFAULT_CATALOG, help="Catalog JSON to inspect"
    )


def _emit(payload: dict[str, Any], force_json: bool) -> None:
    if force_json or not sys.stdout.isatty():
        json.dump(payload, sys.stdout, indent=2 if force_json else None)
        sys.stdout.write("\n")
    elif payload.get("valid", True):
        print(payload.get("summary", "Setup check complete"))
    else:
        for error in payload.get("errors", []):
            print(f"{error['code']}: {error['message']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect, plan, and apply setup for the complete RHDH skills collection."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Report installed skills and setup capabilities")
    _add_shared_paths(doctor)
    doctor.add_argument("--home", type=Path, default=Path.home(), help="User home to inspect")
    doctor.add_argument(
        "--project-root", type=Path, default=Path.cwd(), help="Project root to inspect"
    )
    doctor.add_argument(
        "--no-tool-probes", action="store_true", help="Skip PATH-based tool detection"
    )
    doctor.add_argument("--json", action="store_true", help="Emit structured JSON output")

    plan = subparsers.add_parser("install-plan", help="State the operations an install would run")
    _add_shared_paths(plan)
    plan.add_argument("--pack-url", help="Override the catalog pack URL")
    plan.add_argument("--agent", required=True, help="skills CLI agent identifier")
    plan.add_argument(
        "--scope", choices=("project", "global"), default="global", help="Installation scope"
    )
    plan.add_argument("--json", action="store_true", help="Emit structured JSON output")

    apply_parser = subparsers.add_parser("apply", help="Run a plan the user approved")
    apply_parser.add_argument("--plan", type=Path, required=True, help="Install plan JSON file")
    apply_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm that the user approved this exact plan",
    )
    apply_parser.add_argument("--json", action="store_true", help="Emit structured JSON output")

    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            catalog = _load_catalog(args.catalog)
            payload = setup_status(
                catalog, args.home, args.project_root, probe_tools=not args.no_tool_probes
            )
            code = 0 if not payload["missingSkills"] else 1
        elif args.command == "install-plan":
            catalog = _load_catalog(args.catalog)
            payload = install_plan(catalog, args.agent, args.scope, args.pack_url)
            code = 0
        else:
            plan_payload = json.loads(args.plan.read_text(encoding="utf-8"))
            payload, code = apply_plan(plan_payload, confirmed=args.confirm)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {"valid": False, "errors": [{"code": "SETUP_INPUT", "message": str(exc)}]}
        code = 1

    _emit(payload, args.json)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
