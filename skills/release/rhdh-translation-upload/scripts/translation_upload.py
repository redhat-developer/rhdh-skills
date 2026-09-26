#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Extract translation strings and prepare delta for TMS upload.

Runs the translations-cli against each repo, diffs against the SOT in
rhdh/translations/, and produces upload-ready delta JSON files containing
only new keys.

Usage:
    uv run scripts/translation_upload.py preflight
    uv run scripts/translation_upload.py extract --sprint s4000
    uv run scripts/translation_upload.py extract --sprint s4000 --json
    uv run scripts/translation_upload.py delta --sprint s4000
    uv run scripts/translation_upload.py delta --sprint s4000 --json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from _support import (  # noqa: E402
    OutputFormatter,
    apply_rhdh_overrides,
    build_delta_reference,
    check_tms_credentials,
    compute_delta,
    find_all_repos,
    find_en_sot_dir,
    find_memsource_cli,
    find_node_tool,
    find_translations_cli,
    git_current_branch,
    git_is_clean,
    load_reference_keys,
    load_sot_english_values,
    load_sot_keys,
)

# Per-repo generation configuration.
# source_dir: where the CLI should scan for translation keys.
# core_plugins: whether to use --core-plugins mode (Backstage repo only).
# keep_plugins: when set, only these plugins are kept from the extraction.
#   - rhdh: bundles all plugins but only "rhdh" is its own contribution.
#   - community-plugins: only Red Hat-owned plugins are sent for translation.
REPO_CONFIG: dict[str, dict[str, Any]] = {
    "rhdh-plugins": {"source_dir": "workspaces"},
    "rhdh": {"source_dir": "packages", "keep_plugins": ["rhdh"]},
    "community-plugins": {
        "source_dir": "workspaces",
        "keep_plugins": [
            "plugin.acr",
            "plugin.argocd",
            "plugin.jfrog-artifactory",
            "plugin.nexus-repository-manager",
            "plugin.npm.translation-ref",
            "plugin.rbac",
            "plugin.servicenow",
            "plugin.topology",
            "tekton",
        ],
    },
    "backstage": {"core_plugins": True},
}


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Check all prerequisites for the translation workflow."""
    search_root = args.search_root
    repos = find_all_repos(search_root=search_root)
    checks: list[dict[str, Any]] = []

    # 1. Repo paths
    for name, path in repos.items():
        ok = path is not None
        check = {
            "name": f"repo_{name}",
            "ok": ok,
            "detail": str(path) if ok else f"{name} not found",
        }
        checks.append(check)
        if ok:
            fmt.log_ok(f"{name}: {path}")
        else:
            fmt.log_fail(f"{name}: not found")

    # 2. Git clean state
    for name, path in repos.items():
        if path is None:
            continue
        clean = git_is_clean(path)
        branch = git_current_branch(path)
        check = {
            "name": f"git_clean_{name}",
            "ok": clean,
            "detail": f"branch={branch}, clean={clean}",
        }
        checks.append(check)
        if clean:
            fmt.log_ok(f"{name} git: clean on {branch}")
        else:
            fmt.log_warn(f"{name} git: uncommitted changes on {branch}")

    # 3. translations-cli
    rhdh_plugins = repos.get("rhdh-plugins")
    cli_path: Optional[Path] = None
    if rhdh_plugins:
        cli_path = find_translations_cli(rhdh_plugins)
    cli_ok = cli_path is not None
    checks.append(
        {
            "name": "translations_cli",
            "ok": cli_ok,
            "detail": str(cli_path) if cli_ok else "translations-cli not found",
        }
    )
    if cli_ok:
        fmt.log_ok(f"translations-cli: {cli_path}")
    else:
        fmt.log_fail("translations-cli: not found in rhdh-plugins")

    # 4. Node tools
    for tool in ("node", "npx", "yarn"):
        found = find_node_tool(tool)
        checks.append(
            {
                "name": f"tool_{tool}",
                "ok": found is not None,
                "detail": found or f"{tool} not on PATH",
            }
        )
        if found:
            fmt.log_ok(f"{tool}: {found}")
        else:
            fmt.log_warn(f"{tool}: not on PATH")

    # 5. TMS credentials
    creds = check_tms_credentials()
    any_cred = any(creds.values())
    checks.append(
        {
            "name": "tms_credentials",
            "ok": any_cred,
            "detail": {k: v for k, v in creds.items()},
        }
    )
    if any_cred:
        fmt.log_ok(f"TMS credentials: {creds}")
    else:
        fmt.log_warn("TMS credentials: none set")

    # 6. Memsource CLI
    mem_cli = find_memsource_cli()
    checks.append(
        {
            "name": "memsource_cli",
            "ok": mem_cli is not None,
            "detail": mem_cli or "memsource not on PATH",
        }
    )
    if mem_cli:
        fmt.log_ok(f"memsource CLI: {mem_cli}")
    else:
        fmt.log_warn("memsource CLI: not on PATH")

    # 7. SOT directory
    rhdh_repo = repos.get("rhdh")
    sot_ok = False
    if rhdh_repo:
        sot_dir = rhdh_repo / "translations"
        sot_ok = sot_dir.is_dir()
    checks.append(
        {
            "name": "sot_directory",
            "ok": sot_ok,
            "detail": str(rhdh_repo / "translations") if rhdh_repo else "rhdh repo not found",
        }
    )
    if sot_ok:
        fmt.log_ok(f"SOT: {rhdh_repo / 'translations'}")
    else:
        fmt.log_fail("SOT: rhdh/translations/ not found")

    all_ok = all(c["ok"] for c in checks)
    next_steps = []
    if not all_ok:
        for c in checks:
            if not c["ok"]:
                next_steps.append(f"Fix: {c['name']} — {c['detail']}")

    fmt.success({"checks": checks, "all_ok": all_ok}, next_steps=next_steps)


def _run_generate(
    repo_name: str,
    repo_path: Path,
    sprint: str,
    cli_path: Path,
    fmt: OutputFormatter,
    *,
    backstage_repo_path: Optional[Path] = None,
) -> Optional[Path]:
    """Run translations-cli i18n generate for a single repo.

    Returns the path to the generated reference file, or None on failure.
    """
    output_dir = repo_path / "i18n"
    output_dir.mkdir(exist_ok=True)

    cfg = REPO_CONFIG.get(repo_name, {})

    cmd = [
        "node",
        str(cli_path),
        "i18n",
        "generate",
        "--sprint",
        sprint,
        "--output-dir",
        str(output_dir),
    ]

    # Per-repo source directory (workspaces/, packages/, etc.)
    if "source_dir" in cfg:
        cmd.extend(["--source-dir", cfg["source_dir"]])

    # Backstage uses --core-plugins mode with its own repo path
    if cfg.get("core_plugins"):
        cmd.append("--core-plugins")
        if backstage_repo_path:
            cmd.extend(["--backstage-repo-path", str(backstage_repo_path)])

    fmt.log_info(f"Extracting {repo_name}: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(repo_path),
        env={**os.environ, "NODE_OPTIONS": "--max-old-space-size=4096"},
    )

    if result.returncode != 0:
        fmt.log_fail(f"{repo_name} extraction failed:\n{result.stderr}")
        return None

    fmt.log_ok(f"{repo_name} extraction succeeded")

    # Find the generated file
    normalized_sprint = sprint.lower() if sprint.startswith("s") else f"s{sprint}"
    expected_name = f"{repo_name.lower()}-{normalized_sprint}.json"
    generated = output_dir / expected_name

    if generated.exists():
        return generated

    # Fallback: find any recently generated JSON
    candidates = sorted(output_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]

    fmt.log_fail(f"{repo_name}: no generated file found in {output_dir}")
    return None


def _filter_reference_file(
    ref_file: Path,
    keep_plugins: list[str],
    fmt: OutputFormatter,
    repo_name: str,
) -> None:
    """Rewrite a reference JSON to keep only the listed plugins.

    The rhdh repo bundles all plugins into its extraction output, but only
    the plugins listed in keep_plugins belong to it — the rest come from
    other repos and would cause duplicates in TMS.
    """
    try:
        data = json.loads(ref_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    keep_set = set(keep_plugins)
    removed = sorted(set(data.keys()) - keep_set)
    if not removed:
        return

    filtered = {k: v for k, v in data.items() if k in keep_set}
    ref_file.write_text(
        json.dumps(filtered, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fmt.log_info(
        f"{repo_name}: filtered to {len(filtered)} plugin(s), "
        f"removed {len(removed)} that belong to other repos"
    )


def _detect_backstage_ref(rhdh_repo: Path, fmt: OutputFormatter) -> Optional[str]:
    """Read the Backstage version from rhdh/backstage.json.

    Returns a tag like ``v1.54.0`` (always the .0 minor release).
    Returns None if the file is missing or unparseable.
    """
    bs_json = rhdh_repo / "backstage.json"
    if not bs_json.exists():
        fmt.log_warn("backstage.json not found in rhdh repo")
        return None
    try:
        data = json.loads(bs_json.read_text(encoding="utf-8"))
        version = data.get("version", "")
    except (json.JSONDecodeError, OSError):
        fmt.log_warn("backstage.json is not valid JSON")
        return None

    if not version:
        return None

    # Use the minor release (e.g. 1.54.4 → v1.54.0)
    parts = version.split(".")
    if len(parts) >= 2:
        return f"v{parts[0]}.{parts[1]}.0"
    return f"v{version}"


def _git_checkout(repo: Path, ref: str, fmt: OutputFormatter) -> Optional[str]:
    """Checkout a ref, returning the previous branch/ref to restore later."""
    prev = git_current_branch(repo)
    if prev == ref or (prev == "HEAD" and ref in ("HEAD",)):
        return prev

    fmt.log_info(f"{repo.name}: checking out {ref}")
    result = subprocess.run(
        ["git", "checkout", ref],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    if result.returncode != 0:
        fmt.log_fail(f"{repo.name}: failed to checkout {ref}: {result.stderr.strip()}")
        return None
    return prev


def _git_restore(repo: Path, ref: str, fmt: OutputFormatter) -> None:
    """Restore a previously checked-out branch."""
    subprocess.run(
        ["git", "checkout", ref],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    fmt.log_info(f"{repo.name}: restored to {ref}")


def cmd_extract(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Run extraction across all repos and report results."""
    sprint = args.sprint
    search_root = args.search_root
    repos = find_all_repos(search_root=search_root)

    missing = [name for name, path in repos.items() if path is None]
    if missing:
        fmt.error(
            f"Repos not found: {', '.join(missing)}",
            next_steps=["Run preflight to check repo paths"],
        )
        sys.exit(1)

    rhdh_plugins = repos["rhdh-plugins"]
    assert rhdh_plugins is not None
    cli_path = find_translations_cli(rhdh_plugins)
    if cli_path is None:
        fmt.error(
            "translations-cli not found",
            next_steps=[
                "Build the translations workspace: "
                "cd rhdh-plugins/workspaces/translations && yarn install && yarn build"
            ],
        )
        sys.exit(1)

    # Detect and checkout the correct Backstage version from rhdh/backstage.json
    rhdh_repo = repos.get("rhdh")
    backstage_path = repos.get("backstage")
    backstage_prev_ref: Optional[str] = None

    if rhdh_repo and backstage_path:
        bs_ref = _detect_backstage_ref(rhdh_repo, fmt)
        if bs_ref:
            fmt.log_info(f"Backstage version from rhdh/backstage.json: {bs_ref}")
            backstage_prev_ref = _git_checkout(backstage_path, bs_ref, fmt)
            if backstage_prev_ref is None:
                fmt.error(
                    f"Failed to checkout backstage {bs_ref}",
                    next_steps=[f"Run: cd backstage && git fetch && git checkout {bs_ref}"],
                )
                sys.exit(1)

    results: dict[str, Any] = {}

    for repo_name in ("rhdh-plugins", "rhdh", "community-plugins", "backstage"):
        repo_path = repos[repo_name]
        assert repo_path is not None

        generated = _run_generate(
            repo_name,
            repo_path,
            sprint,
            cli_path,
            fmt,
            backstage_repo_path=backstage_path,
        )

        if generated:
            keys = load_reference_keys(generated)
            total_keys = sum(len(v) for v in keys.values())
            total_plugins = len(keys)

            if total_keys == 0:
                fmt.log_warn(f"{repo_name}: zero keys extracted — check source")

            results[repo_name] = {
                "file": str(generated),
                "plugins": total_plugins,
                "keys": total_keys,
                "ok": total_keys > 0,
            }
        else:
            results[repo_name] = {
                "file": None,
                "plugins": 0,
                "keys": 0,
                "ok": False,
            }

    # Restore backstage to its original branch
    if backstage_prev_ref and backstage_path:
        _git_restore(backstage_path, backstage_prev_ref, fmt)

    all_ok = all(r["ok"] for r in results.values())
    fmt.success(
        {"sprint": sprint, "repos": results, "all_ok": all_ok},
        next_steps=["Run delta to compare against SOT"] if all_ok else None,
    )


