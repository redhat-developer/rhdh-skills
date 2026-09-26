---
name: rhdh-backport
description: >
  Automate the RHDH plugin backport process from PR cherry-pick to changelog.
  Handles: cherry-pick with AI conflict resolution, PR creation,
  CI monitoring, auto-merge, Version Packages detection, and overlays update.
  Pre-2.1: release-x.y/{plugin} per-plugin branches. 2.1+: unified release-x.y branch.
  Accepts a release version and PR number/URL. Auto-detects plugin from PR files.
  Modes: auto (full workflow), create (PR only, stops for review), finish (after manual merge).
  Use when you need to backport changes to a release branch (e.g., "backport PR #3456 to 1.10").
---

<essential_principles>

<principle name="script_driven">
All mechanical work is done by `scripts/backport.py`. The agent's role is:
1. Validate prerequisites
2. Run the script
3. Handle cherry-pick conflicts if the script exits with code 2
4. Report results
</principle>

<principle name="ai_conflict_resolution">
When the script exits with code 2 (cherry-pick conflict), it saves state to a JSON file
and prints the path as `STATE_FILE=<path>` to stderr. The agent must:

1. Read the state file to get the list of conflicting files
2. Present the user with TWO options:
   - Option 1: Let the skill resolve conflicts (AI auto-resolution)
   - Option 2: User resolves manually (abort)

If user chooses Option 1:
- Read each conflicting file (with conflict markers)
- Understand both sides of the conflict using `git log` and `git show`
- Generate intelligent resolution
- Write resolved files using Edit tool
- Validate syntax (npx tsc --noEmit for TypeScript)
- Check no conflict markers remain
- Run: `git add . && git cherry-pick --continue`
- Re-run script with `--continue-from <state_file>`

If user chooses Option 2:
- Print manual resolution instructions and stop

See `references/ai-conflict-resolution.md` for detailed resolution strategies.
</principle>

</essential_principles>

## Prerequisites

- **`gh` CLI** — installed and authenticated
- **Git access** — to `rhdh-plugins`
- **Fork** — of `rhdh-plugins` with `origin` remote pointing to fork
- **`upstream` remote** — pointing to `redhat-developer/rhdh-plugins`
- **Python 3.9+** — for the backport script

---

## Usage

```bash
/backport <release-version> <pr-source> [--mode auto|create|finish]
```

**Examples:**
```bash
# Full automation (default)
/backport 1.10 3456
/backport 2.1 3456
/backport 1.9 https://github.com/redhat-developer/rhdh-plugins/pull/2345

# Create PR only, stop for manual review
/backport 1.10 3456 --mode create

# Complete after manual PR merge
/backport 1.10 3456 --mode finish
```

---

## Modes

### auto (default) — Full workflow

Runs all 11 steps end-to-end. Zero intervention required.

```bash
python scripts/backport.py <release> <pr_source> --mode auto
```

### create — PR only, stops for review

Runs steps 1-7: workflow bootstrap, cherry-pick, push, create PR. Stops and prints the PR URL.
You review and merge manually, then run with `--mode finish`.

```bash
python scripts/backport.py <release> <pr_source> --mode create
```

### finish — After manual merge

Runs steps 8-11: Version Packages, overlays update, changelog.
Assumes PR #1 from `--mode create` is already merged.

```bash
python scripts/backport.py <release> <pr_source> --mode finish
```

---

## Branch strategies

The skill picks the branch model from the release version. **2.1 is the cutoff.**

### Unified release branch — 2.1+ (e.g. `release-2.1`)

