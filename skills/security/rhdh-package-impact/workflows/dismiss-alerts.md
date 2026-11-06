# Dismiss Dependabot alerts

External write. Load [dismissal-policy.md](../references/dismissal-policy.md),
state the exact close commands through `/mutation-gate`, then run.

## Dry run first

```bash
node "$SKILL_DIR/scripts/close-dependabot-alerts.js" <workspace> <package> --json
```

## Package-level (exact RUNNER / PLUGIN_DEV / WORKSPACE_DEV)

Humans — interactive confirm (omit `--yes`):

```bash
node "$SKILL_DIR/scripts/close-dependabot-alerts.js" <workspace> <package> \
  --close --reason not_used \
  --comment "runner-only in <workspace>; classification=RUNNER"
```

After an approved gate plan (fullsend): same command with `--yes`.

## Alert-level (PATCHED_EXCEPT_RUNNER)

Pass the **exact runner manifest**, not the workspace yarn.lock:

```bash
node "$SKILL_DIR/scripts/close-dependabot-alerts.js" \
  workspaces/<workspace>/packages/backend/package.json <package> \
  --close --reason not_used \
  --comment "prod patched; runner alert only; classification=…"
```

Never dismiss `plugins/…` alerts when doing alert-level dismiss of a mixed
package.
