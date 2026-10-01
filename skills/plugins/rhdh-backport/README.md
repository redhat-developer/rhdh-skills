# Backport Skill

Automate the RHDH plugin backport process — cherry-pick, PR creation, Version Packages, overlays update, and changelog.

## Quick Start

```bash
# Full automation — pre-2.1 per-plugin branch
/backport 1.10 3456

# Full automation — 2.1+ unified release branch
/backport 2.1 3456

# Create PR only, review manually
/backport 1.10 3456 --mode create

# Complete after manual merge
/backport 1.10 3456 --mode finish
```

## Branch models

| Release | Target branch | Example |
|---------|---------------|---------|
| < 2.1 | `release-x.y/{plugin}` | `release-1.10/lightspeed` |
| >= 2.1 | `release-x.y` | `release-2.1` |

VP, overlays, and changelog run for both models. Only the target branch shape differs.

## Modes

| Mode | Steps | Use when |
|------|-------|----------|
| `auto` (default) | 1-11 | Full hands-off backport |
| `create` | 1-7 | Want to review PR before merging |
| `finish` | 8-11 | After manually merging the backport PR |

## Features

- **Pre-2.1:** `release-x.y/{plugin}` branches — supports concurrent backports
- **2.1+:** unified `release-x.y` branch — all workspaces on one branch
  (`maintenance-changesets-release/release-x.y/{plugin}` for Version Packages)
- `workspace/{plugin}` is unsupported (removed in rhdh-plugins #4854)
- One-time #4173 workflow bootstrap per per-plugin release branch (pre-2.1 only)
- Auto-creates per-plugin release branch from latest tag if missing (< 2.1)
- AI conflict resolution for cherry-pick failures
- Yarn.lock-only changes (CVE fixes) skip Version Packages — no npm release needed
- Stale VP changesets branches auto-cleaned (per-plugin or per-workspace depending on release model)
- Works across `rhdh-plugins` and `rhdh-plugin-export-overlays` repos via GitHub API

## Prerequisites

- `gh` CLI installed and authenticated
- Fork of `rhdh-plugins` with `origin` remote
- `upstream` remote pointing to `redhat-developer/rhdh-plugins`
- Python 3.9+
- For 2.1+: `release-2.1` (or later) branch must already exist from the release cut
