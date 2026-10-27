---
name: rhdh-pr-create
description: >-
  Publishes verified changes from rhdh-plugins or community-plugins: detect the
  repository and affected workspaces, run the repository build pipeline,
  create package changesets, stage generated files safely, create a signed-off
  commit and branch, push, open a GitHub pull request, upload optional bug-fix
  recordings, and link Jira or GitHub issues. Use for raise PR, create or open
  a plugin PR, push verified plugin changes, or publish a verified change
  another skill handed off.
compatibility: "Git, GitHub CLI, Yarn, and a rhdh-plugins or community-plugins checkout."
---

# RHDH Pull Request

Own publication after implementation is verified. Accept either the current
staged checkout or a change handoff from the calling skill; do not diagnose or
modify product code.

## Start here

1. Load `references/repo-profiles.md` and identify the canonical upstream from
   all remotes.
2. Run `gh auth status` and inspect branch, status, staged diff, and upstream
   default branch.
3. If the calling skill supplied a change handoff, validate its repository and
   file list, issue reference, recordings, and verification evidence against the
   checkout. Treat the checkout as authoritative and report mismatches.
4. Follow `workflows/create-pull-request.md` sequentially. There is no
   auto-approve mode: every external write is stated in full and approved as
   that stated set before it runs.

## Boundaries

- This skill stages, formats, validates, creates changesets, commits, pushes,
  opens the PR, uploads supplied recordings, and updates linked GitHub issues.
  Jira writes belong to `/rhdh-jira-update`; field and JQL context is
  `/rhdh-jira-context`.
  Invoke either by name and consume what it reports; never call Jira directly
  from here.
- GitHub issue reads belong to `/rhdh-forge`, which returns the same issue
  detail with `source: github`. Load `references/github-input.md` when the
  request supplies an issue URL or number.
- It does not implement fixes or features. If validation exposes a product-code
  failure, stop and hand the failure back to the skill that produced the change,
  usually `/rhdh-plugin-bug-fix`, with the failing command and its output.
- Pre-existing dirty or untracked files are outside the publication set unless
  the user explicitly identifies them as part of the change.
- Only published plugin source paths need changesets; private `packages/*`, dev
  apps, tests, fixtures, and stories do not.
- Never fabricate issue data, recording URLs, CI results, or reviewer evidence.

## Change handoff

A skill that produced a verified change may hand it off instead of leaving it
staged; `/rhdh-plugin-bug-fix` is the usual producer. The handoff arrives in the
conversation and names the change summary, the file list making up the change,
the issue reference, the optional before and after recordings, and the
verification that was run with its result.

The file list is the change set. The producing skill does not stage, so those
paths arrive unstaged or untracked: verify them against the working tree, keep
them out of the pre-existing baseline, and stage exactly them alongside the
build-generated files at the workflow's staging gate. An empty index is a stop
condition only when no handoff was supplied.

When no handoff is supplied, derive these fields from the staged diff and ask
only for unresolved issue context or release intent.

## External writes

Read-only inspection, builds, and draft construction do not approve a write. A
push, recording upload, PR creation, or GitHub issue update is an external
write: invoke the named skill `mutation-gate` and follow it rather than
restating the gate here.

State every write this skill owns with its exact target, exact command, and a
preview of the change — the `git push`, the GitHub Contents upload, the
pull-request creation, the GitHub issue comment — get approval for that stated
set, execute only that set, and then report the outcome of every operation,
including the ones that were skipped. Stage exactly the approved paths, taken
from the handoff's file list when a handoff supplied them. If an earlier
operation produces material a later one needs, such as an uploaded recording URL
used in the PR body, report the outcomes of the first set, then state and get
approval for the next one. Reject legacy `--a` as unsupported. Each reported
outcome also names the changed resource or URL, its verification, and any
remaining recovery action.

## Completion

Report the PR URL, the repository, the head branch and commit SHA, the generated
changesets, the uploaded recording URLs when recordings were supplied, every
issue update, and the outcome of every external write. Take exact URLs and SHAs
from command output rather than reconstructing them. A created PR is not
complete until its URL is captured and the requested upload gates have either
succeeded or been reported for manual action. If an external update fails, keep
the successful PR result and report the failed update rather than hiding it.
