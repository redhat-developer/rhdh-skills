# Staging Jira for release-manager CLIs

Use staging to practice list, plan, and apply without touching production.

## Environment

| Variable | Purpose |
|---|---|
| `JIRA_STAGING_URL` | Staging site base URL (**required** with `--staging` or `JIRA_USE_STAGING`) |
| `JIRA_EMAIL` + `JIRA_API_TOKEN` | Same credentials as production (or `email:token` in `.jira-token`) |
| `JIRA_STAGING_EMAIL` | Optional login override when it differs from production |
| `JIRA_STAGING_TOKEN` or `JIRA_STAGING_API_TOKEN` | Optional token override; omit to reuse production token |
| `JIRA_USE_STAGING` | Set to `true` to select staging without `--staging` on every command |

Production URL comes from `JIRA_SERVER` or defaults to `https://redhat.atlassian.net`.
Staging uses **only** `JIRA_STAGING_URL` for the host; the API token is shared unless
you set a staging-specific override.

## CLI

Add **`--staging`** to every subcommand, including **`apply`**, so the plan runs
against the staging site:

```bash
export JIRA_STAGING_URL=https://your-staging.atlassian.net
uv run scripts/fixversions.py check --staging --json
uv run scripts/fixversions.py ensure 99.0.0-test --staging --json
uv run scripts/fixversions.py apply --staging --plan /tmp/plan.json --json
```

`check`, `plan`, `ensure`, and `apply` JSON include `deployment` (`staging` or
`production`) and `server`.
