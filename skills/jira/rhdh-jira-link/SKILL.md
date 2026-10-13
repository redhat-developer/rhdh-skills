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
compatibility: "Node on PATH; gh for GitHub and glab for GitLab; a Jira API token via JIRA_API_TOKEN or the .jira-token file acli uses."
---

# Jira PR / MR links

Zero-token Node scripts for **GitHub and GitLab**: create the PR/MR, attach a
Jira remote Web link, post or update a structured comment, and optionally fill
empty issue fields.

Scripts live under this skill's `scripts/` directory. Resolve that path from the
installed skill root (agents already have it when reading this file):

```bash
SKILL="$(cd "$(dirname "$0")" && pwd)"   # or the absolute path to this skill root
node "$SKILL/scripts/create-pr-mr.js" …
node "$SKILL/scripts/link-pr-mr.js" …
```

Another skill that needs the link step invokes `/rhdh-jira-link` by name and
lets this skill run its own scripts; it never calls into this directory by path.

## Preferred: one-shot create (`create-pr-mr.js`)

After the feature branch is committed:

Compose the reviewer-facing PR or MR title and body, then invoke
`/prose-editing` once on both in the **flavored** register. Preserve Jira keys,
closing syntax, headings, checklists, links, and the required `Generated-by`
line. Pass the edited strings to `create-pr-mr.js`; it is a transport layer and
must not edit them. The structured Jira link comment created later is a protocol
payload and does not receive this prose pass.

```bash
node "$SKILL/scripts/create-pr-mr.js" \
  --issue RHIDP-12345 \
  --title 'fix: short summary' \
  --target main \
  --body "$(cat <<'EOF'
## Summary
- …

## Test plan
- [ ] …

Generated-by: cursor
EOF
)"
```

1. `git push -u origin HEAD` (unless `--no-push`)
2. Detects GitHub vs GitLab from `origin`
3. Runs `gh pr create` or `glab mr create`
4. Runs `link-pr-mr.js link` (unless `--no-link`). Missing Jira auth is an
   error; pass `--no-link` to skip linking.
5. Opens the diffs page (unless `--no-open`)

Flags: `--draft`, `--no-push`, `--no-link`, `--no-open`, `--no-defaults`,
`--no-comment`, `--no-jira-ref`, `--host github|gitlab`.

### Auth

Either works (same token either way):

1. `JIRA_API_TOKEN` + `login`/`server` in `~/.config/.jira/.config.yml`, or
2. `.jira-token` (`email:token`) next to `acli` — the same credential
   `/rhdh-jira-api` uses. Invoke `/rhdh-jira-api` by name for the authoritative auth
   setup instead of duplicating it here.

`create-pr-mr.js` appends `Ref: https://redhat.atlassian.net/browse/KEY` and
`Generated-by: cursor` to the **PR/MR body** when missing. It skips the Jira
`Ref:` line for `community-plugins` remotes (or when `--no-jira-ref` is set) so
that repo stays free of Jira browse URLs in git history / PR text.

## Link-only: `link-pr-mr.js`

When a PR/MR already exists:

```bash
node "$SKILL/scripts/link-pr-mr.js" link \
  --issue RHIDP-12345 \
  --url 'https://gitlab.cee.redhat.com/rhidp/example/-/merge_requests/817' \
  --title 'example #817: fix: short summary' \
  --host gitlab
```

- `--host` optional; inferred from URL when omitted.
- `--no-defaults` skips In Progress + metadata fills (Web link + comment still run).
- `--no-comment` skips the Jira comment.
- If a comment already mentions the PR/MR URL, it is **updated** in place
  (comments are paginated).

### RHDHPLAN → RHIDP auto-move

If the linked issue is an **Epic**, **Story**, or **Task** in **RHDHPLAN**,
`link` moves it to **RHIDP** (same issue type) via the Jira bulk-move API, then
continues Web link / defaults / comment on the **new** key. Features and other
RHDHPLAN types are left alone.

Stdout includes `move: …` and the post-move `issue:` key.

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

The Web link title remains `repo #N: <title>` (unchanged).

### Mark merged / closed

```bash
node "$SKILL/scripts/link-pr-mr.js" mark-merged --issue RHIDP-12345
```

Prefixes Web link titles with `[x] merged: ` when the PR/MR is merged, or
`[!] closed: ` when it is closed without merging. Does not re-apply
defaults/comment. Stdout lists each title **and** its PR/MR URL (indented under
the title). Open PRs/MRs stay in `leftOpen` with no prefix.

