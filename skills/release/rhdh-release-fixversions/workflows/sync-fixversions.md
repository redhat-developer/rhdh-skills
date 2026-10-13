# Sync fix versions across RHIDP, RHDHPLAN, and RHDHBUGS

Run commands from the directory that contains this skill's `SKILL.md` — in a
checkout that is `skills/release/rhdh-release-fixversions`, not the repository
root. There is no `scripts/fixversions.py` at the monorepo root.

```bash
cd skills/release/rhdh-release-fixversions
```

Prefer `--json` on every command (output is JSON either way; the flag matches
`release.py` usage).

To try against **staging** first, export `JIRA_STAGING_URL` (same API token as
production), then add `--staging` to each command (including `apply`).
`check` JSON includes `deployment`: `staging`.

## 1. Capability check

```bash
uv run scripts/fixversions.py check --json
```

Stop when `ok` is false. Report `error` and point to `/setup-rhdh-skills jira`.

## 2. Read-only inspection

```bash
uv run scripts/fixversions.py list --json
uv run scripts/fixversions.py list --json --include-released
uv run scripts/fixversions.py status 1.11.0 --json
uv run scripts/fixversions.py close-check 1.11.0 --json
uv run scripts/fixversions.py diff --json
uv run scripts/fixversions.py diff --json --prune
```

`list`, `diff`, and bulk `plan` default to **unreleased** versions only — create
missing peers, fix metadata drift, and mark released. Pass `--include-released`
for the recent GA window (365 days), or `--all-versions` for the full inventory.
`--lifecycle released` / `archived` on `list` also widens past unreleased-only.

Present a table: version name, each project's lifecycle (`unreleased`,
`released`, `archived`), sync state (`ok`, `drift`, `missing`), and canonical
source. On `drift`, read `changed_fields` plus `from` / `to` (includes
`startDate`, `releaseDate`, and `description`). Use `status VERSION` when the
user names one release (no date window).
Prefer discovery as `list` → `diff` → focused `plan --names …` rather than a
wide historical `plan --include-released`.

Run `check` before planning writes. When `can_write` is false, projects show
`status: read_only` (list still works) — stop until Administer Projects is
available. `status: fail` means the project list itself failed.

When the user is **closing out** a release Feature, run `close-check VERSION`
first. It looks up the RHDHPLAN release Feature and confirms RHIDP, RHDHPLAN,
and RHDHBUGS all have the fix version in the **released** lifecycle. When
`ok` is false, report `blockers` and the `suggested_command` (`ensure` with
`--released`, then plan/apply). Do not close the release Feature until
`ready_to_close_release_feature` is true.

### Z-stream close-out: create the next patch early

When closing a **z-stream** GA (for example `1.9.8`), read `next_z_stream` in
the `close-check` JSON:

| Field | Meaning |
|---|---|
| `stream_support.supported` | RHDH y-stream (for example `1.9`) still vendor-supported |
| `next_version` | Next patch (for example `1.9.9`) |
| `needs_fix_version` | Fix version missing in one or more projects |
| `needs_release_feature` | No RHDHPLAN release Feature for the next patch |
| `prompt_user` | Ask the human to create missing artifacts now |

When `prompt_user` is true, present `prompt_message` and wait for approval
before creating anything. Prioritize the **fix version** (`ensure NEXT --json`,
then `/mutation-gate` and `apply`) so engineering can assign issues immediately.
Create the **release Feature** through `/rhdh-jira-create` when the human
agrees. Skip this block with `--skip-next-stream` when the user only wants the
released-state gate.

## 3. Plan mutations

```bash
uv run scripts/fixversions.py plan --json
uv run scripts/fixversions.py plan --json --prune
uv run scripts/fixversions.py plan --json --names 1.10.6,2.2.0 --release-date 2027-03-10
uv run scripts/fixversions.py ensure 1.11.0 --json
uv run scripts/fixversions.py ensure 1.11.0 --json --release-date 2026-03-15
```

Optional flags on `plan` and `ensure`: `--description`, `--start-date`,
`--release-date`, `--released`, `--archived`, `--no-release-doc`.
`plan --names a,b,c` limits the plan to those versions and applies any
override flags to all of them. `ensure` is the same as `plan --name` for one
version — both are read-only.

Plan JSON includes `summary` (create/update/delete counts) and `decisions`
(orphan create-peers vs delete). Confirm orphan decisions before apply.
Default orphan handling creates missing peers; `--prune` deletes the lone copy
instead.

`plan` and `ensure` automatically read milestone dates from the RHDHPLAN release
Feature description (GA Announce → `releaseDate`, Feature Freeze → `startDate`
when still empty) **only for versions whose canonical dates are still empty**.
The plan JSON lists `release_docs` under `filter` and `date_sources` on each
operation when dates were filled from that issue.

Pass the plan through `/mutation-gate`. Scan the plan JSON with the gate's
credential scanner before showing it.

## 4. Apply

After approval, write the plan to a temp file (never the user's checkout):

```bash
uv run scripts/fixversions.py apply --plan /tmp/fixversions-plan.json --json
uv run scripts/fixversions.py apply --plan /tmp/fixversions-plan.json --json \
  --move-issues-to 1.10.0
```

`apply` re-checks Administer Projects before the first mutation. When `can_write`
is false, every operation is reported `skipped` and nothing is written. After a
permission failure mid-batch, remaining operations are skipped.

## 5. Verify

```bash
uv run scripts/fixversions.py diff --json
```

Report each apply outcome. Remaining drift is incomplete work.

## Handoffs

| Request | Invoke by name |
|---|---|
| When is Code Freeze? | `/rhdh-release-schedule` |
| How many open issues on fix version 1.11? | `/rhdh-release-status` |
| Set fix version on an issue key | `/rhdh-jira-update` |