def _find_reference_file(
    repo_path: Path,
    repo_name: str,
    sprint: str,
    fmt: OutputFormatter,
) -> Optional[Path]:
    """Locate the generated reference JSON for a repo+sprint."""
    i18n_dir = repo_path / "i18n"
    if not i18n_dir.is_dir():
        fmt.log_warn(f"{repo_name}: no i18n/ directory — run extract first")
        return None

    normalized = sprint.lower() if sprint.startswith("s") else f"s{sprint}"
    expected = i18n_dir / f"{repo_name.lower()}-{normalized}.json"
    if expected.exists():
        return expected

    candidates = sorted(
        i18n_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        fmt.log_info(f"{repo_name}: using {candidates[0].name} (sprint file not found)")
        return candidates[0]

    fmt.log_warn(f"{repo_name}: no reference file found in {i18n_dir}")
    return None


def cmd_delta(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Compare extracted references against SOT and produce delta files."""
    sprint = args.sprint
    search_root = args.search_root

    repos = find_all_repos(search_root=search_root)
    rhdh_repo = repos.get("rhdh")
    rhdh_plugins_repo = repos.get("rhdh-plugins")

    if rhdh_repo is None:
        fmt.error("rhdh repo not found — needed for translated SOT", next_steps=["Run preflight"])
        sys.exit(1)

    # EN SOT: primary in rhdh-plugins/workspaces/translations/sot/,
    # fallback to rhdh/translations/ for backward compatibility.
    en_sot_dir = find_en_sot_dir(rhdh_plugins_repo=rhdh_plugins_repo, rhdh_repo=rhdh_repo)
    if en_sot_dir:
        fmt.log_info(f"EN SOT directory: {en_sot_dir}")
    else:
        fmt.log_warn("EN SOT directory not found — value comparison disabled")

    normalized_sprint = sprint.lower() if sprint.startswith("s") else f"s{sprint}"

    # ------------------------------------------------------------------
    # Phase 1: load all reference files so rhdh keys are available for
    #          the backstage override merge.
    # ------------------------------------------------------------------
    ref_keys: dict[str, dict[str, dict[str, str]]] = {}
    repo_i18n: dict[str, Path] = {}

    for repo_name in ("rhdh-plugins", "rhdh", "community-plugins", "backstage"):
        repo_path = repos.get(repo_name)
        if repo_path is None:
            continue
        ref_file = _find_reference_file(repo_path, repo_name, sprint, fmt)
        if ref_file is None:
            continue
        keys = load_reference_keys(ref_file)
        if keys:
            ref_keys[repo_name] = keys
            repo_i18n[repo_name] = repo_path / "i18n"

    # ------------------------------------------------------------------
    # Phase 2: apply RHDH-priority merge to backstage.
    # The rhdh repo bundles all plugins (including backstage ones like
    # catalog, scaffolder) with RHDH-specific values.  Use the FULL
    # rhdh extraction for the override, then filter rhdh down to its
    # own plugins for delta computation.
    # ------------------------------------------------------------------
    overrides_report: list[dict[str, str]] = []
    if "backstage" in ref_keys and "rhdh" in ref_keys:
        ref_keys["backstage"], overrides_report = apply_rhdh_overrides(
            ref_keys["backstage"], ref_keys["rhdh"]
        )
        if overrides_report:
            fmt.log_info(f"backstage: {len(overrides_report)} key(s) overridden with rhdh values")
            for ov in overrides_report:
                fmt.log_info(
                    f"  {ov['plugin']}.{ov['key']}: "
                    f"{ov['backstage_value']!r} → {ov['rhdh_value']!r}"
                )

    # Filter repos with keep_plugins (rhdh → only the "rhdh" plugin).
    # Done after overrides so the full rhdh keys are available above.
    for repo_name, cfg in REPO_CONFIG.items():
        keep = cfg.get("keep_plugins")
        if keep and repo_name in ref_keys:
            before = len(ref_keys[repo_name])
            ref_keys[repo_name] = {p: kv for p, kv in ref_keys[repo_name].items() if p in set(keep)}
            removed = before - len(ref_keys[repo_name])
            if removed:
                fmt.log_info(
                    f"{repo_name}: filtered to {len(ref_keys[repo_name])} plugin(s), "
                    f"removed {removed} that belong to other repos"
                )

    # ------------------------------------------------------------------
    # Phase 3: compute delta and write output files per repo.
    # ------------------------------------------------------------------
    results: dict[str, Any] = {}

    for repo_name in ("rhdh-plugins", "rhdh", "community-plugins", "backstage"):
        if repo_name not in ref_keys:
            results[repo_name] = {"ok": False, "detail": "reference not loaded"}
            continue

        current_keys = ref_keys[repo_name]
        i18n_dir = repo_i18n[repo_name]
        sot_keys = load_sot_keys(rhdh_repo, repo_name)
        prev_english = load_sot_english_values(en_sot_dir, repo_name) if en_sot_dir else {}

        # Compute delta (compares both key names and English values)
        delta = compute_delta(current_keys, sot_keys, previous_english=prev_english)
        summary = delta["summary"]

        fmt.log_info(
            f"{repo_name}: "
            f"{summary['new_key_count']} new, "
            f"{summary['changed_key_count']} changed, "
            f"{summary['removed_key_count']} removed, "
            f"{summary['unchanged_key_count']} unchanged"
        )

        if summary["new_plugin_count"] > 0:
            fmt.log_info(
                f"  {summary['new_plugin_count']} new plugin(s): "
                f"{', '.join(delta['new_plugins'].keys())}"
            )

        if summary["changed_key_count"] > 0:
            changed_plugins = ", ".join(delta["changed_keys"].keys())
            fmt.log_info(
                f"  {summary['changed_key_count']} key(s) with changed English: {changed_plugins}"
            )

        # Build delta reference for upload
        delta_ref = build_delta_reference(delta, current_keys)
        delta_key_count = sum(len(v.get("en", {})) for v in delta_ref.values())

        # Write delta and full files into the repo's own i18n/ directory
        delta_file = i18n_dir / f"{repo_name}-{normalized_sprint}-delta.json"
        delta_file.write_text(
            json.dumps(delta_ref, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Full reference (for archival / future EN SOT).
        # For backstage this includes rhdh overrides already applied.
        full_file = i18n_dir / f"{repo_name}-{normalized_sprint}-full.json"
        full_data = {plugin: {"en": keys} for plugin, keys in current_keys.items()}
        full_file.write_text(
            json.dumps(full_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        result_entry: dict[str, Any] = {
            "ok": True,
            "delta_file": str(delta_file),
            "full_file": str(full_file),
            "delta_keys": delta_key_count,
            "summary": summary,
        }

        # Attach override report to backstage result
        if repo_name == "backstage" and overrides_report:
            overrides_file = i18n_dir / f"{repo_name}-{normalized_sprint}-rhdh-overrides.json"
            overrides_file.write_text(
                json.dumps(overrides_report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            result_entry["overrides_file"] = str(overrides_file)
            result_entry["overrides_count"] = len(overrides_report)

        results[repo_name] = result_entry

        if delta_key_count > 0:
            fmt.log_ok(
                f"{repo_name}: delta written to {delta_file.name} "
                f"({delta_key_count} keys for translation)"
            )
        else:
            fmt.log_info(f"{repo_name}: no new keys — nothing to upload")

    # Aggregate summary
    total_delta = sum(r.get("delta_keys", 0) for r in results.values() if r.get("ok"))

    fmt.success(
        {
            "sprint": sprint,
            "repos": results,
            "total_delta_keys": total_delta,
        },
        next_steps=(
            [
                "Review the delta files in the output directory",
                "Upload delta files to TMS with: translations-cli i18n upload",
            ]
            if total_delta > 0
            else ["No new keys to translate"]
        ),
    )


# ---------------------------------------------------------------------------
# Subcommand: upload to TMS
# ---------------------------------------------------------------------------

# Default TMS project (reused across releases)
DEFAULT_TMS_PROJECT_ID = "gO1x9evesBS0qAX7AUPaY0"
DEFAULT_TARGET_LANGUAGES = ["de", "es", "fr", "it", "ja"]


def cmd_upload(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Upload delta files to TMS via translations-cli."""
    sprint = args.sprint
    search_root = args.search_root
    project_id = args.project_id
    target_langs = [lang.strip() for lang in args.target_languages.split(",")]
    dry_run = args.dry_run

    repos = find_all_repos(search_root=search_root)
    rhdh_plugins = repos.get("rhdh-plugins")
    if rhdh_plugins is None:
        fmt.error("rhdh-plugins not found", next_steps=["Run preflight"])
        sys.exit(1)

    cli_path = find_translations_cli(rhdh_plugins)
    if cli_path is None:
        fmt.error("translations-cli not found")
        sys.exit(1)

    # Check MEMSOURCE_TOKEN
    if not os.environ.get("MEMSOURCE_TOKEN"):
        fmt.error(
            "MEMSOURCE_TOKEN not set — run: source ~/.memsourcerc",
            next_steps=["source ~/.memsourcerc", "Then re-run upload"],
        )
        sys.exit(1)

    normalized_sprint = sprint.lower() if sprint.startswith("s") else f"s{sprint}"
    results: dict[str, Any] = {}

    for repo_name in ("rhdh-plugins", "rhdh", "community-plugins", "backstage"):
        repo_path = repos.get(repo_name)
        if repo_path is None:
            continue

        i18n_dir = repo_path / "i18n"
        delta_file = i18n_dir / f"{repo_name}-{normalized_sprint}-delta.json"

        if not delta_file.exists():
            fmt.log_info(f"{repo_name}: no delta file — skipping")
            results[repo_name] = {"ok": True, "skipped": True, "detail": "no delta file"}
            continue

        # Check if delta has any keys
        try:
            data = json.loads(delta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            fmt.log_warn(f"{repo_name}: could not read delta file")
            results[repo_name] = {"ok": False, "detail": "unreadable delta"}
            continue

        key_count = sum(len(v.get("en", {})) for v in data.values())
        if key_count == 0:
            fmt.log_info(f"{repo_name}: delta has 0 keys — skipping upload")
            results[repo_name] = {"ok": True, "skipped": True, "detail": "0 keys"}
            continue

        upload_filename = f"{repo_name}-{normalized_sprint}.json"

        cmd = [
            "node",
            str(cli_path),
            "i18n",
            "upload",
            "--source-file",
            str(delta_file),
            "--upload-filename",
            upload_filename,
            "--project-id",
            project_id,
            "--target-languages",
            ",".join(target_langs),
        ]
        if dry_run:
            cmd.append("--dry-run")

        fmt.log_info(f"{repo_name}: uploading {delta_file.name} ({key_count} keys)")

        if dry_run:
            fmt.log_info(f"  [dry-run] {' '.join(cmd)}")
            results[repo_name] = {
                "ok": True,
                "dry_run": True,
                "keys": key_count,
                "upload_filename": upload_filename,
            }
            continue

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(repo_path),
            env={**os.environ},
        )

        if result.returncode != 0:
            fmt.log_fail(f"{repo_name}: upload failed: {result.stderr.strip()}")
            results[repo_name] = {
                "ok": False,
                "detail": result.stderr.strip(),
            }
        else:
            fmt.log_ok(f"{repo_name}: uploaded {upload_filename} ({key_count} keys)")
            results[repo_name] = {
                "ok": True,
                "keys": key_count,
                "upload_filename": upload_filename,
            }

    all_ok = all(r.get("ok", False) for r in results.values())
    fmt.success(
        {
            "sprint": sprint,
            "project_id": project_id,
            "target_languages": target_langs,
            "dry_run": dry_run,
            "repos": results,
        },
        next_steps=(
            ["Run update-sot to save the EN baseline for next release"]
            if all_ok and not dry_run
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Subcommand: update EN SOT + create PR
# ---------------------------------------------------------------------------


def cmd_update_sot(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Copy full reference files to rhdh-plugins EN SOT and create a PR."""
    sprint = args.sprint
    search_root = args.search_root
    branch_name = args.branch or f"translation/{sprint}-en-sot-update"

    repos = find_all_repos(search_root=search_root)
    rhdh_plugins_repo = repos.get("rhdh-plugins")

    if rhdh_plugins_repo is None:
        fmt.error("rhdh-plugins repo not found", next_steps=["Run preflight"])
        sys.exit(1)

    sot_dir = rhdh_plugins_repo / "workspaces" / "translations" / "sot"
    sot_dir.mkdir(parents=True, exist_ok=True)

    normalized_sprint = sprint.lower() if sprint.startswith("s") else f"s{sprint}"
    updated: list[dict[str, str]] = []

    for repo_name in ("rhdh-plugins", "rhdh", "community-plugins", "backstage"):
        repo_path = repos.get(repo_name)
        if repo_path is None:
            continue

        full_file = repo_path / "i18n" / f"{repo_name}-{normalized_sprint}-full.json"
        if not full_file.exists():
            fmt.log_info(f"{repo_name}: no full reference file — skipping")
            continue

        target = sot_dir / f"{repo_name}-en.json"
        shutil.copy2(str(full_file), str(target))
        fmt.log_ok(f"{repo_name}: {full_file.name} → {target.name}")
        updated.append({"repo": repo_name, "file": str(target)})

    if not updated:
        fmt.error("No full reference files found — run extract + delta first")
        sys.exit(1)

    # Create branch, commit, and open PR in rhdh-plugins repo
    fmt.log_info(f"Creating branch {branch_name} in rhdh-plugins repo")

    branch_check = subprocess.run(
        ["git", "rev-parse", "--verify", branch_name],
        capture_output=True,
        text=True,
        cwd=str(rhdh_plugins_repo),
    )
    if branch_check.returncode == 0:
        fmt.log_warn(f"Branch {branch_name} already exists — using it")
        subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
            cwd=str(rhdh_plugins_repo),
        )
    else:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            capture_output=True,
            text=True,
            cwd=str(rhdh_plugins_repo),
        )
        if result.returncode != 0:
            fmt.log_fail(f"Failed to create branch: {result.stderr.strip()}")
            sys.exit(1)

    # Stage the updated EN files
    en_files = [
        f"workspaces/translations/sot/{repo_name}-en.json"
        for repo_name in ("rhdh-plugins", "rhdh", "community-plugins", "backstage")
    ]
    subprocess.run(
        ["git", "add"] + en_files,
        capture_output=True,
        text=True,
        cwd=str(rhdh_plugins_repo),
    )

    # Check if there are actual changes
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(rhdh_plugins_repo),
    )
    if diff_result.returncode == 0:
        fmt.log_info("No changes to EN SOT — files are already up to date")
        subprocess.run(
            ["git", "checkout", "main"],
            capture_output=True,
            text=True,
            cwd=str(rhdh_plugins_repo),
        )
        fmt.success({"updated": updated, "pr": None, "detail": "no changes"})
        return

    # Commit
    commit_msg = (
        f"chore(translations): update EN SOT for {sprint}\n\n"
        f"Updated English reference files from {sprint} extraction.\n"
        "These serve as the baseline for the next release's delta comparison."
    )
    subprocess.run(
        ["git", "commit", "-s", "-m", commit_msg],
        capture_output=True,
        text=True,
        cwd=str(rhdh_plugins_repo),
    )
    fmt.log_ok("Committed EN SOT updates")

    # Push and create PR using gh
    push_result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        capture_output=True,
        text=True,
        cwd=str(rhdh_plugins_repo),
    )
    if push_result.returncode != 0:
        fmt.log_fail(f"Push failed: {push_result.stderr.strip()}")
        fmt.success(
            {"updated": updated, "pr": None, "detail": "push failed"},
            next_steps=[f"Manually push: git push -u origin {branch_name}"],
        )
        return

    pr_result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            f"chore(translations): update EN SOT for {sprint}",
            "--body",
            (
                f"Updates the English reference baseline in "
                f"`workspaces/translations/sot/` from the {sprint} extraction.\n\n"
                f"These `{{repo}}-en.json` files are used by the translation "
                f"delta script to detect changed English values between releases."
            ),
            "--base",
            "main",
        ],
        capture_output=True,
        text=True,
        cwd=str(rhdh_plugins_repo),
    )

    pr_url = None
    if pr_result.returncode == 0:
        pr_url = pr_result.stdout.strip()
        fmt.log_ok(f"PR created: {pr_url}")
    else:
        fmt.log_warn(f"PR creation failed: {pr_result.stderr.strip()}")

    # Switch back to main
    subprocess.run(
        ["git", "checkout", "main"],
        capture_output=True,
        text=True,
        cwd=str(rhdh_plugins_repo),
    )

    fmt.success(
        {
            "updated": updated,
            "branch": branch_name,
            "pr": pr_url,
        },
        next_steps=(
            ["Wait for translators, then run /rhdh-translation-deploy"]
            if pr_url
            else [f"Manually create PR from branch {branch_name}"]
        ),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="RHDH translation extraction and upload preparation",
    )
    parser.add_argument(
        "--json",
        dest="output_mode",
        action="store_const",
        const="json",
        default="auto",
        help="Force JSON output",
    )
    parser.add_argument(
        "--search-root",
        default=None,
        help="Root directory to search for repos (default: cwd parent)",
    )

    sub = parser.add_subparsers(dest="command")

    # preflight
    sub.add_parser("preflight", help="Check prerequisites")

    # extract
    p_extract = sub.add_parser("extract", help="Extract keys from all repos")
    p_extract.add_argument(
        "--sprint",
        required=True,
        help="Sprint identifier (e.g., s4000)",
    )

    # delta
    p_delta = sub.add_parser("delta", help="Compute delta against SOT")
    p_delta.add_argument(
        "--sprint",
        required=True,
        help="Sprint identifier (e.g., s4000)",
    )

    # upload
    p_upload = sub.add_parser("upload", help="Upload delta files to TMS")
    p_upload.add_argument(
        "--sprint",
        required=True,
        help="Sprint identifier (e.g., s4000)",
    )
    p_upload.add_argument(
        "--project-id",
        default=DEFAULT_TMS_PROJECT_ID,
        help=f"TMS project ID (default: {DEFAULT_TMS_PROJECT_ID})",
    )
    p_upload.add_argument(
        "--target-languages",
        default=",".join(DEFAULT_TARGET_LANGUAGES),
        help=f"Comma-separated target languages (default: {','.join(DEFAULT_TARGET_LANGUAGES)})",
    )
    p_upload.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be uploaded without uploading",
    )

    # update-sot
    p_sot = sub.add_parser("update-sot", help="Update EN SOT and create PR")
    p_sot.add_argument(
        "--sprint",
        required=True,
        help="Sprint identifier (e.g., s4000)",
    )
    p_sot.add_argument(
        "--branch",
        default=None,
        help="Branch name for the PR (default: translation/{sprint}-en-sot-update)",
    )

    args = parser.parse_args(argv)
    fmt = OutputFormatter(mode=args.output_mode)

    commands = {
        "preflight": cmd_preflight,
        "extract": cmd_extract,
        "delta": cmd_delta,
        "upload": cmd_upload,
        "update-sot": cmd_update_sot,
    }

    if not args.command:
        parser.print_help()
        sys.exit(1)

    handler = commands.get(args.command)
    if handler is None:
        fmt.error(f"Unknown command: {args.command}")
        sys.exit(1)

    handler(args, fmt)


if __name__ == "__main__":
    main()
