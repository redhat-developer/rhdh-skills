# Bump workspace Dependabot packages

Local lockfile / `package.json` edits and PR open are external writes. State
them through `/mutation-gate` before anything that is not `--dry-run`.

## Fullsend / agent default

One orchestrator (prepare → bump → PR tables):

```bash
node "$SKILL_DIR/scripts/workspace-cve-bump.js" \
  --repo-root "$REPO" --workspace <workspace> \
  --alerts-json "$FULLSEND_OUTPUT_DIR/dependabot-alerts.json" --json --dry-run

# After gate approval (mutates the checkout; does not push/open PR):
node "$SKILL_DIR/scripts/workspace-cve-bump.js" \
  --repo-root "$REPO" --workspace <workspace> \
  --alerts-json "$FULLSEND_OUTPUT_DIR/dependabot-alerts.json" --json
```

Fullsend notes:

- Pass `--alerts-json` (staged snapshot). Do not REST-fetch alerts in the sandbox.
- `prepare-workspace-bump.js` auto `--verify-only` when `FULLSEND_OUTPUT_DIR` is set.
- Plugins-monorepo CVE schedule: omit `--base` (defaults / stays on `main`).
- rhdh-core release schedule only: pass `--base release-1.10` or set
  `CVE_BASE_BRANCH=release-1.10` (read when `--base` is omitted) from
  that repo’s workflow — not from rhdh-plugins.
- Never call `close-dependabot-alerts.js` under Fullsend.

Exit codes: `0` ok / fully fixed, `2` partial leftovers or needs human
(including release-1.10 dual-lockfile leftovers/errors), `1` hard error.
JSON includes `prTitle`, `prBody`, bump rows, optional `dualLockfile`, and
`next`.

Then commit on the prepared branch and open via `/rhdh-pr-mr` (requires
`--issue` and `--attribution`). Use `prTitle` / `prBody` from the JSON — do not
hand-write CVE tables.

## Manual steps (same scripts)

1. `prepare-workspace-bump.js` — fetch upstream base, `checkout -B
   chore/<workspace>-cve-bumps` (or `…-release-X.Y` when `--base release-X.Y`).
   Prefer a worktree for release trains.
2. `bump-workspace-packages.js` — `yarn up -R`, install, then dedupe on
   plugins monorepos only (rhdh-core skips dedupe unless `--dedupe`),
   classify, CVE summary. Skips `@backstage/*` / `@backstage-community/*`.
   Allowlisted leftovers (`qs`) auto ancestor-bump. Known no-major-jump
   packages (`http-proxy-middleware`) re-pin if they jumped majors.
   `react-router` / `react-router-dom` co-bump.
   **release-1.10 only:** product / main Dependabot alerts are assumed to
   also apply to wrapped plugins under `dynamic-plugins/` (gap-closer);
   same list drives sibling `yarn up -R` when still vulnerable (see
   `release-1.10-dual-lockfile.js`; REMOVE WHEN EOL).
3. Pipe bump `--json` into `format-bump-pr.js` (`--base release-X.Y` for
   `[release-X.Y] fix(deps): …` titles) for Fully fixed / Partial /
   Unchanged tables.
4. Do **not** run `bump-package-ancestors.js` for non-allowlisted packages
   unless the user explicitly asks.
5. Complex dual-major cases (e.g. `fast-xml-parser`): manual only.
6. Lockfile-only refresh after tip moved: reset to tip + re-bump, not
   conflicted `git rebase` on `yarn.lock`.

## After bump

Re-run `check-dependabot-patch-status.js` if dismiss is next. Prefer SBOM bumps
for exact `PLUGIN_DEV` / `WORKSPACE_DEV` even when dismissable.
