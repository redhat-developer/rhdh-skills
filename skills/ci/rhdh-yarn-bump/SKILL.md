---
name: rhdh-yarn-bump
description: >-
  Bumps Yarn Berry across the RHDH repos — rhdh-plugins, rhdh midstream,
  rhdh-plugin-export-overlays, rhdh-cli, and GitLab CEE rhidp/rhdh and
  rhdh-plugin-catalog — with `yarn set version` plus install, and rewrites the
  pins Yarn cannot see: `packageManager`, `yarnPath`, `ENV YARN=`, and
  Containerfile lines. Use for "bump yarn to 4.17.1", "upgrade Yarn Berry across
  the repos", "weekly yarn bump", "which Yarn version is each repo pinned to",
  or scanning yarn pins.
compatibility: "Node, yarn, git, gh, jq on PATH; PRIVATE_TOKEN + gitlab.cee.redhat.com for GitLab CEE MRs."
---

# RHDH multi-repo Yarn bump

## Goal

Propagate a Yarn Berry 4.x bump across:

| Repo | Notes |
| --- | --- |
| [`redhat-developer/rhdh-plugins`](https://github.com/redhat-developer/rhdh-plugins) | root workspace (+ Fullsend if hardcoded) |
| [`redhat-developer/rhdh`](https://github.com/redhat-developer/rhdh) | root + nested workspaces + Containerfile |
| [`redhat-developer/rhdh-plugin-export-overlays`](https://github.com/redhat-developer/rhdh-plugin-export-overlays) | many `packageManager` pins |
| [`redhat-developer/rhdh-cli`](https://github.com/redhat-developer/rhdh-cli) | root `packageManager` / `yarnPath` |
| [`gitlab.cee.redhat.com/rhidp/rhdh`](https://gitlab.cee.redhat.com/rhidp/rhdh) | distgit binary + `ENV YARN=` (fetched CLI, same bytes as GitHub) |
| [`gitlab.cee.redhat.com/rhidp/rhdh-plugin-catalog`](https://gitlab.cee.redhat.com/rhidp/rhdh-plugin-catalog) | per-workspace pins + Containerfiles |

Renovate Yarn `packageManager` updates are disabled (RHIDP-17563). This skill is the bump path.

**Branch:** live line is `main` on GitHub and GitLab CEE.

## What actually changes

```bash
yarn set version <to>                 # packageManager + yarnPath + .yarn/releases
chmod +x .yarn/releases/yarn-<to>.cjs
yarn install --mode=update-lockfile
```

When `package.json` defines `prettier:check` or `prettier:fix`, `yarn-bump.sh` runs `yarn prettier --ignore-unknown --write` on the changed files before commit. Yarn writes `"**"` in `.yarnrc.yml`; Prettier (rhdh-cli) requires `'**'`.

Plus pins Yarn cannot see: `ENV YARN=`, Containerfile / Dockerfile `yarn_version=` and literal `yarn set version` (including versions not in `--from`; denylist pins stay). `yarn set version $yarn_version` is left as a variable.

`yarn-bump.sh` runs `curl -fsSL` once against `https://repo.yarnpkg.com/<to>/packages/yarnpkg-cli/bin/yarn.js` (the same URL `yarn set version` uses) and installs that file into every bumped `.yarn/releases` directory. GitHub PRs and GitLab MRs commit `yarn-<to>.cjs` (mode `100755`) plus the removed older binary. If the download fails, GitLab falls back to copying a binary produced by a GitHub bump.

## Default path: yarn-bump.sh

```bash
SKILL=<this skill's directory>
"$SKILL/scripts/yarn-bump.sh"                 # resolve latest Yarn 4.x, clone, bump, PR/MR
"$SKILL/scripts/yarn-bump.sh" --to 4.18.1 --dry-run
```

It resolves Yarn 4.x (`@yarnpkg/cli`; never `stable` / 5.x unless `--to`), downloads that CLI once, clones the six repos, skips open `chore/automated-yarn-bump*` PRs/MRs and denylist pins (`4.8.1` / `4.9.2` / `4.15.0`), bumps each tree with `--bin` (so the release binary is in the diff), commits as `rhdh-bot`, and opens PRs/MRs via sibling `/rhdh-pr-mr` (no Jira key for bot bumps).

GitLab weekly-maintenance clones this skill pack and runs `yarn-bump.sh` after digest/bootc and before Quay cleanup.

## Manual mutator (existing checkouts)

```bash
node "$SKILL/scripts/bump-yarn.js" --scan --root /path/to/repo
node "$SKILL/scripts/bump-yarn.js" --to 4.18.1 --from-all --root /path/to/rhdh-plugins
curl -fsSL -o /tmp/yarn-4.18.1.cjs \
  https://repo.yarnpkg.com/4.18.1/packages/yarnpkg-cli/bin/yarn.js
node "$SKILL/scripts/bump-yarn.js" --to 4.18.1 --bin /tmp/yarn-4.18.1.cjs \
  --from-all --root /path/to/rhdh-downstream
```

`--from 4.12.0,4.14.1` is the default when `--from-all` is omitted. Lock refresh can exceed **45 minutes**.

## Anti-patterns

- Do not re-enable Renovate Yarn bumps; they miss Containerfile / `ENV YARN=`.
- Do not `yarn set version stable` — repos must share one exact 4.x.
- Do not download a separate Yarn binary per repo. One fetch from `repo.yarnpkg.com`, then `--bin` copies those bytes into every PR/MR. `--copy-bin` is only the fallback when that fetch fails.
- Do not special-case `rhdh-1-rhel-9`; both CEE repos default to `main`.

## Tests

```bash
node --test "$SKILL/tests/bump-yarn.test.mjs"
bash -n "$SKILL/scripts/yarn-bump.sh"
```

## Completion

Done when matching workspaces sit on `--to` (`packageManager`, `yarnPath`, `yarn-<to>.cjs` mode `100755`), extras rewritten, locks refreshed unless `--no-refresh-locks`, and PRs/MRs opened (or skipped for open bot PR / no diff).
