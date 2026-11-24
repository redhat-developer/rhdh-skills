# Workflow: Triage Bot PRs

Batch-triage open Renovate and Dependabot dependency PRs across RHDH
repositories. Produces a decision for every PR and, unless in dry-run mode,
executes approved operations.

## Step 1 — List

Run the fetch script to collect all open bot PRs:

```bash
uv run scripts/list_bot_prs.py
```

The path is relative to the skill directory.

Optional flags:

- `--repo owner/repo` — restrict to one repository
- `--dry-run` — mark the run as dry-run (no mutations will be executed)

Consume the full JSON output. The top-level object contains:

```
dry_run: true | false
prs: [{repo, number, url, title, base_branch, author, labels, is_security,
       ci_status, is_draft, is_conflicted, dep_type, dep_name, semver_level,
       go_directive_bumped, go_toolchain_bumped, go_godebug_changed,
       go_directive_value, go_godebug_value, base_godebug_pin,
       chart_folders, duplicate_of}]
```

`is_security` folds every signal into one boolean — the `kind/security` label, a
`[security]` title marker, or an open Dependabot alert for the bumped package at
or above its first patched version. Do not re-derive it from `labels` and
`title`: GitHub-hosted Dependabot marks nothing in the title of a security
update, so the alert is the only thing that identifies it, and it is not visible
in the JSON. The rules in `references/policy.md` say "security PR" and mean this
field.

The Go fields are populated for a PR classified `go-module` whose base branch
roots a `go.mod` or `go.work` — discovered per repository and branch, so a Go
repository added to the run is covered without editing the script, and a chart or
local-environment PR that merely names a Go module is not. `base_godebug_pin` is
read from the base branch's root `go.mod` only when the PR raises the `go`
directive **and** is a security PR — for any other PR the directive is frozen and
the pin cannot change the decision. A `null` there therefore means "no pin on that
branch", "not a security directive bump", or "a `go.work`-only workspace with no
root `go.mod`". See "Go repo policy" in `references/policy.md`.

## Step 2 — Release state

For each distinct `release-x.y` base branch found in the PR list, invoke
`/rhdh-release-schedule` to determine the latest z-stream release state for
that minor version: Code Freeze (CF), Feature Freeze (FF), GA, or EOL.

Cross-check EOL status: if `/rhdh-release-schedule` does not cover the version,
invoke `/rhdh-platform-lifecycle` to confirm whether that RHDH minor is
end-of-life.

When `/rhdh-release-schedule` returns TBD for all milestones of a z-stream, record
the release state as **unknown**. Do not infer pre-CF or any other state from
the absence of dates.

When the schedule shows GA has passed, verify the tag in **every repo that has
open release-branch PRs** using `git ls-remote --tags <repo-url>`. Tags in
these repos do not carry a `v` prefix. A tag present in one repo but missing in
another means the release is not fully rolled out — only unhold PRs in repos
where the tag exists.

For rhdh-operator, also confirm the `VERSION ?=` line in the `Makefile` on the
release branch shows the **next** z-stream (e.g. `0.10.5` after `1.10.4` is
tagged). If it still shows the just-released version, the branch is not ready
for new merges — keep PRs held.

Record the release state per branch and per repo for use in Step 3.

## Step 3 — Decide

Apply the rules from `references/policy.md` to each PR. For each PR, determine
the decision and reason.

Produce exactly one triage report table in the conversation, sorted by PR number
descending (newest first) so the order matches the GitHub UI. The table has six
columns — keep cell content concise so the table is scannable at a glance:

