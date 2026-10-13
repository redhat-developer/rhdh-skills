# Release capacity planning

Forecast whether a named team can take the `rhdh-X.Y-candidate` Features for a
release: sample-sprint velocity and interrupt, Epic-first demand, and two
capacity ledgers through Code Freeze.

Use paginated `acli` for bulk reads. For Greenhopper sprint reports, invoke
`/rhdh-jira-api` and let it run its token-file adapter; never `curl`, never
`cat` a token file, never set `AUTH` in chat. `/rhdh-jira-api` owns both
adapters. This workflow is read-only.

Feed the gathered snapshot to `uv run scripts/capacity.py`. Do not re-implement
the arithmetic in prose.

## Input

1. **Team** — name or Jira team UUID. Resolve Cloud ID and board through
   `/rhdh-release-teams` and `/rhdh-jira-api`. Never infer a team from member
   names.
2. **Release version** — e.g. `2.2`. Builds the candidate label
   `rhdh-2.2-candidate`. Ask if missing.
3. **Availability** — default every `FULL_MEMBER` to 100% only when the shared
   PTO calendar has no match for that person. Do not ask for PTO unless the
   calendar cannot be read.
4. **Meeting factor** — default `0.4` (keep 60% of theoretical capacity for
   implementation). Override only when the user names another fraction.
5. **History window** — last 6 closed sprints on the team's board, unless the
   user names a sample range.
6. **Sprint length** — default 21 calendar days (three-week sprints). Pass
   snapshot `sprint_days` only when the user names another length.
7. **SP per person per sprint** — omit to infer from sample completions (the
   script backs out meetings and interrupt before re-applying them). If the user
   supplies a full-focus rate, pass it through as `sp_per_person_sprint`.

## Step 1 — Resolve team, board, roster, and dates

Invoke `/rhdh-release-teams` for Cloud ID. Look up the board in `/rhdh-jira-api`
(the board table). Fetch `FULL_MEMBER` only via the `GetTeamRoster` query;
drop `INVITED` and `ALUMNI`.

Invoke `/rhdh-release-schedule` for Feature Freeze and Code Freeze. Remaining
sprints are three-week slots from today through Code Freeze
(`ceil((code_freeze − today).days / sprint_days)` with `sprint_days` default
21); also print Feature Freeze. If the user already gave `remaining_sprints`,
keep that number.

## Step 2 — Shared PTO calendar

Read the shared RHDH PTO calendar for every team this skill plans. Calendar id:

`c_ffcd3890d6ab3d3b494646b5fa4f36634051b45fcae3456ca6bd5a7d6e7aa5f4@group.calendar.google.com`

Timezone `America/Toronto`. List events from today through Code Freeze with
`gog` (same credential store as sheets). `--max` defaults to 10 — always pass
`--all-pages`:

```bash
gog calendar events \
  'c_ffcd3890d6ab3d3b494646b5fa4f36634051b45fcae3456ca6bd5a7d6e7aa5f4@group.calendar.google.com' \
  --from TODAY --to CODE_FREEZE \
  --timezone America/Toronto \
  --all-pages --json --results-only
```

Match each event to this team's roster by summary and attendees against display
name. Unmatched events are reported, not applied. Default remains 100% when
there is no match.

Google all-day events use start inclusive and end exclusive. Clip each matched
event to `[today, code_freeze]` and count weekdays (Mon–Fri). Per person:

`availability = 1 − (pto_weekdays / (remaining_sprints × sprint_days × 5/7))`

clipped to `[0, 1]`. Pass the fractions as `members[].availability`. Do not
invent a calendar parser unless event JSON is too messy to map in this
workflow.

If `gog` lacks calendar scope, say so and keep 100% availability rather than
guessing PTO. Name `/setup-rhdh-skills` so a new login can request `calendar`
alongside sheets.

## Step 3 — Sample closed sprints

```bash
acli jira board list-sprints --id BOARD_ID --state closed --json
```

`acli` has no `--recent`. Take the last 6 closed sprints whose names match the
team (sprint numbers are shared across teams on some boards). For each:

```bash
acli jira sprint view --id SPRINT_ID --json
```

Record `startDate`. Include the human chart URL:

`https://redhat.atlassian.net/jira/software/c/projects/RHIDP/boards/{boardId}/reports/burndown-chart?sprint={sprintId}`

## Step 4 — Velocity and interrupt

