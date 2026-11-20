# Repository layouts

## Plugins monorepos

Checkouts shaped like `redhat-developer/rhdh-plugins` or
`redhat-developer/community-plugins`:

- Root contains `workspaces/<name>/`
- Each workspace has its own `yarn.lock` and usually `packages/app|backend` runners
  plus `plugins/…` published packages

Flags and env:

| Input | Role |
| --- | --- |
| `--repo-root <path>` | Local checkout for `yarn.lock` / `yarn why` |
| `RHDH_PLUGINS_ROOT` | Fallback when `--repo-root` omitted |
| `--repo <owner/name>` | Remote GitHub repo for Dependabot REST |
| `GITHUB_REPOSITORY` / `origin` | Fallbacks for `--repo` |
| `GH_TOKEN` / `GITHUB_TOKEN` | Dependabot read/write (prefer env; fullsend mints these) |
| `--alerts-json <file>` | Fullsend / offline snapshot (no REST) |

Prefer `yarn install` in the target workspace before classify so `yarn why -R`
resolves.

## RHDH core (`redhat-developer/rhdh`)

Single-root Yarn workspace: root `yarn.lock` + `packages/` (+ `plugins/`,
`backstage.json`). Detected as layout `rhdh-core`. Workspace token `rhdh`
(aliases `.`, `root`). Default Dependabot repo: `redhat-developer/rhdh`.

Product alert/bump scope is root + `packages/**` + `plugins/**` only.
`e2e-tests/` and `.ci/` stay separate tokens when needed.

**Temporary (REMOVE WHEN `release-1.10` EOL):** on the release-1.10 train
only, product / main Dependabot alerts are assumed to also apply to
wrapped plugins under `dynamic-plugins/`, and that package list drives a
second `yarn up -R` there when still vulnerable. Imperfect but closes a
patching gap — see [rhdh-core.md](rhdh-core.md) and
`scripts/release-1.10-dual-lockfile.js`. `main` and `release-2.1+` remain
root-only. There is no `dynamic-plugins` workspace token. Scheduled CVE
workflows that set `--base release-1.10` live in the **rhdh core** repo;
plugins-monorepo Fullsend schedules omit that path.

Env fallback: `RHDH_CORE_ROOT`.
