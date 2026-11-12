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
pass those paths explicitly.

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
`--repo-root` already points at the checkout:

```bash
node "$SKILL_DIR/scripts/bump-workspace-packages.js" \
  --repo-root "$REPO" --repo "$GH" lodash qs --dry-run
```

PR title from `format-bump-pr.js`: `fix(deps): bump yarn.lock packages for Dependabot CVEs`.

Bump pipeline on core: `yarn up -R`, then `yarn install` only. **Do not run
`yarn dedupe` by default** — older release branches (for example 1.10) have
lost large `@react-aria/*` / `@react-stately/*` lockfile sections when CVE
bumps deduped as a silent side effect, breaking `@backstage/ui` resolves.
Pass `--dedupe` only for intentional Backstage / lockfile normalization
(same role as `scripts/update-backstage.mjs`). Plugins monorepos still
dedupe by default. Allowlisted ancestor bumps and react-router pair sync
still apply. Never `yarn up` `@backstage/*` or `@backstage-community/*`.

Sandbox tip: set `YARN_ENABLE_GLOBAL_CACHE=false`,
`YARN_CACHE_FOLDER=$PWD/.yarn/cache`, and `YARN_ENABLE_MIRROR=false` so Yarn
does not write `~/.yarn/berry/cache` during bumps.

## Dismiss

Do **not** dismiss `CORE_PROD` or `PLUGIN_PROD`. There is no
`PATCHED_EXCEPT_RUNNER` path on this repo.

Exact `CORE_DEV` / `PLUGIN_DEV` / `WORKSPACE_DEV` may be dismissed
interactively (same policy as plugins), but prefer a lockfile bump so the
SBOM stays clean. Pass `yarn.lock` (not a workspace name) to
`close-dependabot-alerts.js` when `--repo` is `…/rhdh`.