- **Title**: truncate to the dependency name (e.g. "update golang.org/x/exp
  digest", not the full Renovate title with version tags).
- **Reason**: under ~30 characters (e.g. "CI green", "Go directive frozen",
  "Go bump, pinned").

```
| Repo | PR | Title | Branch | Decision | Reason |
|------|-----|-------|--------|----------|--------|
| rhdh-operator | #42 | update go toolchain | main | approve+merge | CI green, patch bump |
| rhdh-must-gather | #43 | update golang.org/x/net | release-2.1 | flag | godebug rewritten |
| rhdh-chart | #18 | update chart dep X | release-1.10 | hold | CF — hold until 1.10.5 |
| ... | ... | ... | ... | ... | ... |
```

PR numbers link to the GitHub PR URL.

## Step 4 — Dry-run check

If `dry_run` is true in the script output, or the user requested a dry run:

1. Show the triage report table from Step 3.
2. Show the action-count summary:

```
| Action | Count |
|--------|-------|
| approve+merge | 5 |
| hold | 2 |
| close | 1 |
| bump | 1 |
| skip (pending CI) | 3 |
| skip (draft) | 1 |
| flag for human review | 1 |
| unknown (release state TBD) | 0 |
```

3. Stop. Do not invoke `/mutation-gate` or execute any operations.

## Step 4b — Verify CI

Re-check CI status live on every PR whose decision depends on it (approve+merge,
skip-for-CI-failure, or any decision that would change if CI flipped). Run
`gh pr checks` for each and compare against the script snapshot. Update the
decision table for any PR whose CI status has changed before proceeding.

## Step 4c — Verify the Go pin before approving

A security PR that raises the `go` directive on a release branch is mergeable only
because that branch's `godebug` pin holds its runtime semantics at branch cut.
`base_godebug_pin` from Step 1 is a snapshot, so re-read it live for every such PR
whose decision is approve+merge or unhold+approve+merge, immediately before the
mutation gate:

```bash
gh api 'repos/redhat-developer/<repo>/contents/go.mod?ref=<base_branch>' \
  -H 'Accept: application/vnd.github.raw' | grep -E '^godebug '
```

If that prints nothing, or the request fails because the branch has no `go.mod`,
the pin is not in effect: downgrade the decision to **flag**, state that the
branch carries no pin, and do not approve. Merging the PR does not supply the
pin — a release branch inherits it at branch cut, so a branch missing one keeps
the new GODEBUG defaults the bump introduces.

Also confirm the PR's own diff leaves the `godebug` line alone. If it adds,
changes, or removes the line, flag it even when the base branch has a pin: the
branch must not re-pin, and the fix needs the line dropped.

PRs that do not raise the `go` directive skip this step entirely.

## Step 5 — Approve plan

Skipped in dry-run mode.

Always show the triage report table and action-count summary from Step 3 in the
conversation **before** invoking `/mutation-gate`. The user must be able to
review the full decision set before being asked to approve mutations.

Invoke `/mutation-gate` with the full operation list. Each operation states:

- **Target:** repository and PR number
- **Command:** the exact `gh` command to run
- **Preview:** one-line description of the effect
- **Precondition:** CI status, release state, `godebug` pin, or label check that
  must hold
- **Failure recovery:** what to do if the command fails

Every action must include a comment on the PR stating the reason briefly. For
approve+merge, comment the reason before approving. For close, hold, unhold,
and bump, include the reason in the comment body. When the action is a rebase or
recreate, the command belongs to the app that opened the PR — `@renovatebot
rebase` or `@dependabot recreate` — and goes on its own line as the last
instruction line of the comment, after the reason (see "Addressing the bot" in
`references/policy.md`).

Every comment body ends with the fixed italic attribution line from "Attribution
trailer" in `references/policy.md` — `_Assisted by AI, using the rhdh-pr-triage
skill._` — as its last line, after a blank line. The examples below include it.
Do not post a comment without it, whatever the action.

When the decision is "skip" because a release tag is not yet pushed, also
comment `/hold` with the reason if `do-not-merge/hold` is not already on the PR.
If the label is already present, no action is needed.

Example operations:

| Target | Command | Preview | Failure |
|--------|---------|---------|---------|
| rhdh-operator #42 | `gh pr comment 42 --repo redhat-developer/rhdh-operator --body $'Approved by triage: CI green, patch toolchain bump on main.\n\n_Assisted by AI, using the rhdh-pr-triage skill._'` | Comment reason | Skip, report |
| rhdh-operator #42 | `gh pr review 42 --repo redhat-developer/rhdh-operator --approve` | Approve | Skip, report |
| rhdh-operator #42 | `gh pr merge 42 --repo redhat-developer/rhdh-operator --squash` | Squash-merge | Skip, report |
| rhdh-operator #43 | `gh pr comment 43 --repo redhat-developer/rhdh-operator --body $'go.mod conflicts after #42 merged; approved, will merge once CI is green.\n\n@renovatebot rebase\n\n_Assisted by AI, using the rhdh-pr-triage skill._'` | Request rebase from the PR's own bot | Skip, report |
| rhdh-chart #18 | `gh pr comment 18 --repo redhat-developer/rhdh-chart --body $'/hold until 1.10.5 is out — code freeze active.\n\n_Assisted by AI, using the rhdh-pr-triage skill._'` | Hold for pending release | Skip, report |
| rhdh-operator #99 | `gh pr close 99 --repo redhat-developer/rhdh-operator --comment $'Closing — RHDH 1.8 is end of life.\n\n_Assisted by AI, using the rhdh-pr-triage skill._'` | Close EOL PR | Skip, report |
| rhdh-operator #50 | `gh pr comment 50 --repo redhat-developer/rhdh-operator --body $'/hold — still waiting on 1.10.4 tag.\n\n_Assisted by AI, using the rhdh-pr-triage skill._'` | Hold PR pending tag | Skip, report |

## Step 6 — Execute

Skipped in dry-run mode.

Run each approved operation via `gh`. Report outcome per operation, including
operations that were skipped or denied in the gate.

## Step 7 — Summary

Print the triage report table from Step 3 (with outcomes updated to reflect what
actually happened), followed by the action-count summary table:

```
| Action | Count |
|--------|-------|
| approved+merged | 5 |
| held | 2 |
| unheld+merged | 0 |
| closed | 1 |
| bumped | 1 |
| skipped (pending CI) | 3 |
| skipped (draft) | 1 |
| flagged for human review | 1 |
| unknown (release state TBD) | 0 |
```