`mark-merged` checks status via `gh` / `glab`. Failed checks print a
`warn:` line and leave the link in `leftOpen` (do not treat a failed check as
closed). For GitLab remotelinks it passes `--hostname` from the URL
(e.g. `gitlab.cee.redhat.com`), so CEE MRs resolve against the right host.
Prefer `glab` default `host: gitlab.cee.redhat.com` in
`~/.config/glab-cli/config.yml` for day-to-day CEE work.

When summarizing to the user, use markdown links (`[<title>](<url>)`).

## Title format (for `link --title`)

```
<repo-short-name> #<id>: <full PR/MR title>
```

Merged: `[x] merged: <repo-short-name> #<id>: <full PR/MR title>`
Closed (not merged): `[!] closed: <repo-short-name> #<id>: <full PR/MR title>`

## Defaults `link` applies (only if empty)

**No built-in team/assignee values.** First run with defaults enabled requires a
config file (or env/CLI). Missing keys error **when applying defaults**; the Web
link and comment still succeed with `--no-defaults`.

```bash
mkdir -p ~/.config/rhdh-jira-link
cp "$SKILL/config.example.json" ~/.config/rhdh-jira-link/config.json
# edit assigneeEmail, teamId, teamName, boardId, …
```

Also accepted: `$JIRA_PR_MR_CONFIG` or `$SKILL/config.local.json`
(keep personal email out of the repo).

Precedence: **CLI > env > config file > Jira CLI hints** (`login` / `board.id`
from `~/.config/.jira/.config.yml` may fill assignee/board only).

| Field | Required when applying defaults |
|-------|----------------------------------|
| `assigneeEmail` | yes (or Jira `login` email) |
| `teamId` / `teamName` | yes, or set either to `NONE` to skip team **and** sprint |
| `boardId` | yes (or jira CLI `board.id`), unless team/sprint skipped via `NONE` |
| `storyPoints` | yes |
| `priorityName` | yes (only fills when priority is empty) |
| `storyPointsField` | yes |
| `teamField` / `sprintField` | yes, unless team/sprint skipped via `NONE` |
| Status | → **In Progress** unless already In Progress / Review / Closed |

Skip all defaults: `--no-defaults` or `JIRA_PR_MR_APPLY_DEFAULTS=0`.

Skip only team + sprint (still set points / assignee / priority / In Progress):

```json
"teamName": "NONE",
"teamId": "NONE"
```

## Relationship to `/rhdh-pr-create`

`/rhdh-pr-create` owns the **rhdh-plugins** / **community-plugins** monorepo PR
flow (build, changesets, recordings). This skill owns the Jira Web link +
comment (and optional defaults) for any repo. Invoke it by name; do not read or
run its files.

Once `/rhdh-pr-create` has created a PR, it hands the URL and title back and
this skill runs the link step with `--no-defaults`, leaving `/rhdh-pr-create`
free to transition the issue to **Review** (see
[references/raise-pr-integration.md](references/raise-pr-integration.md)).

## Agent checklist

1. Resolve Jira key. Ask if missing (unless user skipped Jira).
2. Commit on a feature branch. Put the Jira browse URL and `Generated-by: cursor`
   in the **PR/MR body** (`create-pr-mr.js` appends them when missing; skips
   `Ref:` for community-plugins).
3. Run **`create-pr-mr.js`** once. Report `url:` / `diffs:` / `browserOpened:` /
   `jiraLink:` from its stdout (`browserOpened: true` or `--no-open` means the
   open step is already done).
4. Fallback: raw create → run `link-pr-mr.js`, then open diffs yourself once.
5. For mark-merged: `link-pr-mr.js mark-merged --issue KEY`. Report merged,
   closed, and still-open Web links.
6. In user-facing summaries, link PR/MRs as `[<title>](<url>)`.

## Every run here is an external write

Creating a PR/MR, writing a Jira Web link, posting a comment, moving an issue to
another project, and filling default fields all change something outside the
session. Invoke `/mutation-gate` and follow it before the first command:
one script invocation can perform several of these at once, so state them as one
set — push, create, link, comment, defaults — and get a single approval covering
all of them.

## Completion

Complete when the answer names the PR/MR URL and diffs link, the Jira key it was
linked to — including the post-move key when an RHDHPLAN Epic, Story, or Task
moved to RHIDP — the Web link title, whether the comment was posted or updated,
which default fields were newly set, and every `warn:` line the scripts printed.
Report the fields the script left alone as kept, never as set. A Web link that
succeeded followed by a defaults update that errored is a partial link, so say
which half landed.