- One branch per release, all workspaces (similar to `main`).
- Open patch PRs targeting `release-2.1` directly.
- Version Packages, overlays, and changelog steps are the same as pre-2.1.
- Version Packages PR comes from `maintenance-changesets-release/release-x.y/{plugin}`
  (per workspace; rhdh-plugins [#4854](https://github.com/redhat-developer/rhdh-plugins/pull/4854)).
- VP workflow on the unified branch is release-team owned (no #4173 bootstrap).
- The `release-2.1` branch must already exist and must be cut from `main` **after**
  [#4854](https://github.com/redhat-developer/rhdh-plugins/pull/4854) merges — the skill
  does not auto-create it.

### Per-plugin release branch — before 2.1 (e.g. `release-1.10/lightspeed`)

- One branch per plugin per release; supports concurrent backports.
- Open patch PRs targeting `release-x.y/{plugin}` directly.
- Version Packages PR comes from `maintenance-changesets-release/release-x.y/{plugin}`.
- npm publish uses dist-tag `maintenance`.
- Auto-creates the release branch from the latest plugin tag if missing.
- One-time #4173 VP workflow bootstrap per release branch (see below).

### Unsupported: `workspace/{plugin}`

- Removed from the prior-release workflow trigger in
  [#4854](https://github.com/redhat-developer/rhdh-plugins/pull/4854).
- Do not use for 1.9 / 1.10 / 2.1+ backports. Use `release-1.x/{plugin}` or `release-x.y`.
- Not automated by this skill.

---

## Workflow

### Steps 1-6 (create)

1. Parse arguments and fetch PR details
2. Auto-detect plugin from PR files (also detects yarn.lock-only changes)
3. **One-time VP workflow bootstrap** (pre-2.1 only) — verify
   `release_workspace_version.yml` on the release branch includes
   [#4173](https://github.com/redhat-developer/rhdh-plugins/pull/4173) changes;
   cherry-pick once if missing (skipped for yarn.lock-only and 2.1+ unified branches)
4. Check if already backported
5. Cherry-pick commit(s)
6. Push backport branch to fork
7. Create PR #1 (fork → release branch), monitor CI, merge

### Steps 8-11 (finish)

8. Detect and merge Version Packages PR (skipped for yarn.lock-only; cleans up stale per-workspace changesets branch)
9. Trigger overlays update workflow, /publish, wait for CI, merge
10. Create and merge changelog PR to main (skipped for yarn.lock-only)
11. Print summary

### Conflict handling (exit code 2)

If the script exits with code 2, cherry-pick had conflicts:

1. Parse `STATE_FILE=<path>` from stderr output
2. Load state: read the JSON file for `conflict_files` list
3. Ask user: resolve with AI or manually?

**AI resolution:**
```bash
# Read each conflicting file
# Analyze conflict markers
# Write resolution using Edit tool
# Then:
git add .
git cherry-pick --continue
python scripts/backport.py <release> <pr_source> --continue-from <state_file>
```

**Manual resolution:**
```
Print instructions and stop.
```

---

## Special Cases

### One-time workflow bootstrap per release branch (pre-2.1 only)

Before the first backport to a `release-x.y/{plugin}` branch (< 2.1) that expects an
npm release via changesets, the release branch must carry the updated
`.github/workflows/release_workspace_version.yml` from
[#4173](https://github.com/redhat-developer/rhdh-plugins/pull/4173) (commit `ef07585`).

**Why:** GitHub runs Prior Version Release Workspace using the workflow file **on the
target branch**, not on `main`. Release branches created before #4173 only trigger on
`workspace/**`, not `release-*/*`. Merging a backport with a changeset will **not**
open Version Packages without this fix.

The script checks automatically in `--mode auto` and `--mode create`. If the workflow
is missing the #4173 markers, it cherry-picks `ef07585` once (or syncs the workflow
file from `main`) and pushes to the release branch. **Do not repeat for every
backport** — only once per release branch.

Required markers in `release_workspace_version.yml`:

- `branches: ['workspace/**', 'release-*/*']`
- `version_branch_id` output for `release-*/*` base refs
- `versionBranch: maintenance-changesets-release/${{ version_branch_id }}`
- Stale-branch check uses `maintenance-changesets-release/release-x.y/{plugin}` (full base ref)

See `references/workflow-bootstrap.md` for manual bootstrap commands.

**2.1+ unified branches** (`release-2.1`, etc.) do not use this bootstrap — the
Version Packages workflow on those branches is owned by the release team and may
change as that work lands.

### Yarn.lock-only changes (CVE fixes)

When the PR only changes `yarn.lock` files (e.g., CVE dependency fix with no code changes),
the script automatically skips Version Packages (step 7) and changelog (step 9).
No npm release is needed — the overlays update (step 8) uses the merge commit directly as `repo-ref`.

### Stale Version Packages changesets branch

The Version Packages workflow fails if a stale changesets branch exists from a
previous cycle. The script deletes it per workspace before waiting for Version Packages:

| Release model | Stale branch cleaned |
|---------------|---------------------|
| Pre-2.1 per-plugin | `maintenance-changesets-release/release-x.y/{plugin}` |
| 2.1+ unified | `maintenance-changesets-release/release-x.y/{plugin}` (per workspace) |

Both prior-version models use the `maintenance-changesets-release/` prefix.
`main` publishes via a different workflow (`changesets-release/{plugin}/main`) and
is not used for backports.

---

## Script flags

| Flag | Description |
|------|-------------|
| `--mode auto` | Full workflow (default) |
| `--mode create` | Steps 1-7 only, creates PR #1 and stops |
| `--mode finish` | Steps 8-11, handles Version Packages, overlays, and changelog (after PR #1 merge) |
| `--continue-from FILE` | Resume after conflict resolution |
| `--force` | Skip already-backported check |
| `--json` | Structured JSON output to stdout |
| `--auto-approve` | Skip confirmation prompts |
| `--repo REPO` | Override plugins repo |
| `--overlays-repo REPO` | Override overlays repo |

---

## When NOT to Use

- **Multi-plugin PRs** — If PR touches multiple plugins, split into separate backports
- **Non-workspace changes** — If PR only changes CI, docs, or root-level files
- **Already backported** — Script will detect and exit early
- **Breaking changes** — Requires manual review and potential code adjustments

---

<reference_index>

## Reference Index

| Reference | Used for |
|-----------|----------|
| `references/ai-conflict-resolution.md` | AI conflict resolution strategies (agent reads on exit code 2) |
| `references/pr-detection.md` | PR source format documentation |
| `references/plugin-detection.md` | Plugin auto-detection logic |
| `references/overlays-lookup.md` | Overlays repo structure |
| `references/overlays-update.md` | Overlays update + /publish flow |
| `references/ci-monitoring.md` | CI monitoring and merge logic |
| `references/version-packages-detection.md` | Version Packages PR detection |
| `references/workflow-bootstrap.md` | One-time #4173 workflow bootstrap per release branch |
| `references/pr-creation.md` | PR templates and patterns |

</reference_index>

## Completion

Report the PR numbers and URLs for every PR created or merged (backport PR,
Version Packages PR, overlays PR, changelog PR), the plugin name, the release
version, the VP commit SHA, and the published npm version. For yarn.lock-only
changes, note that Version Packages and changelog were skipped. Take exact
values from script output rather than reconstructing them.
