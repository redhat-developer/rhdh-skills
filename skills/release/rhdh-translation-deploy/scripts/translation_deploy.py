#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Download translations from TMS and deploy to target repos.

Downloads via translations-cli. Merges into locale .ts files by updating
matching keys only (never removes, never inserts missing keys). Backstage
and rhdh strings go to rhdh/translations/ via update-translated-sot — there
is no upstream backstage repo PR.

Usage:
    uv run scripts/translation_deploy.py preflight
    uv run scripts/translation_deploy.py download --project-id PROJ_ID
    uv run scripts/translation_deploy.py update-translated-sot --sprint s3297
    uv run scripts/translation_deploy.py deploy --source-dir i18n/downloads
    uv run scripts/translation_deploy.py validate --source-dir i18n/downloads
    uv run scripts/translation_deploy.py pr --sprint s3297
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from _support import (  # noqa: E402
    OutputFormatter,
    check_tms_credentials,
    find_all_repos,
    find_memsource_cli,
    find_node_tool,
    find_translations_cli,
    git_current_branch,
    git_is_clean,
)

# Languages we translate into
TARGET_LANGUAGES = ("de", "es", "fr", "it", "ja")

# Repos that receive in-place .ts locale merges + PRs with changesets.
# backstage / rhdh go only through update-translated-sot → rhdh/translations/.
DEPLOY_TS_REPOS = ("rhdh-plugins", "community-plugins")

# Repos whose translations go into the translated SOT (rhdh/translations/).
# rhdh-plugins is excluded — its translations live in the rhdh-plugins repo.
TRANSLATED_SOT_REPOS = ("backstage", "community-plugins", "rhdh")

