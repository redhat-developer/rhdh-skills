# RHDH core CVE bumps

`redhat-developer/rhdh` is a **single Yarn workspace** (root `yarn.lock`,
`packages/*` + `plugins/*`). It is **not** an `rhdh-plugins`-style
`workspaces/<name>/` monorepo.

`--repo-root` is the repo root (for example `/path/to/rhdh`). Workspace token
is `rhdh` (aliases: `.`, `root`). Dependabot alerts live on
`redhat-developer/rhdh` — always pass `--repo redhat-developer/rhdh` (fork
`origin` is the wrong alert source).

Default bump scope is the **product** lockfile: `yarn.lock`, `package.json`,
`packages/**`, `plugins/**`. `e2e-tests/` and `.ci/` are excluded unless you
pass those paths explicitly. Package discovery always starts from the product Dependabot list.

## Classification (do not reuse runner dismiss)

| Label | Meaning | Customer impact |
|-------|---------|-----------------|
| `CORE_PROD` | Reached via `packages/app`, `app-next`, `backend`, or `plugin-utils` production deps | **high** — these **ship in RHDH**. Never dismiss |
| `PLUGIN_PROD` | Reached via in-tree `plugins/*` production deps (private plugins still ship) | **high** — never dismiss |
| `CORE_DEV` | Reached only via those packages' `devDependencies` | local-dev / SBOM; bump when practical |
| `PLUGIN_DEV` | In-tree plugin harness / tests | local-dev / SBOM |
| `WORKSPACE_DEV` | Root `package.json` `devDependencies` | local-dev / SBOM |
| `RUNNER` | **Does not apply.** `packages/app` and `packages/backend` are not local-dev shells here | — |

Never treat `packages/app` or `packages/backend` as `RUNNER`. That label is
only for plugins-monorepo demo apps.

## Commands

`SKILL_DIR` is this skill directory. `REPO` is the rhdh checkout.

```bash
REPO=/path/to/rhdh
GH=redhat-developer/rhdh

node "$SKILL_DIR/scripts/prepare-workspace-bump.js" --repo-root "$REPO" rhdh

node "$SKILL_DIR/scripts/list-dependabot-packages.js" --repo "$GH" rhdh --json

node "$SKILL_DIR/scripts/classify-cve-source.js" --repo-root "$REPO" rhdh lodash --table

GITHUB_TOKEN=… node "$SKILL_DIR/scripts/check-dependabot-patch-status.js" \
  --repo-root "$REPO" --repo "$GH" rhdh

node "$SKILL_DIR/scripts/bump-workspace-packages.js" \
  --repo-root "$REPO" --repo "$GH" rhdh --json \
  | node "$SKILL_DIR/scripts/format-bump-pr.js" --with-title
```

On rhdh-core you may omit `rhdh` and pass package names directly when
`--repo-root` already points at the checkout.

PR title from `format-bump-pr.js`: `fix(deps): bump yarn.lock packages for Dependabot CVEs`.
Pass `--base release-X.Y` (or infer from the current git branch) for
`[release-X.Y] fix(deps): …`.

Bump pipeline on core: `yarn up -R`, then `yarn install` only. **Do not run
`yarn dedupe` by default** — older release branches (for example 1.10) have
lost large `@react-aria/*` / `@react-stately/*` lockfile sections when CVE
bumps deduped as a silent side effect, breaking `@backstage/ui` resolves.
Pass `--dedupe` only for intentional Backstage / lockfile normalization
(same role as `scripts/update-backstage.mjs`). Plugins monorepos still
dedupe by default. Allowlisted ancestor bumps and react-router pair sync
still apply. Never `yarn up` `@backstage/*` or `@backstage-community/*`.

Sandbox / Fullsend tip: set `YARN_ENABLE_GLOBAL_CACHE=false`,
`YARN_CACHE_FOLDER=$PWD/.yarn/cache`, and `YARN_ENABLE_MIRROR=false`. Under
Fullsend always pass `--alerts-json` with the staged snapshot (no PAT / REST
in the sandbox). `prepare-workspace-bump.js` auto-selects `--verify-only`
when `FULLSEND_OUTPUT_DIR` is set.

