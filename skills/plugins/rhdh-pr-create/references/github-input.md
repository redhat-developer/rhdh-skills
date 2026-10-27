# GitHub input and handoff

Resolve GitHub issue input by composing with `/rhdh-forge`. This skill does not
parse issue URLs, call `gh issue view`, or hold its own copy of the `gh` error
table.

## Read handoff

Invoke `/rhdh-forge` with the raw reference — a URL, a bare `#number`, or
`owner/repo#number` — and consume the issue detail it returns. Take `key`,
`summary`, `source`, `url`, `repository`, `number`, `labels`, and `state` from
it. Construct `github_issue_url` from the returned `url`; never retain the
user's raw input.

`source` is `github` here and `jira` when the same shape arrives from a Jira
read, so Step 1.5 branches on `source`, not on shape.

If `/rhdh-forge` is unavailable, retain the number and repository, leave the
title unresolved, and report that GitHub enrichment is unavailable and that the
human's next step is `/setup-rhdh-skills install`. Do not fall back to a local
parser or read a credential file.

## Write handoff after PR publication

A comment on the issue or a label change is an external write. State the exact
command, repository, issue number, and body or label, get approval for that
stated set, execute only that set, and report the outcome of every operation in
it. `/rhdh-forge` supplies the payload; it executes nothing.

Failure to update the issue does not invalidate a created PR. Keep the
successful PR result and report the desired issue outcomes for retry.