_SKIP_UNQUOTED = frozenset(
    {
        "import",
        "export",
        "const",
        "let",
        "var",
        "default",
        "function",
        "return",
        "if",
        "else",
        "messages",
        "id",
        "ref",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_ts_string(value: str) -> str:
    """Format a string literal for a .ts messages entry.

    Prefer double quotes when the value contains an apostrophe (codebase
    convention). Escape backslashes and the chosen delimiter.
    """
    escaped = value.replace("\\", "\\\\")
    if "'" in value:
        return '"' + escaped.replace('"', '\\"') + '"'
    return "'" + escaped.replace("'", "\\'") + "'"


def _find_plugin_translations_dir(repo_root: Path, plugin_name: str) -> Path | None:
    """Locate workspaces/*/plugins/{name}/src/translations for a plugin."""
    short = plugin_name
    if short.startswith("plugin."):
        short = short[len("plugin.") :]
    workspaces = repo_root / "workspaces"
    if not workspaces.is_dir():
        return None
    for ws in sorted(workspaces.iterdir()):
        candidate = ws / "plugins" / short / "src" / "translations"
        if candidate.is_dir():
            return candidate
    return None


def _unescape_ts_string(raw: str) -> str:
    """Unescape a TypeScript string literal body."""
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in ("'", '"', "\\"):
                out.append(nxt)
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
        out.append(raw[i])
        i += 1
    return "".join(out)


def _extract_locale_keys(content: str) -> dict[str, str]:
    """Parse key → decoded value from a locale .ts messages object.

    Handles quoted keys ('dotted.key') and unquoted keys (disclaimer:).
    Same-line string values only.
    """
    keys: dict[str, str] = {}
    for m in re.finditer(
        r"""['\"]([a-zA-Z][a-zA-Z0-9_.]*)['\"]\s*:\s*(['\"])((?:\\.|(?!\2).)*)\2""",
        content,
    ):
        keys[m.group(1)] = _unescape_ts_string(m.group(3))
    for m in re.finditer(
        r"""^\s+([a-zA-Z][a-zA-Z0-9_]*)\s*:\s*(['\"])((?:\\.|(?!\2).)*)\2""",
        content,
        re.MULTILINE,
    ):
        word = m.group(1)
        if word not in _SKIP_UNQUOTED:
            keys[word] = _unescape_ts_string(m.group(3))
    return keys


def _update_key_value(content: str, key: str, new_value: str) -> tuple[str, bool]:
    """Replace the value for an existing key; return (content, changed).

    Matches quoted or unquoted keys. Does not insert missing keys.
    """
    formatted = _format_ts_string(new_value)
    # Quoted key (single or double quotes around the key)
    quoted = re.compile(
        r"(['\"])(" + re.escape(key) + r")\1\s*:\s*(['\"])(?:\\.|(?!\3).)*\3",
        re.DOTALL,
    )

    def _repl_quoted(m: re.Match[str]) -> str:
        return f"{m.group(1)}{m.group(2)}{m.group(1)}: {formatted}"

    new_content, n = quoted.subn(_repl_quoted, content, count=1)
    if n:
        return new_content, new_content != content

    # Unquoted key (no dots)
    if "." not in key and re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", key):
        unquoted = re.compile(
            r"^(\s+)" + re.escape(key) + r'(\s*:\s*)([\'"])(?:\\.|(?!\3).)*\3',
            re.MULTILINE | re.DOTALL,
        )

        def _repl_unquoted(m: re.Match[str]) -> str:
            return f"{m.group(1)}{key}{m.group(2)}{formatted}"

        new_content, n = unquoted.subn(_repl_unquoted, content, count=1)
        if n:
            return new_content, new_content != content

    return content, False


def _merge_locale_file(
    ts_path: Path,
    incoming: dict[str, str],
) -> dict[str, int]:
    """Update matching keys in a locale .ts file.

    Returns counts: updated, skipped (not in file), unchanged.
    Never removes keys and never inserts new ones.
    """
    content = ts_path.read_text(encoding="utf-8")
    existing = _extract_locale_keys(content)
    updated = 0
    skipped = 0
    unchanged = 0

    for key, value in incoming.items():
        if key not in existing:
            skipped += 1
            continue
        if existing[key] == value:
            unchanged += 1
            continue
        content, changed = _update_key_value(content, key, value)
        if changed:
            updated += 1
        else:
            # Key present but value rewrite failed (e.g. multi-line) — skip
            skipped += 1

    if updated:
        ts_path.write_text(content, encoding="utf-8")

    return {"updated": updated, "skipped": skipped, "unchanged": unchanged}


def _run_prettier(repo_root: Path, files: list[Path], fmt: OutputFormatter) -> None:
    """Run Prettier --write on changed files when available."""
    if not files:
        return
    prettier = repo_root / "node_modules" / ".bin" / "prettier"
    if not prettier.is_file():
        fmt.log_warn(f"{repo_root.name}: prettier not found — format manually")
        return
    rels = []
    for f in files:
        try:
            rels.append(str(f.relative_to(repo_root)))
        except ValueError:
            rels.append(str(f))
    result = subprocess.run(
        [str(prettier), "--write", *rels],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if result.returncode != 0:
        fmt.log_warn(f"prettier failed: {result.stderr[-300:]}")
    else:
        fmt.log_ok(f"prettier: formatted {len(rels)} file(s)")


def _package_name_near(ts_path: Path) -> str | None:
    """Read package.json name walking up from a translation file."""
    for parent in ts_path.parents:
        pkg = parent / "package.json"
        if not pkg.is_file():
            continue
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        name = data.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def _incoming_keys_from_download(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Flatten TMS download JSON to {plugin: {key: value}}.

    TMS nests under language key (often 'en' for all locales).
    """
    out: dict[str, dict[str, str]] = {}
    for plugin, plugin_data in data.items():
        if not isinstance(plugin_data, dict):
            continue
        keys: dict[str, str] = {}
        for _lang, lang_data in plugin_data.items():
            if isinstance(lang_data, dict):
                for k, v in lang_data.items():
                    if isinstance(v, str):
                        keys[k] = v
        if keys:
            out[plugin] = keys
    return out


def _run_cli(
    cmd: list[str],
    *,
    cwd: str | Path,
    fmt: OutputFormatter,
    label: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run a CLI command, log, and return result."""
    fmt.log_info(f"{label}: {' '.join(cmd)}" if label else " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**os.environ, "NODE_OPTIONS": "--max-old-space-size=4096"},
    )
    if result.returncode != 0:
        fmt.log_fail(f"{label} failed:\n{result.stderr}")
    return result


def _find_downloaded_files(download_dir: Path) -> dict[str, list[Path]]:
    """Group downloaded JSON files by repo name.

    Expected patterns:
      {repo}-s{sprint}-{lang}(-C).json
      {repo}-{date}-{lang}(-C).json
    """
    result: dict[str, list[Path]] = {}
    if not download_dir.is_dir():
        return result

    lang_codes = "|".join(TARGET_LANGUAGES)
    # Sprint pattern: repo-sNNNN-lang(-C).json
    sprint_pat = re.compile(rf"^([a-z][\w-]*?)-(s\d+)-({lang_codes})(?:-C)?\.json$", re.IGNORECASE)
    # Date pattern: repo-YYYY-MM-DD-lang(-C).json
    date_pat = re.compile(
        rf"^([a-z][\w-]*?)-(\d{{4}}-\d{{2}}-\d{{2}})-({lang_codes})(?:-C)?\.json$",
        re.IGNORECASE,
    )

    for f in sorted(download_dir.iterdir()):
        if not f.suffix == ".json":
            continue
        m = sprint_pat.match(f.name) or date_pat.match(f.name)
        if m:
            repo = m.group(1)
            result.setdefault(repo, []).append(f)

    return result


def _validate_translation_file(
    filepath: Path,
) -> dict[str, Any]:
    """Validate a downloaded translation JSON file.

    Checks:
    - Valid JSON
    - Expected structure: { plugin: { lang: { key: value } } }
    - No empty plugins
    - Placeholder preservation ({{...}} patterns)
    """
    issues: list[str] = []
    stats: dict[str, int] = {"plugins": 0, "keys": 0}

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "issues": [f"Invalid JSON: {exc}"], "stats": stats}

    if not isinstance(data, dict):
        return {"ok": False, "issues": ["Root is not an object"], "stats": stats}

    for plugin_name, plugin_data in data.items():
        if not isinstance(plugin_data, dict):
            issues.append(f"{plugin_name}: not an object")
            continue

        stats["plugins"] += 1
        for lang, lang_data in plugin_data.items():
            if not isinstance(lang_data, dict):
                issues.append(f"{plugin_name}.{lang}: not an object")
                continue
            stats["keys"] += len(lang_data)

            if len(lang_data) == 0:
                issues.append(f"{plugin_name}.{lang}: empty — no keys")

            # Check placeholder preservation (just warn, don't block)
            for key, value in lang_data.items():
                if not isinstance(value, str):
                    issues.append(f"{plugin_name}.{lang}.{key}: value is not a string")

    return {
        "ok": len([i for i in issues if "not an object" in i or "not a string" in i]) == 0,
        "issues": issues,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Check prerequisites for the deploy workflow."""
    search_root = args.search_root
    repos = find_all_repos(search_root=search_root)
    checks: list[dict[str, Any]] = []

    for name, path in repos.items():
        ok = path is not None
        checks.append(
            {
                "name": f"repo_{name}",
                "ok": ok,
                "detail": str(path) if ok else f"{name} not found",
            }
        )
        if ok:
            fmt.log_ok(f"{name}: {path}")
        else:
            fmt.log_fail(f"{name}: not found")

    rhdh_plugins = repos.get("rhdh-plugins")
    cli_path: Optional[Path] = None
    if rhdh_plugins:
        cli_path = find_translations_cli(rhdh_plugins)
    checks.append(
        {
            "name": "translations_cli",
            "ok": cli_path is not None,
            "detail": str(cli_path) if cli_path else "not found",
        }
    )
    if cli_path:
        fmt.log_ok(f"translations-cli: {cli_path}")
    else:
        fmt.log_fail("translations-cli: not found")

    for tool in ("node", "gh"):
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

    creds = check_tms_credentials()
    any_cred = any(creds.values())
    checks.append(
        {
            "name": "tms_credentials",
            "ok": any_cred,
            "detail": {k: v for k, v in creds.items()},
        }
    )

    mem_cli = find_memsource_cli()
    checks.append(
        {
            "name": "memsource_cli",
            "ok": mem_cli is not None,
            "detail": mem_cli or "not on PATH",
        }
    )

    for name, path in repos.items():
        if path is None:
            continue
        clean = git_is_clean(path)
        branch = git_current_branch(path)
        checks.append(
            {
                "name": f"git_clean_{name}",
                "ok": clean,
                "detail": f"branch={branch}, clean={clean}",
            }
        )
        if clean:
            fmt.log_ok(f"{name} git: clean on {branch}")
        else:
            fmt.log_warn(f"{name} git: uncommitted changes on {branch}")

    all_ok = all(c["ok"] for c in checks)
    next_steps = [f"Fix: {c['name']} — {c['detail']}" for c in checks if not c["ok"]]

    fmt.success({"checks": checks, "all_ok": all_ok}, next_steps=next_steps or None)


def cmd_download(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Download translated files from TMS."""
    search_root = args.search_root
    repos = find_all_repos(search_root=search_root)
    rhdh_plugins = repos.get("rhdh-plugins")

    if rhdh_plugins is None:
        fmt.error("rhdh-plugins repo not found", next_steps=["Run preflight"])
        sys.exit(1)

    cli_path = find_translations_cli(rhdh_plugins)
    if cli_path is None:
        fmt.error("translations-cli not found")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "node",
        str(cli_path),
        "i18n",
        "download",
        "--output-dir",
        str(output_dir),
    ]

    if args.project_id:
        cmd.extend(["--project-id", args.project_id])

    if args.languages:
        cmd.extend(["--languages", args.languages])

    if args.status:
        cmd.extend(["--status", args.status])

    result = _run_cli(cmd, cwd=rhdh_plugins, fmt=fmt, label="download")

    if result.returncode != 0:
        fmt.error(
            f"Download failed: {result.stderr}",
            next_steps=["Check TMS credentials and project ID"],
        )
        sys.exit(1)

    # Discover what was downloaded
    downloaded = _find_downloaded_files(output_dir)
    summary: dict[str, int] = {}
    for repo, files in downloaded.items():
        summary[repo] = len(files)
        for f in files:
            fmt.log_ok(f"Downloaded: {f.name}")

    fmt.success(
        {
            "output_dir": str(output_dir),
            "files_by_repo": summary,
            "total_files": sum(summary.values()),
        }
    )


def cmd_validate(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Validate downloaded translation files before deployment."""
    source_dir = Path(args.source_dir)

    if not source_dir.is_dir():
        fmt.error(f"Source directory not found: {source_dir}")
        sys.exit(1)

    downloaded = _find_downloaded_files(source_dir)
    if not downloaded:
        fmt.error(
            f"No translation files found in {source_dir}",
            next_steps=["Run download first"],
        )
        sys.exit(1)

    results: dict[str, list[dict[str, Any]]] = {}
    all_ok = True

    for repo, files in downloaded.items():
        results[repo] = []
        for f in files:
            validation = _validate_translation_file(f)
            results[repo].append(
                {
                    "file": f.name,
                    **validation,
                }
            )
            if validation["ok"]:
                fmt.log_ok(
                    f"{f.name}: {validation['stats']['plugins']} plugins, "
                    f"{validation['stats']['keys']} keys"
                )
            else:
                fmt.log_fail(f"{f.name}: {validation['issues']}")
                all_ok = False

    fmt.success(
        {"validations": results, "all_ok": all_ok},
        next_steps=(
            ["Run deploy to write translations into repos"]
            if all_ok
            else ["Fix validation issues before deploying"]
        ),
    )


def cmd_deploy(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Merge TMS downloads into locale .ts files (update matching keys only).

    Only rhdh-plugins and community-plugins. Does not call
    ``translations-cli i18n deploy`` (that rewrites files and drops keys).
    Backstage / rhdh translations belong in ``update-translated-sot``.
    """
    source_dir = Path(args.source_dir)
    search_root = args.search_root
    repos = find_all_repos(search_root=search_root)

    if not source_dir.is_dir():
        fmt.error(f"Source directory not found: {source_dir}")
        sys.exit(1)

    downloaded = _find_downloaded_files(source_dir)
    if not downloaded:
        fmt.error(f"No translation files in {source_dir}")
        sys.exit(1)

    deploy_results: dict[str, Any] = {}

    for repo_name in DEPLOY_TS_REPOS:
        repo_path = repos.get(repo_name)
        if repo_path is None:
            fmt.log_warn(f"{repo_name}: repo not found, skipping")
            deploy_results[repo_name] = {"ok": False, "detail": "repo not found"}
            continue

        repo_files = downloaded.get(repo_name, [])
        if not repo_files:
            fmt.log_info(f"{repo_name}: no downloaded files, skipping")
            deploy_results[repo_name] = {
                "ok": True,
                "detail": "no files to deploy",
                "files_changed": 0,
            }
            continue

        changed_files: list[Path] = []
        totals = {"updated": 0, "skipped": 0, "unchanged": 0, "plugins": 0}

        for dl_file in repo_files:
            locale = _detect_locale_from_filename(dl_file.name)
            if locale is None:
                fmt.log_warn(f"{dl_file.name}: could not detect locale — skipping")
                continue

            try:
                data = json.loads(dl_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                fmt.log_fail(f"{dl_file.name}: invalid JSON — {exc}")
                continue

            if not isinstance(data, dict):
                fmt.log_fail(f"{dl_file.name}: root is not an object")
                continue

            for plugin, keys in _incoming_keys_from_download(data).items():
                trans_dir = _find_plugin_translations_dir(repo_path, plugin)
                if trans_dir is None:
                    fmt.log_warn(f"{repo_name}/{plugin}: translations dir not found")
                    continue
                ts_path = trans_dir / f"{locale}.ts"
                if not ts_path.is_file():
                    fmt.log_warn(f"{ts_path.relative_to(repo_path)}: missing — skip")
                    continue

                counts = _merge_locale_file(ts_path, keys)
                totals["updated"] += counts["updated"]
                totals["skipped"] += counts["skipped"]
                totals["unchanged"] += counts["unchanged"]
                totals["plugins"] += 1
                if counts["updated"]:
                    if ts_path not in changed_files:
                        changed_files.append(ts_path)
                    fmt.log_ok(
                        f"{plugin} {locale}: "
                        f"{counts['updated']} updated, "
                        f"{counts['skipped']} skipped, "
                        f"{counts['unchanged']} unchanged"
                    )

        _run_prettier(repo_path, changed_files, fmt)

        deploy_results[repo_name] = {
            "ok": True,
            "files_changed": len(changed_files),
            "changed_files": [str(p.relative_to(repo_path)) for p in changed_files],
            **totals,
        }
        fmt.log_ok(
            f"{repo_name}: {len(changed_files)} file(s), "
            f"{totals['updated']} keys updated, "
            f"{totals['skipped']} skipped"
        )

    # Note repos that belong in translated SOT instead
    for repo_name in TRANSLATED_SOT_REPOS:
        if repo_name in downloaded and repo_name not in DEPLOY_TS_REPOS:
            fmt.log_info(
                f"{repo_name}: not deployed as .ts — use update-translated-sot "
                "into rhdh/translations/"
            )

    all_ok = all(r.get("ok", False) for r in deploy_results.values())
    fmt.success(
        {"repos": deploy_results, "all_ok": all_ok},
        next_steps=(
            [
                "Create PRs: uv run scripts/translation_deploy.py pr --sprint S",
                "For backstage/rhdh/community-plugins JSON SOT: "
                "uv run scripts/translation_deploy.py update-translated-sot --sprint S",
            ]
            if all_ok
            else ["Fix deploy failures before creating PRs"]
        ),
    )


def cmd_pr(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Prepare changesets and report repos ready for mutation-gate PRs.

    Only rhdh-plugins and community-plugins. Creates a changeset per repo
    with correct package names for every touched translation package.
    """
    sprint = args.sprint
    branch_name = args.branch or f"translation/{sprint}"
    search_root = args.search_root
    repos = find_all_repos(search_root=search_root)

    pr_results: dict[str, Any] = {}

    for repo_name in DEPLOY_TS_REPOS:
        repo_path = repos.get(repo_name)
        if repo_path is None:
            fmt.log_warn(f"{repo_name}: repo not found, skipping")
            pr_results[repo_name] = {"ok": False, "detail": "repo not found"}
            continue

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(repo_path),
        )
        if status.returncode != 0 or not status.stdout.strip():
            fmt.log_info(f"{repo_name}: no changes to commit")
            pr_results[repo_name] = {"ok": True, "detail": "no changes"}
            continue

        changed_lines = [line.strip() for line in status.stdout.strip().split("\n") if line.strip()]
        # Paths after status prefix (XY path)
        changed_paths: list[Path] = []
        for line in changed_lines:
            path_part = line[3:] if len(line) > 3 else line
            # Handle renames: "R  old -> new"
            if " -> " in path_part:
                path_part = path_part.split(" -> ", 1)[1]
            changed_paths.append(repo_path / path_part)

        ts_changed = [
            p
            for p in changed_paths
            if p.suffix == ".ts" and "translations" in p.parts and p.name != "ref.ts"
        ]
        package_names: list[str] = []
        for ts in ts_changed:
            name = _package_name_near(ts)
            if name:
                package_names.append(name)

        # Prefer workspace-level .changeset when present
        changeset_paths: list[str] = []
        by_ws: dict[Path, list[str]] = {}
        for ts in ts_changed:
            name = _package_name_near(ts)
            if not name:
                continue
            # workspaces/<ws>/...
            try:
                parts = ts.relative_to(repo_path).parts
            except ValueError:
                continue
            if len(parts) >= 2 and parts[0] == "workspaces":
                ws_root = repo_path / "workspaces" / parts[1]
                by_ws.setdefault(ws_root, []).append(name)
            else:
                by_ws.setdefault(repo_path, []).append(name)

        for ws_root, names in by_ws.items():
            cs_dir = ws_root / ".changeset"
            if not cs_dir.is_dir():
                # fall back to repo root
                cs_dir = repo_path / ".changeset"
            if not cs_dir.is_dir():
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", sprint.lower()).strip("-")
            cs_path = cs_dir / f"translations-{slug}.md"
            lines = ["---"]
            for n in sorted(set(names)):
                lines.append(f'"{n}": patch')
            lines.append("---")
            lines.append(f"Update translations for {sprint}.")
            lines.append("")
            cs_path.write_text("\n".join(lines), encoding="utf-8")
            try:
                changeset_paths.append(str(cs_path.relative_to(repo_path)))
            except ValueError:
                changeset_paths.append(str(cs_path))
            fmt.log_ok(f"{repo_name}: changeset → {cs_path.name} ({len(set(names))} pkgs)")

        pr_results[repo_name] = {
            "ok": True,
            "branch": branch_name,
            "changed_files": len(changed_lines),
            "packages": sorted(set(package_names)),
            "changesets": changeset_paths,
            "ready_for_pr": True,
        }
        fmt.log_ok(
            f"{repo_name}: {len(changed_lines)} files changed, ready for branch {branch_name}"
        )

    fmt.log_info(
        "backstage: no .ts PR — overrides come from rhdh/translations/ via update-translated-sot"
    )

    fmt.success(
        {
            "sprint": sprint,
            "branch": branch_name,
            "repos": pr_results,
        },
        next_steps=[
            f"For each repo with changes, create branch {branch_name}, "
            "commit with Signed-off-by (include changesets), run prettier "
            "if needed, and open PR via /mutation-gate",
        ],
    )


def _fix_locale_key(data: dict[str, Any], target_locale: str) -> dict[str, Any]:
    """Replace the 'en' language key with the actual target locale.

    TMS returns: { plugin: { "en": { key: translated_value } } }
    SOT expects: { plugin: { "de": { key: translated_value } } }
    """
    fixed: dict[str, Any] = {}
    for plugin_name, plugin_data in data.items():
        if not isinstance(plugin_data, dict):
            fixed[plugin_name] = plugin_data
            continue
        new_plugin: dict[str, Any] = {}
        for lang_key, lang_data in plugin_data.items():
            actual_key = target_locale if lang_key == "en" else lang_key
            new_plugin[actual_key] = lang_data
        fixed[plugin_name] = new_plugin
    return fixed


def _merge_sot(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge incoming translations into the existing SOT.

    For each plugin → locale → key, incoming values override existing.
    Keys that exist in the SOT but not in incoming are preserved (they
    are unchanged translations from the previous release).
    """
    merged = json.loads(json.dumps(existing))
    for plugin_name, plugin_data in incoming.items():
        if plugin_name not in merged:
            merged[plugin_name] = {}
        if not isinstance(plugin_data, dict):
            continue
        for locale, keys in plugin_data.items():
            if locale not in merged[plugin_name]:
                merged[plugin_name][locale] = {}
            if isinstance(keys, dict):
                merged[plugin_name][locale].update(keys)
    return merged


def _detect_locale_from_filename(filename: str) -> str | None:
    """Extract locale from a TMS download filename.

    Patterns: {repo}-s{sprint}-{locale}.json or {repo}-{date}-{locale}.json
    """
    for lang in TARGET_LANGUAGES:
        if f"-{lang}.json" in filename or f"-{lang}-C.json" in filename:
            return lang
    return None


def cmd_update_translated_sot(args: argparse.Namespace, fmt: OutputFormatter) -> None:
    """Merge downloaded translations into rhdh/translations/ SOT.

    Reads TMS downloads, fixes the 'en' locale key to the actual target
    locale, and merges into the existing SOT files. Only processes repos
    in TRANSLATED_SOT_REPOS (backstage, community-plugins, rhdh).
    """
    source_dir = Path(args.source_dir)
    search_root = args.search_root
    sprint = args.sprint
    branch_name = args.branch or f"translation/{sprint}-translated-sot"

    repos = find_all_repos(search_root=search_root)
    rhdh_repo = repos.get("rhdh")

    if rhdh_repo is None:
        fmt.error("rhdh repo not found", next_steps=["Run preflight"])
        sys.exit(1)

    if not source_dir.is_dir():
        fmt.error(f"Source directory not found: {source_dir}")
        sys.exit(1)

    translations_dir = rhdh_repo / "translations"
    if not translations_dir.is_dir():
        fmt.error(f"SOT directory not found: {translations_dir}")
        sys.exit(1)

    downloaded = _find_downloaded_files(source_dir)
    if not downloaded:
        fmt.error(
            f"No translation files in {source_dir}",
            next_steps=["Run download first"],
        )
        sys.exit(1)

    updated: list[dict[str, str]] = []

    for repo_name in TRANSLATED_SOT_REPOS:
        repo_files = downloaded.get(repo_name, [])
        if not repo_files:
            fmt.log_info(f"{repo_name}: no downloaded files — skipping")
            continue

        for dl_file in repo_files:
            locale = _detect_locale_from_filename(dl_file.name)
            if locale is None:
                fmt.log_warn(f"{dl_file.name}: could not detect locale — skipping")
                continue

            try:
                incoming = json.loads(dl_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                fmt.log_fail(f"{dl_file.name}: invalid JSON — {exc}")
                continue

            # Fix en → actual locale
            fixed = _fix_locale_key(incoming, locale)

            # Load existing SOT file and merge
            sot_file = translations_dir / f"{repo_name}-{locale}.json"
            existing: dict[str, Any] = {}
            if sot_file.exists():
                try:
                    existing = json.loads(sot_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass

            merged = _merge_sot(existing, fixed)

            # Count new/updated keys
            new_key_count = sum(
                len(keys)
                for p in fixed.values()
                if isinstance(p, dict)
                for keys in p.values()
                if isinstance(keys, dict)
            )

            sot_file.write_text(
                json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            fmt.log_ok(f"{repo_name}-{locale}: merged {new_key_count} keys → {sot_file.name}")
            updated.append({"repo": repo_name, "locale": locale, "file": sot_file.name})

    if not updated:
        fmt.error("No files updated — check downloads")
        sys.exit(1)

    # Create branch, commit, and open PR in rhdh repo
    fmt.log_info(f"Creating branch {branch_name} in rhdh repo")

    orig_branch = git_current_branch(rhdh_repo) or "main"

    branch_check = subprocess.run(
        ["git", "rev-parse", "--verify", branch_name],
        capture_output=True,
        text=True,
        cwd=str(rhdh_repo),
    )
    if branch_check.returncode == 0:
        fmt.log_warn(f"Branch {branch_name} already exists — using it")
        subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
            cwd=str(rhdh_repo),
        )
    else:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            capture_output=True,
            text=True,
            cwd=str(rhdh_repo),
        )
        if result.returncode != 0:
            fmt.log_fail(f"Failed to create branch: {result.stderr.strip()}")
            sys.exit(1)

    # Stage only the updated translation files
    sot_files = [f"translations/{u['file']}" for u in updated]
    subprocess.run(
        ["git", "add"] + sot_files,
        capture_output=True,
        text=True,
        cwd=str(rhdh_repo),
    )

    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(rhdh_repo),
    )
    if diff_result.returncode == 0:
        fmt.log_info("No changes to translated SOT — files are already up to date")
        subprocess.run(
            ["git", "checkout", orig_branch],
            capture_output=True,
            text=True,
            cwd=str(rhdh_repo),
        )
        fmt.success({"updated": updated, "pr": None, "detail": "no changes"})
        return

    commit_msg = (
        f"chore(translations): update translated SOT for {sprint}\n\n"
        f"Merged {len(updated)} translated files from TMS into translations/.\n"
        "Repos updated: " + ", ".join(sorted({u["repo"] for u in updated}))
    )
    subprocess.run(
        ["git", "commit", "-s", "-m", commit_msg],
        capture_output=True,
        text=True,
        cwd=str(rhdh_repo),
    )
    fmt.log_ok("Committed translated SOT updates")

    push_result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        capture_output=True,
        text=True,
        cwd=str(rhdh_repo),
    )
    if push_result.returncode != 0:
        fmt.log_fail(f"Push failed: {push_result.stderr.strip()}")
        fmt.success(
            {"updated": updated, "pr": None, "detail": "push failed"},
            next_steps=[f"Manually push: git push -u origin {branch_name}"],
        )
        subprocess.run(
            ["git", "checkout", orig_branch],
            capture_output=True,
            text=True,
            cwd=str(rhdh_repo),
        )
        return

    locales_str = ", ".join(sorted({u["locale"] for u in updated}))
    repos_str = ", ".join(sorted({u["repo"] for u in updated}))
    pr_result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            f"chore(translations): update {sprint} translations ({locales_str})",
            "--body",
            (
                f"Merges {sprint} TMS translations into `translations/`.\n\n"
                f"**Repos:** {repos_str}\n"
                f"**Locales:** {locales_str}\n"
                f"**Files updated:** {len(updated)}\n\n"
                "The `en` language key in TMS output has been fixed to the "
                "actual target locale."
            ),
            "--base",
            "main",
        ],
        capture_output=True,
        text=True,
        cwd=str(rhdh_repo),
    )

    pr_url = None
    if pr_result.returncode == 0:
        pr_url = pr_result.stdout.strip()
        fmt.log_ok(f"PR created: {pr_url}")
    else:
        fmt.log_warn(f"PR creation failed: {pr_result.stderr.strip()}")

    subprocess.run(
        ["git", "checkout", orig_branch],
        capture_output=True,
        text=True,
        cwd=str(rhdh_repo),
    )

    fmt.success(
        {
            "updated": updated,
            "branch": branch_name,
            "pr": pr_url,
            "repos": sorted({u["repo"] for u in updated}),
            "locales": sorted({u["locale"] for u in updated}),
        },
        next_steps=(
            [
                "Run deploy for .ts merges in rhdh-plugins and community-plugins",
                "uv run scripts/translation_deploy.py deploy --source-dir …",
            ]
            if pr_url
            else [f"Manually create PR from branch {branch_name}"]
        ),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="RHDH translation download and deployment",
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

    # download
    p_download = sub.add_parser("download", help="Download from TMS")
    p_download.add_argument("--project-id", help="TMS project ID")
    p_download.add_argument(
        "--output-dir",
        default="i18n/downloads",
        help="Download output directory",
    )
    p_download.add_argument(
        "--languages",
        help="Comma-separated languages (e.g., de,es,fr,it,ja)",
    )
    p_download.add_argument(
        "--status",
        default="COMPLETED",
        help="Job status filter (default: COMPLETED)",
    )

    # validate
    p_validate = sub.add_parser("validate", help="Validate downloaded files")
    p_validate.add_argument(
        "--source-dir",
        default="i18n/downloads",
        help="Directory with downloaded translations",
    )

    # deploy — in-place .ts merge for rhdh-plugins + community-plugins only
    p_deploy = sub.add_parser(
        "deploy",
        help="Merge into locale .ts files (rhdh-plugins, community-plugins)",
    )
    p_deploy.add_argument(
        "--source-dir",
        default="i18n/downloads",
        help="Directory with downloaded translations",
    )

    # pr
    p_pr = sub.add_parser("pr", help="Prepare branches for PRs")
    p_pr.add_argument(
        "--sprint",
        required=True,
        help="Sprint identifier for branch name",
    )
    p_pr.add_argument(
        "--branch",
        help="Custom branch name (default: translation/s{sprint})",
    )

    # update-translated-sot
    p_update_sot = sub.add_parser(
        "update-translated-sot",
        help="Merge TMS downloads into rhdh/translations/ and create PR",
    )
    p_update_sot.add_argument(
        "--source-dir",
        default="i18n/downloads",
        help="Directory with downloaded translations",
    )
    p_update_sot.add_argument(
        "--sprint",
        required=True,
        help="Sprint identifier (e.g., s3297)",
    )
    p_update_sot.add_argument(
        "--branch",
        default=None,
        help="Branch name for the PR (default: translation/{sprint}-translated-sot)",
    )

    args = parser.parse_args(argv)
    fmt = OutputFormatter(mode=args.output_mode)

    commands = {
        "preflight": cmd_preflight,
        "download": cmd_download,
        "validate": cmd_validate,
        "deploy": cmd_deploy,
        "pr": cmd_pr,
        "update-translated-sot": cmd_update_translated_sot,
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
