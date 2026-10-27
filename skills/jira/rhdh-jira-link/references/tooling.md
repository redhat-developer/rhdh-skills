# Local tooling: link-pr-mr commands

**The optional tooling sidecar.** Exact scripts for the protocol in
`SKILL.md`, for agents that have Node, `gh`/`glab`, and a Jira token. An ADLC
tool may perform the same steps; the protocol `SKILL.md` pins binds whichever
tool runs.
The scripts are transport layers: they post exactly what they are given and
never edit prose.

## Script location

Scripts live under this skill's `scripts/` directory. Resolve that path from
the installed skill root (agents already have it when reading this file):

```bash
SKILL="$(cd "$(dirname "$0")" && pwd)"   # or the absolute path to this skill root
node "$SKILL/scripts/create-pr-mr.js" …
node "$SKILL/scripts/link-pr-mr.js" …
```

Another skill that needs the link step invokes `/rhdh-jira-link` by name and
lets this skill run its own scripts; it never calls into this directory by
path.

## Raise and link in one shot (`create-pr-mr.js`)

Run after the feature branch is committed. Pushes, detects GitHub vs GitLab
from `origin`, creates the PR/MR, then runs the link step (unless
`--no-link`; missing Jira auth is an error — pass `--no-link` to skip
linking) and opens the diffs page (unless `--no-open`):

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

Flags: `--draft`, `--no-push`, `--no-link`, `--no-open`, `--no-defaults`,
`--no-comment`, `--no-jira-ref`, `--host github|gitlab`.

`create-pr-mr.js` appends `Ref: https://redhat.atlassian.net/browse/KEY` and
`Generated-by: cursor` to the PR/MR body when missing, and skips the Jira
`Ref:` line for `community-plugins` remotes (or when `--no-jira-ref` is set).

## Link an existing PR/MR (`link-pr-mr.js link`)

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

Stdout includes `move: …` and the post-move `issue:` key when an RHDHPLAN
Epic/Story/Task moved to RHIDP.

## Mark merged / closed

```bash
node "$SKILL/scripts/link-pr-mr.js" mark-merged --issue RHIDP-12345
```

Prefixes Web link titles with `[x] merged:` or `[!] closed:` (see
`SKILL.md` for the title formats). `mark-merged` checks status via `gh` /
`glab`; failed checks print a `warn:` line and leave the link in `leftOpen`
(do not treat a failed check as closed). For GitLab remotelinks it passes
`--hostname` from the URL (e.g. `gitlab.cee.redhat.com`), so CEE MRs resolve
against the right host. Prefer `glab` default `host: gitlab.cee.redhat.com` in
`~/.config/glab-cli/config.yml` for day-to-day CEE work.

## Auth

Either works (same token either way):

1. `JIRA_API_TOKEN` + `login`/`server` in `~/.config/.jira/.config.yml`, or
2. `.jira-token` (`email:token`) next to `acli` — the same credential
   `/rhdh-jira-api` uses. Invoke `/rhdh-jira-api` by name for the
   authoritative auth setup instead of duplicating it here.

## Defaults

First run with defaults enabled requires a config file (or env/CLI). Missing
keys error **when applying defaults**; the Web link and comment still succeed
with `--no-defaults`.

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

Skip all defaults: `--no-defaults` or `JIRA_PR_MR_APPLY_DEFAULTS=0`. Skip only
team + sprint (still set points / assignee / priority / In Progress):

```json
"teamName": "NONE",
"teamId": "NONE"
```

## Serving `/rhdh-pr-create`

After `/rhdh-pr-create` hands back the PR URL and title, run the link step
with `--no-defaults`, then report the post-move key and let `/rhdh-pr-create`
transition the issue to **Review**:

```bash
REPO_SHORT="$(basename "$(git rev-parse --show-toplevel)")"
LINK_OUT="$(node "$SKILL/scripts/link-pr-mr.js" link \
  --issue "$JIRA_KEY" \
  --url "$PR_URL" \
  --title "${REPO_SHORT} #${PR_NUM}: ${PR_TITLE}" \
  --host github \
  --no-defaults)"
echo "$LINK_OUT"
EFFECTIVE_KEY="$(printf '%s\n' "$LINK_OUT" | awk -F': ' '/^issue:/{print $2; exit}')"
EFFECTIVE_KEY="${EFFECTIVE_KEY:-$JIRA_KEY}"

acli jira workitem transition --key "$EFFECTIVE_KEY" --status "Review" --yes
```

Why `--no-defaults`: the linker's default status target is **In Progress**;
`/rhdh-pr-create` wants **Review** after PR submit. Defaults remain available
for general agent sessions that use `create-pr-mr.js` alone. The sequencing
contract lives in
[raise-pr-integration.md](raise-pr-integration.md).