Try Greenhopper first. Invoke `/rhdh-jira-api`: run `uv run scripts/setup.py
--json` and use `token_file_found` / `token_file_status` (contents are never
printed). If the token file is missing or unreadable, skip Greenhopper in one
line and reconstruct. If it is found, run:

```bash
uv run scripts/greenhopper.py sprintreport --board BOARD_ID --sprint SPRINT_ID
```

That adapter reads the local token file in-process. Never `curl`. Never `cat`
the token file. Never set `AUTH` or paste an Authorization header.

On HTTP 404/403, or a body that lacks `contents`, skip in one line and
reconstruct. Put a successful report on the sprint as `greenhopper_sprintreport`.

**Reconstruction** — search with fields `acli` actually allows, then enrich.
`storypoints` and `sprint` are custom fields; `acli jira workitem search
--fields` rejects them.

```bash
acli jira workitem search \
  --jql 'project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND sprint = SPRINT_ID AND "Team[Team]" = TEAM_ID' \
  --fields "key,summary,status,issuetype,assignee" --paginate --json
```

Ask `/rhdh-jira-api` to enrich with `parse_issues.py --enrich` (or `view
--fields '*all'`). Changelog via the host adapter `getJiraIssue
expand=changelog` is a last-resort sample, not a loop over hundreds of issues.

An issue is interrupt when Greenhopper `issueKeysAddedDuringSprint` (or a
changelog that was actually fetched) shows its Sprint field joined after
`startDate`. If changelog cannot be fetched and Greenhopper was skipped, set
snapshot `interrupt_retrieved` to false — do not write `added_after_start:
false` for every issue and treat that as a 0% interrupt rate.

Completed is Closed or Release Pending. Put each sprint into the snapshot as
either `greenhopper_sprintreport` or `issues` with `added_after_start` only
when that flag was retrieved, plus `burndown_url`. The script computes
completed, interrupt, and planned-completed points. Rolled-forward issues
(`issuesCompletedInAnotherSprint`) are not completed in this sprint.

## Step 5 — Candidate demand

```jql
project = RHDHPLAN AND issuetype = Feature AND labels = 'rhdh-VERSION-candidate'
ORDER BY priority ASC
```

Enrich Size, labels (`stretch`), and Team. For each Feature, query child Epics:

```jql
issuetype = Epic AND parent = FEATURE_KEY
```

If that returns 0, retry `"Epic Link" = FEATURE_KEY`. Keep Epics whose Team is
the specified team. For each kept Epic, sum child Story Points:

```jql
parent = EPIC_KEY
```

Demand rules (Epic-first):

- Team Epic with child Story Points → use that sum.
- Team Epic with no child points but a T-shirt → placeholder Fibonacci from
  the script. Print `demand.tshirt_placeholder_note`.
- No team Epic → Feature T-shirt the same way.
- No size and no child points → unsized. Do not invent a number.

Never treat the Size field's 1–5 as story points. Never convert T-shirt
through sprint-effort × team velocity.

## Step 6 — Run the arithmetic

Write the snapshot (team, version, board, dates, `sprint_days` when overridden,
members with availability, sprints, features, meeting factor, optional
`sp_per_person_sprint`, `interrupt_retrieved` when reconstruction skipped
changelog) and run:

```bash
uv run scripts/capacity.py --input snapshot.json
```

Pretty JSON on a TTY, compact when piped. Exit 1 on a bad snapshot.

The script shows:

- **Fillable** — mean planned-completed (interrupt already excluded) × remaining
  sprints × availability. Fit **required demand** against this line. When
  interrupt was unretrieved, this is an **upper bound**, not candidate room.
- **Interrupt reserve** — mean interrupt × remaining × availability, printed
  separately. Do not fill it with candidates. Absent when interrupt was
  unretrieved; do not claim a 0% interrupt rate.
- **Historical** — the same planned net as fillable, kept as the sample-velocity
  ledger.
- **Theoretical** — available people × remaining sprints × SP/person/sprint ×
  (1 − meeting factor) × (1 − interrupt rate) **when the rate is known**. If
  SP/person/sprint was inferred from Jira completions, it is backed out of the
  40% and interrupt before those haircuts are applied again. When interrupt was
  skipped, omit the interrupt term; do not re-apply `× 1` and treat the two
  ledgers as independent confirmation.

