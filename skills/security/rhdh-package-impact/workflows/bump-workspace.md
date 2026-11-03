# Bump workspace Dependabot packages

Local lockfile / `package.json` edits and PR open are external writes. State
them through `/mutation-gate` before anything that is not `--dry-run`.

## Fullsend / agent default

One orchestrator (prepare → bump → PR tables):

```bash
node "$SKILL_DIR/scripts/workspace-cve-bump.js" \
  --repo-root "$REPO" --workspace <workspace> --json --dry-run

# After gate approval (mutates the checkout; does not push/open PR):
node "$SKILL_DIR/scripts/workspace-cve-bump.js" \
  --repo-root "$REPO" --workspace <workspace> --json
```

Exit codes: `0` ok / fully fixed, `2` partial leftovers or needs human,
`1` hard error. JSON includes `prTitle`, `prBody`, bump rows, and `next`.

Then commit on the prepared branch and open via `/rhdh-pr-mr` (requires
`--issue` and `--attribution`). Use `prTitle` / `prBody` from the JSON — do not
hand-write CVE tables.

## Manual steps (same scripts)

1. `prepare-workspace-bump.js` — fetch upstream base, `checkout -B
   chore/<workspace>-cve-bumps`.
2. `bump-workspace-packages.js` — `yarn up -R`, install, dedupe, classify,
   CVE summary. Skips `@backstage/*` / `@backstage-community/*`. Allowlisted
   leftovers (`qs`) auto ancestor-bump. Known no-major-jump packages
   (`http-proxy-middleware`) re-pin if they jumped majors. `react-router` /
   `react-router-dom` co-bump.
3. Pipe bump `--json` into `format-bump-pr.js` for Fully fixed / Partial /
   Unchanged tables.
4. Do **not** run `bump-package-ancestors.js` for non-allowlisted packages
   unless the user explicitly asks.
5. Complex dual-major cases (e.g. `fast-xml-parser`): manual only.

## After bump

Re-run `check-dependabot-patch-status.js` if dismiss is next. Prefer SBOM bumps
for exact `PLUGIN_DEV` / `WORKSPACE_DEV` even when dismissable.
