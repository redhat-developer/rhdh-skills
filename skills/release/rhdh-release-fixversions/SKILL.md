---
name: rhdh-release-fixversions
description: >-
  Lists and synchronizes Jira fix versions across RHIDP, RHDHPLAN, and RHDHBUGS
  using the invoker's local Jira credentials — create missing versions, align
  dates and released or archived flags, and delete or archive orphans when
  explicitly requested. Use for "sync fix versions", "create fix version 1.11.0
  in all projects", "list fix versions", "fix version drift", "align Jira
  versions for the release", or preparing version fields before a release
  starts. Release-manager scope only — requires Administer Projects on all three
  keys; ordinary Jira issue work is a different skill.
compatibility: >-
  Python 3.9+ and uv; Jira REST via the invoker's API token (JIRA_API_TOKEN,
  JIRA_EMAIL, or .jira-token next to acli). Staging: --staging with
  JIRA_STAGING_URL (same JIRA_API_TOKEN as production; JIRA_USE_STAGING=true).
  Administer Projects on RHIDP, RHDHPLAN, and RHDHBUGS.
---

# RHDH release fix versions

Keep the same fix-version names and metadata on RHIDP, RHDHPLAN, and RHDHBUGS.
Most engineers never need this; release managers use it when spinning up or
closing a release stream.

This skill is self-contained: its CLI lives here only. Other release skills do
not embed these commands.

Run every command from **this skill's directory** (the folder that contains
`SKILL.md`), not the rhdh-skills repository root:

```bash
cd skills/release/rhdh-release-fixversions   # in a checkout
# or cd to the installed rhdh-release-fixversions skill folder
uv run scripts/fixversions.py check --json
```

## Route

Load `workflows/sync-fixversions.md`. Load `references/version-fields.md` when
metadata disagrees and you need field semantics or the canonical-source rule.
Load `references/staging-jira.md` when the human wants staging credentials or
`--staging` on the CLI.

| Intent | CLI |
|---|---|
| Verify auth and project access | `uv run scripts/fixversions.py check --json` |
| Try staging before production | add `--staging` to any command (including `apply`) |
| List unreleased versions (default) | `uv run scripts/fixversions.py list --json` |
| Lifecycle for one version across projects | `uv run scripts/fixversions.py status VERSION --json` |
| Before closing the release Feature | `uv run scripts/fixversions.py close-check VERSION --json` |
| Drift among unreleased versions (default) | `uv run scripts/fixversions.py diff --json` |
| Include recently released GA (365d window) | add `--include-released` to `list`, `diff`, or `plan` |
| Full historical inventory | add `--all-versions` to `list`, `diff`, or `plan` |
| Plan creates and updates for unreleased | `uv run scripts/fixversions.py plan --json` |
| Plan specific versions (with optional date overrides) | `uv run scripts/fixversions.py plan --names 1.10.6,2.2.0 --release-date 2027-03-10 --json` |
| Ensure one version everywhere | `uv run scripts/fixversions.py ensure VERSION --json` |
| Apply an approved plan | `uv run scripts/fixversions.py apply --plan FILE --json` |

`list`, `diff`, and bulk `plan` default to **unreleased** versions — the set the
team maintains day to day (create missing peers, fix drift, mark released). Pass
`--include-released` for the recent GA window, or `--all-versions` for history.
Named commands (`status`, `ensure`, `close-check`, `plan --name` / `--names`)
always target the version(s) you name.

`check` verifies **Administer Projects** on RHIDP, RHDHPLAN, and RHDHBUGS (not
only browse). Projects that can be listed but not written report
`status: read_only` with `can_write: false` on the payload — stop and fix
credentials before `apply`. `ensure` is a read-only plan alias for one version;
only `apply` mutates Jira.

## Prerequisites

Run `check` before any write. It never prints credentials. When auth is missing,
stop and tell the human to run `/setup-rhdh-skills jira`. When `can_write` is
false or a project reports missing Administer Projects, stop — browse-only
access is not enough for create/update.

Pass **`--staging`** on any subcommand to target staging Jira instead of
production (`deployment` in `check` JSON is `staging`). Set **`JIRA_STAGING_URL`**
to the staging site; reuse production `JIRA_EMAIL` and `JIRA_API_TOKEN`. Optional
`JIRA_STAGING_EMAIL` or `JIRA_STAGING_TOKEN` when staging differs. Set
`JIRA_USE_STAGING=true` to avoid passing `--staging` on every command.

`acli` cannot create or delete fix versions. This skill uses Jira REST with the
invoker's token at run time. Credentials stay in the environment or token file —
never in the conversation, a plan preview, or a committed file.

## Every mutation is an external write

Invoke `/mutation-gate` and follow it. Build the plan first with `plan` or
`ensure`. Before creating fix versions, `plan` and `ensure` read the RHDHPLAN
release Feature for that version and copy GA Announce / Feature Freeze dates into
empty `releaseDate` and `startDate` fields. Present the operations table
(including any `date_sources`), then run `apply` only after approval.

Deleting a version that still has issues requires `--move-issues-to VERSION` on
`apply`. Prefer archiving via `ensure --archived` over delete when issues remain.

Before transitioning the RHDHPLAN release Feature to **Closed**, run
`close-check VERSION`. Every in-scope project must have the fix version marked
**released** (`--released` on `ensure`, then `plan`/`apply` through
`/mutation-gate`). Do not close the release Feature while fix versions are still
unreleased.

For **z-stream** closes (for example `1.9.8`), `close-check` also looks up RHDH
y-stream lifecycle (for example `1.9` via the Product Life Cycles API). When
support continues and the next patch (`1.9.9`) is missing a fix version or
release Feature, the JSON sets `prompt_user: true` with `prompt_message` and
`suggested_actions`. **Ask the human** whether to create them now — fix
versions should exist ASAP so engineering can assign issues. Use `ensure` for
fix versions; invoke `/rhdh-jira-create` for the RHDHPLAN release Feature
(`component = Release`, summary `RHDH VERSION Release`). Cross-check lifecycle
with `/rhdh-platform-lifecycle` when the API lookup fails or is ambiguous.

## Boundary with the neighbouring skills

- ADF milestone date extraction uses the shared `adf_milestones` module from
  `rhdh-jira-api` (requiresSkills dependency). The release Feature lookup and
  status helpers are local to this skill because they use the REST client, not
  `acli`. Milestone dates for a version also come from `/rhdh-release-schedule`
  when the human asks for the calendar rather than fix-version CRUD.
- Open-issue counts per fix version are read through `/rhdh-release-status`.
- Setting fix version on issues is issue update work; automation rules are in the
  Jira API reference skill.
- Version CRUD uses the Jira REST API directly because `acli` has no version
  subcommand. Auth follows the exception documented in `rest-api-fallback.md`.
- In-scope projects are defined in `rhdh-jira-projects.md` under `rhdh-context`.
  RHDHSUPP is excluded from fix-version sync — only RHIDP, RHDHPLAN, and
  RHDHBUGS stay in sync.

## Completion

Complete when every project named in the answer was read after the change (or
after a read-only list, status, or diff), the CLI subcommand is cited, and each
approved operation has a reported outcome. For every version discussed, report
each in-scope project's lifecycle (`unreleased`, `released`, or `archived`), not
merely whether the name exists. A drift report names the canonical source
project per version (RHIDP, else RHDHPLAN, else RHDHBUGS). A version the user
named that appears in no project is reported absent unless `ensure` created it.
Partial apply is a partial result, not success.
