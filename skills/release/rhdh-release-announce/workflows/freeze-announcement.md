# Workflow: Freeze announcement

Four announcements, one command, one token apart.

<prerequisites>

Jira reads use `acli`, team data uses `gog`, and every freeze and release-note
scope comes from the Rich Filter export. Run
`uv run scripts/release.py --json check` when anything fails and follow its
`next_steps`.

</prerequisites>

<process>

## Step 1: Pick the announcement

The pairs differ by **when they are sent**, not by content depth. Confirm which
one the user means when the request just says "the freeze message" — sending an
update on the freeze day, or the milestone message a week early, is the mistake
this table exists to prevent.

| Ask | Token | Sent |
|---|---|---|
| Feature Freeze has been reached | `feature-freeze` | **on** the Feature Freeze date |
| Feature Freeze status update | `feature-freeze-update` | **before** the Feature Freeze date |
| Code Freeze has been reached | `code-freeze` | **on** the Code Freeze date |
| Code Freeze status update | `code-freeze-update` | **before** the Code Freeze date |

```bash
uv run scripts/release.py --json slack <token> {{RELEASE_VERSION}}
```

The `slack_message` field is the filled template. Use it as the draft body; do
not rebuild it from the parts.

The two milestone messages carry the release-wide figures — blocker bugs, feature
demos, Test Day features, open issues, EPICs, CVEs, release notes. The two
updates carry per-team lines with each team's count, Jira link, and lead Slack
handle, plus the freeze date itself, so the teams still holding work can see it.

## Step 2: Edit, then present

Invoke `/prose-editing` on the full draft in the **voiced** register. Present
what it returns in a triple-backtick block. Never show the unedited message as
the draft.

Alongside the draft, list any figure the CLI could not produce. Leave it named
and missing; do not fill it.

## Step 3 (fallback): milestone messages only

If `slack code-freeze` fails, rebuild the message: take blocker bugs and open
issues with the bundled Jira adapter using the `blockers` and `open_issues` templates in
`scripts/jql-release.md`, feature demos from
`rich-filter query static demo --version "{{VERSION}}" --count`, Test Day features
from `rich-filter query static "Test Day" --version "{{VERSION}}" --count`, then
fill the **Code Freeze Announcement** template in `scripts/slack-templates.md`.

The two update messages have no fallback. Their team scoping comes from the Rich
Filter's Cloud ID clauses; fix the configuration and retry instead.

</process>

<gotchas>

- The `Feature Freeze` filter excludes infrastructure and ops components and
  excludes bugs. That is deliberate — Feature Freeze tracks feature work, so a
  larger open-issue count elsewhere is not a contradiction.
- `Code Freeze` scope is whatever the Rich Filter says it is. Never replace it
  with `status != closed`.
- After Code Freeze there are no cherry-picks without explicit release-manager
  approval, and only critical CVEs are considered before GA. The Code Freeze
  milestone message is where the channel learns that.
- Every count in the message needs a URL-encoded Jira search link so recipients
  can drill in without asking.
- Keep the triple-backtick block intact. Slack formatting inside it is copied
  verbatim by the sender.

</gotchas>

<success_criteria>

- [ ] The right token for the milestone-or-update the user meant
- [ ] `/prose-editing` ran on the draft before it was shown
- [ ] Draft in a triple-backtick block, no placeholders left unfilled
- [ ] Every count carries a Jira link; missing figures are named, not invented
- [ ] Nothing was posted

</success_criteria>
