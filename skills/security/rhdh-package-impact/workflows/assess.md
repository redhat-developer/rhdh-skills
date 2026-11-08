# Assess Dependabot package impact

Read-only. No mutation gate.

## Steps

1. Resolve `--repo-root` (or `RHDH_PLUGINS_ROOT`) and the workspace name. See
   [repo-layouts.md](../references/repo-layouts.md).
2. Ensure `GH_TOKEN` or `GITHUB_TOKEN` is set for Dependabot REST.
3. Discover packages (unless the caller already supplied a list):

```bash
node "$SKILL_DIR/scripts/list-dependabot-packages.js" <workspace> --json
```

4. Prefer patch-status (classification + dismiss hints) for the whole workspace:

```bash
node "$SKILL_DIR/scripts/check-dependabot-patch-status.js" \
  --repo-root "$REPO" <workspace>
# or --json for agents / fullsend
```

5. For a named package list only:

```bash
node "$SKILL_DIR/scripts/classify-cve-source.js" --repo-root "$REPO" \
  <workspace> pkg1 pkg2 --json
```

6. Report a markdown table to humans (script default) or the `--json` payload to
   agents. Read [classifications.md](../references/classifications.md) when a
   verdict is unfamiliar.

7. Recommend next step: bump (`workflows/bump-workspace.md`) or dismiss
   (`workflows/dismiss-alerts.md`) — do not execute writes here.
