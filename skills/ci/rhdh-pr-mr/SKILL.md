---
name: rhdh-pr-mr
description: >-
  Pushes a topic branch and opens a GitHub pull request or GitLab CEE merge
  request for CI and agent automation, then links Jira via /rhdh-jira-link only
  when an issue key is known. Use for "open a PR", "create the merge request",
  "push and open PR/MR after a yarn or base-image bump", or when another CI
  skill needs a shared opener. Not for plugin changeset publish (/rhdh-pr-create)
  and not a replacement for midstream createPR.sh inside updateBaseImages.sh.
compatibility: "bash, git, jq, curl; gh for GitHub; PRIVATE_TOKEN (and optional glab) for GitLab CEE; JIRA_API_TOKEN when linking."
---

# RHDH PR / MR opener

Shared script for push + open. Caller owns the commit and `/mutation-gate`
approval when an agent is driving. Weekly bots may call the script unattended.

## Boundaries

- **Not** `/rhdh-pr-create` (plugin changesets, recordings, monorepo publish).
- **Does** call `/rhdh-jira-link` `link-pr-mr.js` when `--issue` or `JIRA_ISSUE` is set.
- **Skips** Jira when no key is known — never invent one.
- Midstream `createPR.sh` (distgit) stays for `updateBaseImages.sh` until a later migration.

## Script

```bash
SKILL=<this skill's directory>
"$SKILL/scripts/create-pr-mr.sh" \
  --cwd /path/to/checkout \
  --base main \
  --head chore/my-topic \
  --title 'chore: short summary' \
  --body-file /tmp/body.md \
  [--issue RHIDP-12345] \
  [--label ok-to-test] \
  [--dry-run]
```

Default is `--no-open` (no browser). Pass `--open` only for interactive agent runs.
`GITLAB_PIPELINE=true` forces no browser.

The script appends ` [<base>]` to `--title` when that suffix is missing, including
for `main` (`chore: short summary` becomes `chore: short summary [main]`). A
title that already ends with the base branch is left as-is.

Stdout includes `url: …`. Exit 0 if a PR/MR already exists for `--head`.

## Jira

| Condition | Behavior |
| --- | --- |
| `--issue KEY` or `JIRA_ISSUE` set + `JIRA_API_TOKEN` | After open, invoke `/rhdh-jira-link` (`link-pr-mr.js link`). The Jira comment is `PR: <url>` or `MR: <url>` (plus optional Adjusted fields). |
| Issue set but no token / missing link script | Warn; PR/MR still succeeds |
| No issue | `[INFO] no Jira issue; skip link` |

Override the link scripts directory with `RHDH_JIRA_LINK_SCRIPTS` when the
sibling skill is not next to this one in the pack checkout.

## Agents

1. Follow `/mutation-gate` for push + open (+ link if issuing).
2. Invoke `/rhdh-pr-mr` by name (or run the script path when already inside a
   skill clone). Pass `--issue` when the conversation already has a Jira key.
3. Report the `url:` line.

## Tests

```bash
bash -n "$SKILL/scripts/create-pr-mr.sh"
shellcheck --severity=warning "$SKILL/scripts/create-pr-mr.sh"
"$SKILL/scripts/create-pr-mr.sh" --help
"$SKILL/tests/smoke.sh"
```

## Completion

Done when the topic branch is pushed, a PR or MR URL is printed, and either a
Jira Web link was updated or linking was explicitly skipped for lack of an issue.
