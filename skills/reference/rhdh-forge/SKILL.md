---
name: rhdh-forge
description: >-
  Reads GitHub and GitLab and constructs unexecuted forge payloads for the other
  RHDH skills: parse an issue, pull request, or merge request reference, fetch
  issue detail, resolve a plugin workspace, inspect checks or pipelines, read
  repository files, or build the exact command for a GitHub pull request,
  GitLab merge request, comment, label, assignee, approval, or /publish write.
  Use for a forge URL, a bare #number, a !number merge request, "which workspace
  is this issue in", a stale statusCheckRollup, "why did that check fail", or
  safe gh, glab, and jq command construction.
compatibility: >-
  GitHub CLI authenticated through gh auth login, plus Python 3. glab is
  optional and needed only for GitLab work, authenticated through
  glab auth login --hostname.
---

# RHDH Forge

One home for reading a forge and constructing its write payloads. Issue parsing,
issue fetch, workspace resolution, check and pipeline reads, repository content
reads, and the `gh` and `glab` behaviours that mislead a caller who has not met
them before all live here. Otherwise, every skill that touches a forge keeps its
own drifting copy.

This skill reads. It never executes a write.

GitHub work runs through `gh`. GitLab work — `rhidp/rhdh` and
`rhidp/rhdh-plugin-catalog` on `gitlab.cee.redhat.com` — runs through `glab`,
which is only needed when a GitLab host is in play.

## Route by outcome

| Outcome | Load and follow |
|---|---|
| Turn a GitHub issue reference into structured context | Run `uv run scripts/fetch_issue_context.py <reference>` |
| Parse a GitHub or GitLab reference without a network call | `references/issue-context.md` |
| Resolve the plugin workspace an issue belongs to | `references/issue-context.md` |
| Read PR state, labels, assignees, files, or check status | `references/gh-cli.md` |
| Explain a failing, stale, or missing check | `references/gh-cli.md` |
| Read a file from a repository or a PR branch | `references/gh-cli.md` |
| Read a GitLab issue, MR state, pipeline status, or file | `references/glab-cli.md` |
| Prepare a GitHub pull-request creation payload | `references/gh-cli.md`, then the caller's mutation gate |
| Prepare a GitLab merge-request creation payload | `references/glab-cli.md`, then the caller's mutation gate |
| Prepare a comment, label, assignee, or `/publish` payload | `references/issue-context.md`, then the caller's mutation gate |
| Prepare a GitLab comment, label, or approval payload | `references/glab-cli.md`, then the caller's mutation gate |

Callers invoke this skill by name and consume what it returns. Do not load its
files from another skill.

## Invariants

- Every route here is read-only. A caller that needs a write gets a payload, not
  an execution.
- Construct an issue, PR, or MR URL from the resolved namespace, repository, and
  number. Never retain the user's raw URL; it may carry a fragment or a query
  string.
- A Jira key is not this skill's work. Extract it, hand it back, and let the
  caller read it with its Jira tool.
- `gh pr checks` and `statusCheckRollup` are cached views and go stale. Confirm
  a check verdict against `gh run list --branch` before acting on it.
- A GitLab pipeline verdict belongs to a commit, not to a merge request. Compare
  the pipeline's SHA against the MR head SHA before reporting it.
- Report an unresolved workspace as unresolved. Guessing one sends a caller into
  the wrong repository.
- Never read a credential file. If `gh auth status` or `glab auth status` fails,
  stop and report the missing capability.

## Mutation boundary

The command patterns in the references are payloads, not authorization. This
skill builds the command and hands it back unexecuted, which is what leaves the
decision with the user rather than with the module that knows the syntax.

Before any pull request, merge request, comment, label, assignee, review,
approval, or `/publish` write, the calling skill invokes `/mutation-gate` and
follows it. This skill returns the exact argument vector and a shell-safe
rendering, the canonical host and repository, the target object or base and head
branches, the title when applicable, and the absolute body-file path. It also
returns the body-file contents for preview and a read-only verification command.
It never runs the write command.

For PR and MR creation, reject a missing or multiline title, a relative or
unreadable body file, an unresolved repository, or an empty base or head branch.
Treat each value as one argument. Do not interpolate a title or body into shell
syntax, use `eval`, or replace the body file with a heredoc.

A request to fetch, triage, or analyze is intent to read. It approves no write.

## Issue context output

`scripts/fetch_issue_context.py` prints one JSON object and nothing else. There
is no envelope: the issue fields are the whole document.

```json
{
  "key": "owner/repo#607",
  "summary": "issue title",
  "source": "github",
  "url": "https://github.com/owner/repo/issues/607",
  "repository": "owner/repo",
  "number": 607,
  "state": "OPEN",
  "labels": [],
  "description": "full issue body",
  "workspace": {"name": null, "strategy": "label"},
  "comments": []
}
```

`key` is `owner/repo#number`, `summary` is the issue title, `state` is `OPEN` or
`CLOSED`, and `workspace.strategy` is one of `label`, `body`, `title`,
`package`, or `unresolved`.

A Jira issue read through the caller's tool fills the same fields with
`source: jira`, and a GitLab
issue read through `references/glab-cli.md` fills the same fields with
`source: gitlab`, so a caller consumes any of the three without branching on
shape.

Keep an unresolved workspace `null` with `strategy: unresolved` rather than
inventing a name.

## Scripts and references

- `scripts/fetch_issue_context.py` deterministically builds that document from a
  GitHub issue URL, a bare `#number`, or `owner/repo#number`. A GitLab issue is
  read with `glab` instead.
- `references/issue-context.md` covers reference parsing for both forges, field
  extraction, workspace resolution, and the gated interaction payloads.
- `references/gh-cli.md` covers `gh` and `jq` read patterns, pull-request
  creation payloads, check and workflow-run reads, repository content reads,
  the failure table, and the overlay repository's `/publish` rules.
- `references/glab-cli.md` covers `glab` reads for merge requests, pipelines,
  and repository content, GitLab merge-request creation payloads, the GitLab
  field names that differ from GitHub's, and the other commands it constructs
  but never runs.

## Completion

A fetch is complete when the JSON carries `key`, `summary`, and `source`, `url`
was rebuilt from the resolved namespace, repository, and number rather than
copied from the request, and `workspace.strategy` names the rule that resolved
it or reads `unresolved` with `name: null`. A check verdict is complete only
once `gh run list --branch` confirmed it on GitHub, or the pipeline for the MR
head SHA confirmed it on GitLab; a `gh pr checks` or `statusCheckRollup` value
alone is a cached view, not a verdict. A write payload is complete when it
is handed back unexecuted for the caller's mutation gate. An interaction payload
states the exact command, repository, issue, PR, or MR number, head SHA, and body
or label. A PR or MR creation payload carries the canonical repository, exact
base and head branches, one-line title, absolute body-file path, body preview,
argument vector, shell-safe command, and read-only verification command. A Jira
key found in the issue is reported to the caller, never resolved here.
