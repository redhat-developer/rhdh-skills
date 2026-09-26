"""Output formatting and preflight checks for translation skills.

Bundled with this skill so it runs installed alone. A sibling skill
carrying something similar is expected, not a defect.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
BOLD = "\033[1m"
NC = "\033[0m"


def _color_enabled() -> bool:
    return os.environ.get("NO_COLOR") is None


# ---------------------------------------------------------------------------
# OutputFormatter — TTY-aware human / JSON output
# ---------------------------------------------------------------------------


def detect_output_mode() -> str:
    return "human" if sys.stdout.isatty() else "json"


@dataclass
class OutputFormatter:
    """Formats CLI output as JSON or human-readable."""

    mode: str = "auto"
    verbose: bool = False
    _debug_info: dict[str, Any] = field(default_factory=dict)
    _color: bool = field(default=True, repr=False)

    def __post_init__(self) -> None:
        if self.mode == "auto":
            self.mode = detect_output_mode()
        self._color = _color_enabled()

    # -- human helpers -------------------------------------------------------

    def log_ok(self, msg: str) -> None:
        if self.mode == "human":
            pfx = f"{GREEN}✓{NC}" if self._color else "✓"
            print(f"{pfx} {msg}", file=sys.stderr)

    def log_warn(self, msg: str) -> None:
        if self.mode == "human":
            pfx = f"{YELLOW}⚠{NC}" if self._color else "⚠"
            print(f"{pfx} {msg}", file=sys.stderr)

    def log_fail(self, msg: str) -> None:
        if self.mode == "human":
            pfx = f"{RED}✗{NC}" if self._color else "✗"
            print(f"{pfx} {msg}", file=sys.stderr)

    def log_info(self, msg: str) -> None:
        if self.mode == "human":
            pfx = f"{BLUE}ℹ{NC}" if self._color else "ℹ"
            print(f"{pfx} {msg}", file=sys.stderr)

    # -- structured output ---------------------------------------------------

    def success(
        self,
        data: Any,
        *,
        next_steps: Optional[list[str]] = None,
    ) -> None:
        envelope: dict[str, Any] = {"success": True, "data": data}
        if next_steps:
            envelope["next_steps"] = next_steps
        if self.mode == "json":
            print(json.dumps(envelope, indent=2, default=str))

    def error(
        self,
        message: str,
        *,
        next_steps: Optional[list[str]] = None,
    ) -> None:
        envelope: dict[str, Any] = {
            "success": False,
            "error": message,
        }
        if next_steps:
            envelope["next_steps"] = next_steps
        if self.mode == "json":
            print(json.dumps(envelope, indent=2, default=str))
        else:
            self.log_fail(message)


# ---------------------------------------------------------------------------
# Preflight: repo discovery
# ---------------------------------------------------------------------------

REPOS = ("rhdh-plugins", "rhdh", "community-plugins", "backstage")

# Environment variables that override auto-detection per repo
_REPO_ENV = {
    "rhdh-plugins": "RHDH_PLUGINS_REPO_PATH",
    "rhdh": "RHDH_REPO_PATH",
    "community-plugins": "COMMUNITY_PLUGINS_REPO_PATH",
    "backstage": "BACKSTAGE_REPO_PATH",
}


def find_repo(name: str, *, search_root: Optional[str] = None) -> Optional[Path]:
    """Locate a repo by name.

    Priority:
      1. Environment variable (e.g. RHDH_REPO_PATH)
      2. Sibling of *search_root* (or cwd) with the expected directory name
    """
    env_key = _REPO_ENV.get(name)
    if env_key:
        env_val = os.environ.get(env_key)
        if env_val:
            p = Path(env_val)
            if p.is_dir():
                return p

    base = Path(search_root) if search_root else Path.cwd()
    # Walk up to find a common parent that might contain all repos
    for ancestor in (base, base.parent, base.parent.parent):
        candidate = ancestor / name
        if candidate.is_dir() and (candidate / ".git").exists():
            return candidate
    return None


def find_all_repos(*, search_root: Optional[str] = None) -> dict[str, Optional[Path]]:
    """Return {repo_name: Path | None} for every expected repo."""
    return {name: find_repo(name, search_root=search_root) for name in REPOS}


# ---------------------------------------------------------------------------
# Preflight: git helpers
# ---------------------------------------------------------------------------


def git_is_clean(repo: Path) -> bool:
    """True when the working tree has no uncommitted changes."""
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    return r.returncode == 0 and r.stdout.strip() == ""


def git_current_branch(repo: Path) -> Optional[str]:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    return r.stdout.strip() if r.returncode == 0 else None


# ---------------------------------------------------------------------------
# Preflight: tool discovery
# ---------------------------------------------------------------------------


def find_node_tool(name: str) -> Optional[str]:
    """Find node/npx/yarn on PATH."""
    return shutil.which(name)


def find_translations_cli(
    rhdh_plugins_path: Path,
) -> Optional[Path]:
    """Find translations-cli binary inside the rhdh-plugins translations workspace."""
    cli_bin = (
        rhdh_plugins_path
        / "workspaces"
        / "translations"
        / "packages"
        / "cli"
        / "bin"
        / "translations-cli"
    )
    if cli_bin.exists():
        return cli_bin
    return None


def find_memsource_cli() -> Optional[str]:
    """Find memsource CLI on PATH."""
    return shutil.which("memsource")


# ---------------------------------------------------------------------------
# Preflight: TMS credentials
# ---------------------------------------------------------------------------


def check_tms_credentials() -> dict[str, bool]:
    """Check which TMS env vars are set."""
    return {
        "MEMSOURCE_URL": bool(os.environ.get("MEMSOURCE_URL")),
        "MEMSOURCE_TOKEN": bool(os.environ.get("MEMSOURCE_TOKEN")),
        "MEMSOURCE_USERNAME": bool(os.environ.get("MEMSOURCE_USERNAME")),
    }


# ---------------------------------------------------------------------------
# SOT: load source-of-truth translation files
# ---------------------------------------------------------------------------


def _sot_prefix(repo_name: str) -> str:
    """Map repo name to SOT file prefix."""
    sot_prefix_map = {
        "rhdh-plugins": "rhdh-plugins",
        "rhdh": "rhdh",
        "community-plugins": "community-plugins",
        "backstage": "backstage",
    }
    return sot_prefix_map.get(repo_name, repo_name)


def load_sot_keys(rhdh_repo: Path, repo_name: str) -> dict[str, set[str]]:
    """Load translated key names from the SOT for a given repo.

    Returns {plugin_name: {key1, key2, ...}} extracted from all language
    files for that repo in rhdh/translations/.

    The SOT structure is: { pluginName: { lang: { key: value } } }
    We union the key sets across all languages to get the complete set of
    keys that were translated in the previous release.
    """
    translations_dir = rhdh_repo / "translations"
    if not translations_dir.is_dir():
        return {}

    prefix = _sot_prefix(repo_name)
    result: dict[str, set[str]] = {}

    for json_file in sorted(translations_dir.glob(f"{prefix}-*.json")):
        # The suffix after the prefix must be a language code (2–5 chars,
        # e.g. "de", "ja", "zh-CN") — skip files like rhdh-plugins-de.json
        # when the prefix is "rhdh".
        lang_part = json_file.stem[len(prefix) + 1 :]
        if not (2 <= len(lang_part) <= 5):
            continue
        # Skip the English reference file — that's handled separately
        if json_file.name == f"{prefix}-en.json" or json_file.name == "OWNERS":
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        for plugin_name, plugin_data in data.items():
            if not isinstance(plugin_data, dict):
                continue
            for _lang, lang_data in plugin_data.items():
                if not isinstance(lang_data, dict):
                    continue
                if plugin_name not in result:
                    result[plugin_name] = set()
                result[plugin_name].update(lang_data.keys())

    return result


def find_en_sot_dir(
    *, rhdh_plugins_repo: Path | None = None, rhdh_repo: Path | None = None
) -> Path | None:
    """Locate the EN SOT directory.

    Primary location: rhdh-plugins/workspaces/translations/sot/
    Fallback: rhdh/translations/ (legacy, for backward compatibility)
    """
    if rhdh_plugins_repo:
        sot_dir = rhdh_plugins_repo / "workspaces" / "translations" / "sot"
        if sot_dir.is_dir():
            return sot_dir
    if rhdh_repo:
        legacy = rhdh_repo / "translations"
        if legacy.is_dir():
            return legacy
    return None


def load_sot_english_values(en_sot_dir: Path, repo_name: str) -> dict[str, dict[str, str]]:
    """Load previous-release English values from the EN SOT.

    Looks for {prefix}-en.json in the EN SOT directory
    (rhdh-plugins/workspaces/translations/sot/). This file stores the
    English reference from the previous release:
        { pluginName: { en: { key: english_value } } }

    Returns {plugin_name: {key: english_value}}.
    If the file does not exist (first run), returns empty — the delta will
    treat all existing keys as unchanged by value.
    """
    if not en_sot_dir.is_dir():
        return {}

    prefix = _sot_prefix(repo_name)
    en_file = en_sot_dir / f"{prefix}-en.json"
    if not en_file.exists():
        return {}

    return load_reference_keys(en_file)


def load_reference_keys(
    reference_file: Path,
) -> dict[str, dict[str, str]]:
    """Load English keys from a generated reference file.

    The reference structure is: { pluginName: { en: { key: value } } }
    Returns {plugin_name: {key: english_value}}.
    """
    if not reference_file.exists():
        return {}
    try:
        data = json.loads(reference_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    result: dict[str, dict[str, str]] = {}
    if not isinstance(data, dict):
        return result

    for plugin_name, plugin_data in data.items():
        if not isinstance(plugin_data, dict):
            continue
        en_data = plugin_data.get("en", {})
        if isinstance(en_data, dict):
            result[plugin_name] = {k: v for k, v in en_data.items() if isinstance(v, str)}

    return result


def compute_delta(
    current_keys: dict[str, dict[str, str]],
    sot_keys: dict[str, set[str]],
    *,
    previous_english: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compare current extraction against SOT and return delta.

    *previous_english*, when provided, maps plugin → {key: old_english_value}.
    Keys whose English value changed compared to the previous release are
    treated as needing re-translation and included in ``changed_keys``.

    Returns:
        {
            "new_plugins": {plugin: {key: value, ...}},
            "new_keys": {plugin: {key: value, ...}},
            "changed_keys": {plugin: {key: value, ...}},
            "removed_plugins": [plugin, ...],
            "removed_keys": {plugin: [key, ...]},
            "summary": {
                "new_plugin_count": int,
                "new_key_count": int,
                "changed_key_count": int,
                "removed_plugin_count": int,
                "removed_key_count": int,
                "unchanged_key_count": int,
            },
        }
    """
    if previous_english is None:
        previous_english = {}

    new_plugins: dict[str, dict[str, str]] = {}
    new_keys: dict[str, dict[str, str]] = {}
    changed_keys: dict[str, dict[str, str]] = {}
    removed_plugins: list[str] = []
    removed_keys: dict[str, list[str]] = {}

    all_sot_plugins = set(sot_keys.keys())
    all_current_plugins = set(current_keys.keys())

    new_key_count = 0
    changed_key_count = 0
    removed_key_count = 0
    unchanged_key_count = 0

    # Plugins that are entirely new
    for plugin in sorted(all_current_plugins - all_sot_plugins):
        new_plugins[plugin] = current_keys[plugin]
        new_key_count += len(current_keys[plugin])

    # Plugins removed since last release
    removed_plugins = sorted(all_sot_plugins - all_current_plugins)
    for plugin in removed_plugins:
        removed_key_count += len(sot_keys[plugin])

    # Plugins present in both — find new, changed, and removed keys
    for plugin in sorted(all_current_plugins & all_sot_plugins):
        current = set(current_keys[plugin].keys())
        previous = sot_keys[plugin]

        added = current - previous
        removed = previous - current
        common = current & previous

        # Detect changed English values among common keys
        old_en = previous_english.get(plugin, {})
        plugin_changed: dict[str, str] = {}
        for key in sorted(common):
            old_val = old_en.get(key)
            new_val = current_keys[plugin][key]
            if old_val is not None and old_val != new_val:
                plugin_changed[key] = new_val

        unchanged_key_count += len(common) - len(plugin_changed)

        if added:
            new_keys[plugin] = {k: current_keys[plugin][k] for k in sorted(added)}
            new_key_count += len(added)

        if plugin_changed:
            changed_keys[plugin] = plugin_changed
            changed_key_count += len(plugin_changed)

        if removed:
            removed_keys[plugin] = sorted(removed)
            removed_key_count += len(removed)

    return {
        "new_plugins": new_plugins,
        "new_keys": new_keys,
        "changed_keys": changed_keys,
        "removed_plugins": removed_plugins,
        "removed_keys": removed_keys,
        "summary": {
            "new_plugin_count": len(new_plugins),
            "new_key_count": new_key_count,
            "changed_key_count": changed_key_count,
            "removed_plugin_count": len(removed_plugins),
            "removed_key_count": removed_key_count,
            "unchanged_key_count": unchanged_key_count,
        },
    }


