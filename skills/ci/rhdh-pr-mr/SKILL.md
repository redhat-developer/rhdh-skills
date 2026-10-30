---
name: rhdh-pr-mr
description: >-
  Pushes a topic branch and opens a GitHub pull request or GitLab CEE merge
  request for CI and agent automation after validating AI/tool attribution and a
  linked Jira issue in its description, then links Jira via /rhdh-jira-link.
  Use for "open a PR", "create the merge request", "push and open PR/MR after
  a yarn or base-image bump", or when another CI skill needs a shared opener.
  Not for plugin changeset publish (/rhdh-pr-create) and not a replacement for
  midstream createPR.sh inside updateBaseImages.sh.
compatibility: "bash, git, jq, curl; gh for GitHub; PRIVATE_TOKEN (and optional glab) for GitLab CEE; JIRA_API_TOKEN when linking."
---

# RHDH PR / MR opener

Shared script for push + open. Caller owns the commit and `/mutation-gate`
approval when an agent is driving. Weekly bots may call the script unattended.

## Boundaries

- **Not** `/rhdh-pr-create` (plugin changesets, recordings, monorepo publish).
- **Requires** a known Jira key and calls `/rhdh-jira-link` after opening. Stop
  before pushing when no issue is known; never invent one.
- **Requires** an explicit attribution resolved from the available IDE, CLI,
  and model identity.
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
  --issue RHIDP-12345 \
  --assisted-by '<IDE or CLI> (<model label>)' \
  [--label ok-to-test] \
  [--dry-run]
```

Default is `--no-open` (no browser). Pass `--open` only for interactive agent runs.
`GITLAB_PIPELINE=true` forces no browser.

The script appends ` [<base>]` to `--title` when that suffix is missing, including
for `main` (`chore: short summary` becomes `chore: short summary [main]`). A
title that already ends with the base branch is left as-is.

Resolve the `--assisted-by` value from the current work, in this order:

1. Use `<IDE or CLI> (<model label>)` when both are known, such as
   `Codex (5.6 Sol High)`.
2. Use `<IDE or CLI>` when the tool is known but the model is not.
3. Use `Unknown AI (possibly Skynet)` when neither can be identified.

Before pushing, the script verifies that the latest commit contains the exact
`Assisted-By: <resolved value>` trailer. It adds the same line and
`Related Jira: [KEY](https://redhat.atlassian.net/browse/KEY)` to the PR/MR
description.

GitLab MRs set `remove_source_branch: true` so merging deletes the topic branch.

Stdout includes `url: …`. Exit 0 if a PR/MR already exists for `--head`.

## Jira

| Condition | Behavior |
| --- | --- |
| `--issue KEY` or `JIRA_ISSUE` set + `JIRA_API_TOKEN` | Add the linked issue to the description, then invoke `/rhdh-jira-link` (`link-pr-mr.js link`). The Jira comment is `PR: <url>` or `MR: <url>` (plus optional Adjusted fields). |
| Issue set but no token / missing link script | The linked description remains; warn that the Jira backlink was skipped. |

Override the link scripts directory with `RHDH_JIRA_LINK_SCRIPTS` when the
sibling skill is not next to this one in the pack checkout.

## Agents

1. Resolve the most specific available attribution with the fallback order
   above and add that exact `Assisted-By:` trailer to the commit.
2. Resolve the Jira key from the conversation. Stop before pushing when none is
   known; never turn a plain issue key in the description into an unlinked label.
3. Follow `/mutation-gate` for push + open + Jira link.
4. Invoke `/rhdh-pr-mr` by name (or run the script path when already inside a
   skill clone), passing `--issue` and `--assisted-by`.
5. Report the `url:` line.

## Tests

```bash
bash -n "$SKILL/scripts/create-pr-mr.sh"
shellcheck --severity=warning "$SKILL/scripts/create-pr-mr.sh"
"$SKILL/scripts/create-pr-mr.sh" --help
"$SKILL/tests/smoke.sh"
```

## Completion

Done when the topic branch is pushed; the latest commit and PR/MR description
carry the exact resolved attribution; the description contains the Markdown
Jira link; a Jira Web link was updated or its missing credential was reported;
and a GitLab MR is configured to delete its source branch after merge.
