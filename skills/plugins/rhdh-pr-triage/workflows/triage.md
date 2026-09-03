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
prs: [{repo, number, url, title, base_branch, author, labels, ci_status,
       is_draft, is_conflicted, dep_type, dep_name, semver_level,
       go_directive_bumped, go_toolchain_bumped, chart_folders,
       duplicate_of}]
```

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

Produce a plan table in the conversation, sorted by PR number descending (newest
first) so the order matches the GitHub UI:

```
| Repo | PR | Title | Branch | Type | CI | Decision | Reason |
|------|-----|-------|--------|------|----|----------|--------|
| rhdh-operator | #42 | update go toolchain to 1.23.5 | main | go-toolchain | pass | approve+merge | CI green, patch bump |
| rhdh-chart | #18 | update chart dep X to 2.1.0 | release-1.10 | chart-dep | pass | hold | CF — hold until 1.10.5 |
| ... | ... | ... | ... | ... | ... | ... | ... |
```

## Step 4 — Dry-run check

If `dry_run` is true in the script output, or the user requested a dry run:

1. Show the plan table from Step 3.
2. Show a summary of planned actions:

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

## Step 5 — Approve plan

Skipped in dry-run mode.

Invoke `/mutation-gate` with the full operation list. Each operation states:

- **Target:** repository and PR number
- **Command:** the exact `gh` command to run
- **Preview:** one-line description of the effect
- **Precondition:** CI status, release state, or label check that must hold
- **Failure recovery:** what to do if the command fails

Every action must include a comment on the PR stating the reason briefly. For
approve+merge, comment the reason before approving. For close, hold, unhold,
and bump, include the reason in the comment body.

When the decision is "skip" because a release tag is not yet pushed, also
comment `/hold` with the reason if `do-not-merge/hold` is not already on the PR.
If the label is already present, no action is needed.

Example operations:

| Target | Command | Preview | Failure |
|--------|---------|---------|---------|
| rhdh-operator #42 | `gh pr comment 42 --repo redhat-developer/rhdh-operator --body "Approved by triage: CI green, patch toolchain bump on main."` | Comment reason | Skip, report |
| rhdh-operator #42 | `gh pr review 42 --repo redhat-developer/rhdh-operator --approve` | Approve | Skip, report |
| rhdh-operator #42 | `gh pr merge 42 --repo redhat-developer/rhdh-operator --squash` | Squash-merge | Skip, report |
| rhdh-chart #18 | `gh pr comment 18 --repo redhat-developer/rhdh-chart --body "/hold until 1.10.5 is out — code freeze active."` | Hold for pending release | Skip, report |
| rhdh-operator #99 | `gh pr close 99 --repo redhat-developer/rhdh-operator --comment "Closing — RHDH 1.8 is end of life."` | Close EOL PR | Skip, report |
| rhdh-operator #50 | `gh pr comment 50 --repo redhat-developer/rhdh-operator --body "/hold — still waiting on 1.10.4 tag."` | Hold PR pending tag | Skip, report |

## Step 6 — Execute

Skipped in dry-run mode.

Run each approved operation via `gh`. Report outcome per operation, including
operations that were skipped or denied in the gate.

## Step 7 — Summary

Print a summary table:

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