If sample story-point coverage is under 50%, the script switches the unit to
issue counts and sets `coverage_warning`. Say that out loud.

## Output

```markdown
## Release capacity — {team} {version}

Horizon: today → Code Freeze {code_freeze} ({remaining} three-week sprints)
Feature Freeze: {feature_freeze}
Sprint length: {sprint_days} days

### Sample velocity
| Sprint | Source | Completed | Interrupt | Planned completed | Chart |
|--------|--------|-----------|-----------|-------------------|-------|

Avg planned (fillable): {mean} {unit}/sprint | Interrupt retrieved: {yes/no}
Interrupt rate: {rate or unretrieved} | Coverage: {coverage}

### Demand ({total} {unit}, {required} required, {stretch} stretch)
Placeholder T-shirt→SP: {demand.tshirt_placeholder_note or not used}

| Feature | Size | Basis | {unit} | Placeholder | Stretch | Team epics |
|---------|------|-------|--------|-------------|---------|------------|

Unsized: {keys or none}

### Capacity vs demand
| Bucket | Arithmetic | Net | Notes |
|--------|------------|-----|-------|
| Fillable (planned) | {fillable.arithmetic} | {net} | {upper bound if interrupt unretrieved} |
| Interrupt reserve | {reserve.arithmetic or n/a} | {net or n/a} | not candidate room |
| Required demand | — | {required} | fit against fillable |
| All candidates | — | {total} | includes stretch |

Required vs fillable: {fits} (slack {slack})
All-candidates vs fillable: {fits} (slack {slack})

### Ledgers
| Ledger | Arithmetic | Net | Required fit | All-candidates fit |
|--------|------------|-----|--------------|--------------------|
| Historical | {historical.arithmetic} | {net} | {fits} ({slack}) | {fits} ({slack}) |
| Theoretical | {theoretical.arithmetic} | {net} | {fits} ({slack}) | {fits} ({slack}) |

Meeting factor {meeting} (keep {1-meeting} for implementation). Theoretical
SP/person/sprint source: {inferred_backed_out or user_full_focus}. Do not
recommend filling theoretical when interrupt was unretrieved.

### PTO
| Member | Availability | Matched events |
|--------|--------------|----------------|
Unmatched calendar events: {summaries or none}

### First cuts
Stretch Features, in priority order: {keys}
```

## Error handling

| Error | Action |
|---|---|
| Team or version missing | Ask. Do not guess a release from the newest label you have seen. |
| Board ID not found | Ask. List boards with `acli jira board search --project RHIDP`. |
| No closed sprints | Stop velocity. Say historical data is unavailable. |
| Token file missing or unreadable | Skip Greenhopper in one line; reconstruct. Do not `chmod 644` the token. |
| Greenhopper 404/403 or adapter error | Skip in one line; reconstruct. |
| Changelog unretrieved | Interrupt is unretrieved, not zero. Fillable is an upper bound. |
| `gog` calendar scope missing | Keep 100% availability; name `/setup-rhdh-skills`. |
| Bulk search truncated | Report a floor, not a total. Retry once with `--paginate`. |
| Code Freeze TBD | Ask for a remaining-sprint count rather than inventing dates. |
| Story-point coverage under 50% | Keep the script's issue-count unit and say why. |

## Caveats

1. **Meetings already sit inside Jira velocity.** Historical planned-completed
   already reflects meetings and interrupt. The theoretical ledger is the one
   that applies the 40% haircut, and only after backing out an inferred rate.
   Print both arithmetic lines so that cannot be missed.
2. **Do not fill interrupt.** Fit required demand against fillable planned
   capacity. The interrupt reserve is capacity that must remain empty.
3. **T-shirt→SP is a placeholder.** The script owns the Fibonacci map. That
   map is not calibrated, not the Size field's 1–5, and not sprint-effort ×
   team velocity (which treats extra-small as whole-team sprints). Child
   story points are real; T-shirt rows are not. Print
   `demand.tshirt_placeholder_note` whenever it is set.
4. **Greenhopper is unofficial and may vanish.** Reconstruction from issues
   currently on a sprint id double-counts work that rolled forward and
   finished later. Prefer the report sums when present. The chart URL is for
   humans.
5. **Scope-change detection from changelog is approximate.** Issues moved
   between sprints can look like interrupt.
6. **Release Pending counts as completed**, matching sprint-plan convention.
