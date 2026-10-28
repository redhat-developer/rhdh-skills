---
name: rhdh-jira-link
description: >-
  Ties a GitHub pull request or GitLab merge request to an RHDH Jira issue in
  RHIDP, RHDHPLAN, RHDHBUGS, or RHDHSUPP: attach the Jira Web link titled
  `repo #N: <title>`, post or update the structured comment, fill empty issue
  fields, move an RHDHPLAN Epic, Story, or Task to RHIDP, and mark a Web link
  merged or closed. Raises the PR or MR first when one does not exist yet. Use
  for "link this PR to RHIDP-1234", "attach the MR to the Jira issue", "mark the
  Web links merged", "mark closed PRs", replacing a hand-rolled remotelink or
  comment step, or a PR outside the rhdh-plugins and community-plugins monorepo
  flow. The full monorepo flow — build, changeset, recordings — is rhdh-pr-create.
compatibility: "Access to raise a PR or MR on the target GitHub or GitLab repository; write access to RHDH Jira (RHIDP, RHDHPLAN, RHDHBUGS, RHDHSUPP) for web links, comments, field edits, and project moves. Windows, macOS, Linux."
local-tooling: "Optional: a Jira session — acli, an Atlassian MCP server, or another tool; a forge CLI (gh, glab) to raise the PR/MR. The bundled executor authenticates from the environment (JIRA_API_TOKEN or the .jira-token file)."
---

# Jira PR / MR links

The protocol for tying a GitHub pull request or GitLab merge request to an RHDH
Jira issue: raise the PR/MR when one does not exist, attach the Jira remote Web
link, post or update the structured comment, optionally fill empty issue
fields, and mark Web links merged or closed later. Field and payload
context is `/rhdh-jira-context`.

## Raise the PR/MR first

When no PR/MR exists yet, the order is: commit on a feature branch, push, then
create the PR/MR, then link. The push must happen before the create; the Jira
link happens after and must not fail silently — missing Jira authentication is
an error in the link step, not a reason to skip it.

Compose the reviewer-facing PR or MR title and body, then invoke
`/prose-editing` once on both in the **flavored** register. Preserve Jira keys,
closing syntax, headings, checklists, links, and the required `Generated-by`
line. The transport that posts them must not edit them further. The structured
Jira link comment created later is a protocol payload and does not receive this
prose pass.

The body carries the Jira browse URL (`Ref: https://…/browse/KEY`) and a
`Generated-by:` line when missing. Skip the `Ref:` line for
`community-plugins` remotes so that repo stays free of Jira browse URLs in git
history and PR text.

## The link step

Given an existing PR/MR URL and the Jira key:

1. Attach the Jira remote Web link titled `repo #N: <title>` — short repo
   name, PR/MR number, full title. A second link with the same URL replaces
   the first rather than duplicating it.
2. Post the structured comment; if a comment already mentions the PR/MR URL,
   update it in place instead of posting a new one (comments are paginated —
   check before claiming absence).
3. Optionally fill empty issue fields (see Defaults below).

Comment shape (only **newly set** fields; omit `kept` values):

```
PR: https://github.com/org/repo/pull/123
```

or, for GitLab:

```
MR: https://gitlab.cee.redhat.com/group/repo/-/merge_requests/817
```

Then, when any defaults were newly set:

```
Adjusted fields:
* Priority: Normal
* Status: In Progress
```

## RHDHPLAN → RHIDP auto-move

If the linked issue is an **Epic**, **Story**, or **Task** in **RHDHPLAN**,
the link step moves it to **RHIDP** (same issue type) via the Jira bulk-move
API, then continues Web link / defaults / comment on the **new** key. Features
and other RHDHPLAN types are left alone. Report the post-move key — the caller
must use it, not the original one.

## Defaults the link step applies (only if empty)

When defaults are enabled, empty fields are filled: assignee, team, board,
story points, priority, and status. Status becomes **In Progress** unless the
issue is already In Progress / Review / Closed. There are no built-in
team/assignee values — the values come from configuration the operator sets.
Team and sprint can be skipped together while the other defaults still apply.
Missing values are an error only when applying defaults; the Web link and
comment still succeed with defaults disabled.

## Mark merged / closed

Given an issue key, check each of its Web links against the forge — the agent
checks PR/MR state itself; no script does. Prefix the titles with
`[x] merged:` when the PR/MR is merged, or `[!] closed:` when it is closed
without merging. Do not re-apply defaults or comment. Report each title
**and** its PR/MR URL; open PRs/MRs stay unprefixed. A failed status check
leaves the link unprefixed — never treat a failed check as closed.

Title formats:

```
<repo-short-name> #<id>: <full PR/MR title>
[x] merged: <repo-short-name> #<id>: <full PR/MR title>
[!] closed: <repo-short-name> #<id>: <full PR/MR title>
```

## Bundled executor

`scripts/link-pr-mr.js` implements the link step and mark-merged against the
Jira REST API directly, authenticating from the environment (`JIRA_API_TOKEN`
plus login/server in `~/.config/.jira/.config.yml`, or the `.jira-token` file
`acli` uses). It runs no other tool. `link` takes `--issue`, `--url`, `--title`,
optional `--host`, `--no-defaults`, `--no-comment`. `mark-merged --issue KEY`
takes the PR/MR states you checked as repeated `--state <url>=<merged|closed|open>`
arguments and prefixes accordingly. Stdout includes `move: …` and the
post-move `issue:` key.

Defaults configuration: `~/.config/jira-pr-mr-link/config.json` (template:
`config.example.json`), `$JIRA_PR_MR_CONFIG`, or `config.local.json` next to
the scripts. Precedence: CLI > env > config file > Jira CLI hints.

Another skill that needs the link step invokes `/rhdh-jira-link` by name and
lets this skill run its own scripts; it never calls into this directory by
path.

## Relationship to `/rhdh-pr-create`

`/rhdh-pr-create` owns the **rhdh-plugins** / **community-plugins** monorepo PR
flow (build, changesets, recordings). This skill owns the Jira Web link +
comment (and optional defaults) for any repo. Invoke it by name; do not read or
run its files.

Once `/rhdh-pr-create` has created a PR, it hands the URL and title back and
this skill runs the link step with defaults disabled, leaving `/rhdh-pr-create`
free to transition the issue to **Review** (see
[references/raise-pr-integration.md](references/raise-pr-integration.md)).

## Agent checklist

1. Resolve the Jira key. Ask if missing (unless the user skipped Jira).
2. Commit on a feature branch and push. Put the Jira browse URL and
   `Generated-by:` line in the PR/MR body.
3. Raise the PR/MR (when it does not exist), then run the link step. Report
   the PR/MR URL, the diffs page, and the resulting Jira link.
4. For mark-merged: report merged, closed, and still-open Web links, each with
   its PR/MR URL.
5. In user-facing summaries, link PR/MRs as `[<title>](<url>)`.

## Every run here is an external write

Creating a PR/MR, writing a Jira Web link, posting a comment, moving an issue to
another project, and filling default fields all change something outside the
session. Invoke `/mutation-gate` and follow it before the first operation:
one pass can perform several of these at once, so state them as one
set — push, create, link, comment, defaults — and get a single approval covering
all of them.

## Completion

Complete when the answer names the PR/MR URL and diffs link, the Jira key it was
linked to — including the post-move key when an RHDHPLAN Epic, Story, or Task
moved to RHIDP — the Web link title, whether the comment was posted or updated,
which default fields were newly set, and every warning the tooling printed.
Report the fields the pass left alone as kept, never as set. A Web link that
succeeded followed by a defaults update that errored is a partial link, so say
which half landed.
