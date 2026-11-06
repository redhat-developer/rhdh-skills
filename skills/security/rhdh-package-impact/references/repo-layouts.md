# Repository layouts

## Supported today: plugins monorepos

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

Prefer `yarn install` in the target workspace before classify so `yarn why -R`
resolves.

## Future: `redhat-developer/rhdh`

The midstream / app monorepo does not use the same `workspaces/<name>/` plugin
layout. Until classify and bump grow an explicit layout adapter for it, refuse
with a clear error rather than inventing paths. Keep using `--repo-root` as the
primary flag so the env name does not hard-wire “plugins only.”