## release-1.10 dual lockfile (temporary — REMOVE WHEN EOL)

**Only** `redhat-developer/rhdh` on the `release-1.10` train. `main`,
`release-2.1+`, and plugins monorepos stay **root `yarn.lock` only**.

Any GitHub Actions / Fullsend CVE **schedule** that passes `--base
release-1.10` (or sets `CVE_BASE_BRANCH`, read by `resolveBumpBase` when
`--base` is omitted) belongs in the **rhdh core** repo, not in
`rhdh-plugins` / `community-plugins`. The plugins Fullsend CVE schedule
(`fullsend-cve-schedule.yml`) stays workspace×`main` and can omit
release-branch / dual-lockfile wiring entirely.

On release-1.10 the same Dependabot package list may also need
`yarn up -R` under `dynamic-plugins/yarn.lock` (independent resolved
versions). Implementation lives in
`scripts/release-1.10-dual-lockfile.js` — delete that file and its imports
when 1.10 is EOL.

### Assumption (intentional, imperfect)

For release-1.10, **Dependabot alerts discovered for the product / main-line
package set are assumed to also apply to wrapped plugins under
`dynamic-plugins/`**, even when Dependabot has not (or has not yet) filed a
matching alert on that sibling lockfile. That is not always accurate — version
lines and advisory ranges can differ — but treating the product alert list as
the candidate set for both lockfiles closes a patching gap that a
product-only bump would leave open. After candidates are chosen, scoring
still uses **resolved version + advisory range** per lockfile (a sibling line
already outside the range stays `ok` / `n/a`, not a blind bump).

Behavior when `--base release-1.10` is set, `CVE_BASE_BRANCH=release-1.10`
is set, **or** the current branch resolves to `release-1.10` (Fullsend
chore branches included):

1. Discover packages from the product Dependabot list (and any
   `dynamic-plugins/` alerts present) — one list; no separate workspace token.
   Prefer the product / main alert set as the driver for sibling candidates.
2. Bump the root product lockfile as usual (`--no-dedupe` / core default).
3. For packages from that list still vulnerable in `dynamic-plugins/yarn.lock`,
   run `yarn up -R` + `yarn install` in `dynamic-plugins/` (never dedupe).
4. Emit `dualLockfile` on bump `--json` (gap table + sibling bump outcome).

One bump run → both lockfiles dirty in the same checkout → **one PR**
(commit root `yarn.lock` and `dynamic-plugins/` together). Do not open a
separate follow-up PR for the sibling lockfile.

```bash
# Interactive / worktree
git fetch upstream release-1.10
git worktree add -B chore/rhdh-cve-bumps-release-1.10 "$WT" upstream/release-1.10

node "$SKILL_DIR/scripts/bump-workspace-packages.js" \
  --repo-root "$WT" --repo redhat-developer/rhdh --base release-1.10 rhdh --json \
  | node "$SKILL_DIR/scripts/format-bump-pr.js" --with-title --base release-1.10

# Fullsend (branch already checked out; staged alerts snapshot)
node "$SKILL_DIR/scripts/workspace-cve-bump.js" \
  --repo-root "$REPO" --workspace rhdh \
  --alerts-json "$FULLSEND_OUTPUT_DIR/dependabot-alerts.json" --json
# base inferred from HEAD when it contains release-1.10
```

Lockfile-only refresh after tip moved: reset to tip + re-bump (core
`--no-dedupe` default), not conflicted `git rebase` on `yarn.lock`.

## Dismiss

Do **not** dismiss `CORE_PROD` or `PLUGIN_PROD`. There is no
`PATCHED_EXCEPT_RUNNER` path on this repo.

Exact `CORE_DEV` / `PLUGIN_DEV` / `WORKSPACE_DEV` may be dismissed
interactively (same policy as plugins), but prefer a lockfile bump so the
SBOM stays clean. Pass `yarn.lock` (not a workspace name) to
`close-dependabot-alerts.js` when `--repo` is `…/rhdh`.