def build_delta_reference(
    delta: dict[str, Any],
    current_keys: dict[str, dict[str, str]],
) -> dict[str, dict[str, dict[str, str]]]:
    """Build a reference JSON containing only new/changed keys for TMS upload.

    Returns the same { plugin: { en: { key: value } } } structure but only
    with keys that need translation — new keys plus keys whose English
    value changed since the previous release.
    """
    result: dict[str, dict[str, dict[str, str]]] = {}

    # Include all keys from new plugins
    for plugin, keys in delta["new_plugins"].items():
        result[plugin] = {"en": keys}

    # Include new keys from existing plugins
    for plugin, keys in delta["new_keys"].items():
        if plugin not in result:
            result[plugin] = {"en": {}}
        result[plugin]["en"].update(keys)

    # Include keys whose English value changed
    for plugin, keys in delta.get("changed_keys", {}).items():
        if plugin not in result:
            result[plugin] = {"en": {}}
        result[plugin]["en"].update(keys)

    return result


# ---------------------------------------------------------------------------
# RHDH-priority merge for backstage overlapping keys
# ---------------------------------------------------------------------------


def apply_rhdh_overrides(
    backstage_keys: dict[str, dict[str, str]],
    rhdh_keys: dict[str, dict[str, str]],
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """Apply RHDH-priority values to overlapping backstage keys.

    RHDH customises certain Backstage strings (e.g. "Create" → "Self-service").
    When both repos define the same plugin+key but with different English
    values, the RHDH value wins because that is what end-users see.

    Args:
        backstage_keys: {plugin: {key: english_value}} from backstage extraction.
        rhdh_keys: {plugin: {key: english_value}} from rhdh extraction.

    Returns:
        (merged_backstage_keys, overrides_report)
        - merged_backstage_keys: backstage_keys with RHDH values applied.
        - overrides_report: list of {plugin, key, backstage_value, rhdh_value}
          for every key that was overridden.
    """
    merged = {p: dict(kv) for p, kv in backstage_keys.items()}
    report: list[dict[str, str]] = []

    for plugin in sorted(set(merged) & set(rhdh_keys)):
        for key in sorted(set(merged[plugin]) & set(rhdh_keys[plugin])):
            bs_val = merged[plugin][key]
            rhdh_val = rhdh_keys[plugin][key]
            if bs_val != rhdh_val:
                merged[plugin][key] = rhdh_val
                report.append(
                    {
                        "plugin": plugin,
                        "key": key,
                        "backstage_value": bs_val,
                        "rhdh_value": rhdh_val,
                    }
                )

    return merged, report
