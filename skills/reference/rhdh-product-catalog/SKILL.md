---
name: rhdh-product-catalog
description: >-
  Read-only queries over rhdh-plugin-export-overlays for an RHDH release:
  Package metadata (npm/workspaces), Extensions Plugin catalog (tiles,
  all.yaml), support levels, core/OOTB (default.packages.yaml), diffs between
  versions, export txt alignment, and plugin vs package support alignment.
  Use when asking what packages or plugins are in RHDH 1.9/1.10/main, support
  levels, default catalog membership, core/OOTB, what changed between releases,
  export list consistency, or whether plugin and package support match.
  Prefer RHDH_OVERLAY_REPO or --repo for a local overlay checkout. Do not use
  for overlay onboarding, version bumps, CI/PRs (overlay), platform EOL
  (lifecycle), CVE exports, or local enablement (rhdh-local).
compatibility: "Python 3.9+, git; optional local checkout of rhdh-plugin-export-overlays."
---

# RHDH product catalog

Read-only inspection of [rhdh-plugin-export-overlays](https://github.com/redhat-developer/rhdh-plugin-export-overlays) for a release. **Run the scripts** — do not parse overlay YAML in the model. Never `git checkout` the user's overlay tree.

## Which script?

| User need | Script |
|-----------|--------|
| npm packages, workspaces, export txt lists, package diff | `scripts/list_packages.py` |
| Extensions catalog plugins, all.yaml, pre-installed YAML, plugin diff, support alignment | `scripts/list_plugins.py` |
| Both views (e.g. “notifications on main”) | Run **both** for the same version/ref |

Resolve paths from this `SKILL.md`:

```bash
PACKAGES="$(dirname "$SKILL_MD")/scripts/list_packages.py"
PLUGINS="$(dirname "$SKILL_MD")/scripts/list_plugins.py"
```

## Quick start

```bash
python3 "$PACKAGES" 1.10
python3 "$PACKAGES" main --workspace scorecard --support ga
python3 "$PACKAGES" --diff 1.9 1.10
python3 "$PACKAGES" main --compare-txt --core

python3 "$PLUGINS" 1.10 --in-catalog --support ga
python3 "$PLUGINS" main --support-alignment
python3 "$PLUGINS" --diff 1.9 1.10 --json

export RHDH_OVERLAY_REPO=~/src/rhdh-plugin-export-overlays
python3 "$PACKAGES" 1.10 --repo "$RHDH_OVERLAY_REPO"
python3 "$PLUGINS" main --repo "$RHDH_OVERLAY_REPO"
```

If the user omitted a version, ask once. For `--diff`, both versions are required. Do not default a numbered release to `main`.

`/ask-rhdh` routes release inventory / support / catalog questions here.

## Workflow

1. Map the request to a version or git ref (`1.10`, `main`, `release-1.10`). Two versions + “what changed” → `--diff FROM TO` on the appropriate script.
2. Prefer a local overlay checkout (`--repo` or `RHDH_OVERLAY_REPO`) — ~10× faster than a sparse clone.
3. Return the script markdown as-is. Use `--json` only for follow-up filtering, not as the user-facing answer.
4. Re-run with filters; do not hand-filter a previous dump.

**Packages:** `references/packages.md`  
**Plugins:** `references/plugins.md`

## Data model

```
rhdh-plugin-export-overlays @ ref
├── workspaces/*/metadata/*.yaml     → list_packages.py  (kind: Package)
├── catalog-entities/.../plugins/    → list_plugins.py  (kind: Plugin)
├── default.packages.yaml            → Core OOTB (both scripts)
├── rhdh-community-packages.txt      → list_packages.py --compare-txt
└── rhdh-supported-packages.txt      → list_packages.py --compare-txt
```

**Plugin** = catalog tile. **Package** = npm artifact. One plugin often maps to several packages via `spec.packages`.

## Version → overlay ref

| User says | Git ref |
|-----------|---------|
| `1.9`, `1.9.3` | `release-1.9` |
| `1.10`, `1.10.3` | `release-1.10` |
| `main`, `next`, unreleased | `main` |
| explicit branch or tag | used as-is |

## Overlay repo

Sparse clone by default (~2s). Local git checkout strongly preferred.

| Priority | Source |
|----------|--------|
| 1 | `--repo PATH` |
| 2 | `RHDH_OVERLAY_REPO` |
| 3 | `rhdh` CLI `get_overlay_repo()` |
| 4 | Auto-discovery of `rhdh-plugin-export-overlays` |
| 5 | Temp sparse clone from GitHub |

| Flag | Purpose |
|------|---------|
| `--repo PATH` | Local overlay checkout |
| `--ref REF` | Override mapped ref |
| `--workdir` | Read working tree (list modes only; not with `--diff`) |

Reads use `git cat-file` at the ref — never checkout the user's branch.

## Packages (`list_packages.py`)

Grouped by **workspace** → support level.

| Flag | Purpose |
|------|---------|
| `--support` | ga / tp / dp / community |
| `--workspace` | workspace substring |
| `--package` | name/title substring |
| `--core` / `--enabled-ootb` / `--disabled-ootb` | `default.packages.yaml` |
| `--diff FROM TO` | support, lifecycle, added, removed |
| `--compare-txt` | vs community/supported export txt lists |

## Plugins (`list_plugins.py`)

Grouped by **Included in the Catalog** vs **Packaged, but Not in Catalog** → support level.

| Flag | Purpose |
|------|---------|
| `--in-catalog` / `--not-in-catalog` | `all.yaml` membership |
| `--pre-installed` / `--custom` | plugin YAML annotation |
| `--support` / `--name` / `--lifecycle` | filters |
| `--core` / `--enabled-ootb` / `--disabled-ootb` | core product list |
| `--diff FROM TO` | support, lifecycle, added, removed |
| `--support-alignment` | plugin vs linked package support (manual review) |

## Core OOTB (`default.packages.yaml`)

| Layer | Rule |
|-------|------|
| **Package** | match `spec.packageName` → enabled / disabled |
| **Plugin** | derive from linked packages (enabled / disabled / mixed) |

Source: [`default.packages.yaml`](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/default.packages.yaml) on the overlay ref.

## Out of scope

- Mutate overlay (onboard, bump, CI, PRs) → `/rhdh-overlay`
- Platform/vendor EOL → `/rhdh-platform-lifecycle`
- CVE CSV for GA workspaces → `/rhdh-overlay-cve-export`
- Enable plugins locally → `/rhdh-local`

## Completion

Complete when the user has the script markdown for the requested version or diff,
with the overlay git ref named. For `--support-alignment`, report mismatch counts
and list plugins that need manual review. For `--compare-txt`, report alignment
counts per list. Re-run with filters rather than hand-filtering a prior dump.
This skill is read-only — it never checks out or edits the user's overlay tree.

## Tests

```bash
python3 -m unittest discover -s skills/reference/rhdh-product-catalog/tests -p 'test_*.py'
```
