# Refine RHDH Jira issues

Analyze issues for readiness, missing fields, duplicates, stale comments, and
relevance. Produces a refinement report with actionable recommendations and
optional fixes.

Reads and writes go through `/rhdh-jira-api` — it owns the JQL, the field IDs,
the enrichment rules, and the adapter order. In local mode the exact commands
are in [references/tooling.md](../references/tooling.md).

## Input

The caller provides one of:

1. **Issue key(s)** — one or more specific issues.
2. **JQL query** — e.g. `"project = RHIDP AND sprint in openSprints() AND status = New"`.
3. **`sprint`** — every issue in the current sprint that needs refinement.
4. **`backlog`** — unrefined backlog issues for a team.

For `sprint` or `backlog`, ask for the team ID or infer it from context.

## Refinement context

Ask or infer which of these the caller is in. It changes the tone, the urgency
framing, and which checks matter.

| Context | Goal | Framing |
|---|---|---|
| **Pre-release prep** | Features are ready to start when the release kicks off | "Ready for a clean start" |
| **Mid-release hygiene** | In-flight features are on track, no blockers | "On track for delivery" |
| **Feature freeze triage** | Everything must be complete or descoped | "Must close or descope before freeze" |
| **Feature Exploration** | Feature candidates are understood, sized, and owned | "What do we need to know before committing" |

Pre-release prep cares about sizing, child Epics, and readiness to leave
Refinement. Freeze triage cares about completion, blockers, and descope
candidates. Feature Exploration runs Check 7 as its main event.

## Terminology, and why it matters here

**Feature Exploration** is the meeting where team leads, architects, and
engineers review candidate Features, ask questions, and identify risks.
**Refinement** is a Jira workflow status. They are not the same thing, and
conflating them produces bad advice.

Features in **New** status are *expected* going into Feature Exploration. The
New → Refinement transition is an **outcome** of exploration, not a prerequisite
for it. Sizing and field population happen during and after the meeting. Do not
tell a team to refine a Feature before they are allowed to explore it.

Epic creation can happen before *or* during exploration. Teams often create child
Epics beforehand precisely to size the parent Feature, since aggregate Epic sizes
inform its T-shirt size.

## Exit criteria

`/rhdh-jira-api` holds the exit criteria tables per issue type and status. It is
the single source of truth for which fields a status requires. Load it before
Check 1 and do not restate its tables here.

Definitions the checks below use:

- **Unrefined** — Story Points empty, not in a sprint, status New or Refinement.
- **Ready for Planning** — Story Points set, not in a sprint, status Backlog or To Do.
- **Planned** — Story Points set, in an open or future sprint, status To Do / In Progress / Review, assignee set.
- **DoR** — all exit criteria from entry statuses complete before In Progress.
- **DoD** — all exit criteria for all statuses complete before Closed.

## Checks

Run every applicable check per issue.

Fetch with enrichment. A plain search result omits every custom field, so Story
Points, Team, Size, and Sprint come back empty whether or not they are set.

> Tooling: `references/tooling.md#bulk-read`

### Check 1 — Missing fields against exit criteria

Determine each issue's type and current status, look up the required fields in
`/rhdh-jira-api`, and report what is missing.

| Issue type | Field | How to verify |
|---|---|---|
| All | Assignee | `assignee` is not null |
| All | Priority | `priority.name` is not "Undefined" |
| All | Component | At least one component in `JiraComponentsField` |
| Feature/Epic | Team | Read the Team custom field (`customfield_10001`) with all fields requested; use the host adapter if absent |
| Feature/Epic | Size | The `Size` single-select has a value |
| Story/Task/Bug | Story Points | `storyPoints` is not null |
| Epic | Description | The Description rich-text field is not empty |
| Feature (Refinement+) | Candidate label | Labels include an `rhdh-X.Y-candidate` |
| Feature (Backlog+) | Child Epics | `parent = {key}` returns at least one Epic |
| Epic (To Do+) | Child Stories/Tasks | `parent = {key}` returns children |

### Check 2 — Duplicates

Run the audit check from `/rhdh-jira-authoring` for each issue. Flag likely and
possibly-related duplicates.

### Check 3 — Hierarchy integrity

| Issue type | Check | Finding if missing |
|---|---|---|
| Epic | Has a parent Feature in RHDHPLAN | "Epic has no parent Feature. Link to an existing Feature or create one." |
| Story/Task | Has a parent Epic | "Story/Task has no parent Epic. Link to an existing Epic or create one." |
| Feature (Backlog+) | Has at least one child Epic | "Feature in Backlog+ has no child Epics. Create delivery Epics." |
| Epic (To Do+) | Has at least one child Story/Task | "Epic in To Do+ has no children. Break it down." |

Query children with `parent = {key} AND status != Closed`.

> Tooling: `references/tooling.md#hierarchy-lookups` — why
> hierarchy lookups prefer the local search path

### Check 4 — Unaddressed comments

Fetch the issue's comments.

> Tooling: `references/tooling.md#comments`

Flag when the most recent comment is a question from someone other than the
assignee, when it contains an action item ("TODO", "action item", "follow up",
"next step"), or when the last comment on an In Progress issue is older than 14
days.

### Check 5 — Relevance and staleness

| Condition | Flag |
|---|---|
| New or Refinement and `updated` > 90 days ago | "Stale in {status} for {N} days. Still relevant?" |
| In Progress and `updated` > 30 days ago | "In Progress but no updates for {N} days. Blocked?" |
| Fix Version is a released version and status != Closed | "Fix version {version} is released but the issue is open." |
| Linked upstream issue is closed, this one is not | "Upstream {link} is closed. Can this close too?" |

For upstream checks, look at issue links and at GitHub URLs in comments and
external links.

### Check 6 — Sprint readiness (input is `sprint`)

Verify each sprint issue meets **Planned**: Story Points set, assignee set,
status To Do / In Progress / Review, component set. Flag anything missing as "not
sprint-ready".

### Check 7 — Feature Exploration readiness

Run this for Features during exploration, pre-release prep, or freeze triage.
This is the full checklist, and it doubles as the agenda for the meeting.

| Check | How to verify | Severity |
|---|---|---|
| Priority set | Business value and urgency reflected | error |
| Team set | The owning scrum team | error |
| Assignee set as Feature Owner | Single point of contact | error |
| Candidate label | Labels include `rhdh-X.Y-candidate` | error — the Feature is invisible to release tracking without it |
| Components set and valid | At least one, validated against `/rhdh-jira-api` | error — components drive Feature Freeze and Code Freeze queries |
| Child Epics exist, one per scrum team | `parent = {key}` returns Epics | error if status ≥ Backlog |
| Each Epic has Team, Epic Owner, Component, Size | Epic Owner sizes their own Epic | error |
| Size set on the Feature | Based on the sizing guide and the aggregate of Epic sizes | error at Refinement+ |
| Cross-team dependencies noted | `Blocks` / `Depend` links to other teams | warning if the Feature spans teams and has none |
| `demo` label decision | Customer-facing Features need a demo | warning |
| `rhdh-testday` label decision | Test-day candidacy | warning |
| Feature Demo link | Required at Release Pending | warning as the Feature approaches Release Pending |
| `needs-pm` / `needs-info` | Open questions for PM or the reporter | informational — these are the exploration agenda |

Two more things the meeting produces, which are recommendations rather than
field checks:

- **Decisions go in comments**, not the description. Document questions, answers,
  and next steps as comments so the description stays structured.
- **Rescope early.** If a Feature will not fit one release, split it, name the
  minimum viable scope for this release, comment on what is deferred and why, and
  move the `rhdh-X.Y-candidate` label if the target release changed.

When exploration is complete, the Feature moves to **Backlog** with all child
Epics created and linked.

If multiple L or XL Epics sit under one Feature, flag it — the Feature scope
probably needs reassessing.

**Freeze-aware filtering.** In feature freeze triage, exclude issues labeled
`quality` from the release query. Continuous improvement work is not subject to
code freeze.

```jql
project = RHDHPLAN AND issuetype = Feature AND labels in ("rhdh-X.Y-candidate") AND labels != "quality" AND status != Closed
```

## Output

Each finding carries the issue key, the check that produced it, a severity of
`error`, `warning`, or `info`, the detail, and whether it can be fixed without
asking. Summarize counts per check.

```markdown
## Refinement Report

Checked: {issues_checked} issues | Findings: {issues_with_findings} issues

### Missing Fields ({count})

| # | Issue | Type | Status | Missing |
|---|-------|------|--------|---------|
| 1 | [RHIDP-1234](<url>) | Epic | New | Component, Size |

### Possible Duplicates ({count})

| # | Issue | Possibly duplicates | Overlap |
|---|-------|--------------------|---------|
| 1 | [RHIDP-1234](<url>) | [RHIDP-1100](<url>) | 72% |

### Hierarchy Gaps ({count})

| # | Issue | Type | Gap |
|---|-------|------|-----|
| 1 | [RHIDP-1234](<url>) | Epic | No parent Feature |

### Unaddressed Comments ({count})

| # | Issue | Last comment | By | Days ago |
|---|-------|--------------|----|----------|

### Stale Issues ({count})

| # | Issue | Status | Last updated | Flag |
|---|-------|--------|-------------|------|

### Sprint Not Ready ({count})

| # | Issue | Missing for sprint |
|---|-------|--------------------|

### Feature Exploration ({count})

| # | Feature | Missing | Severity |
|---|---------|---------|----------|

### Summary

| Check | Count |
|-------|-------|
```

## Remediation

After presenting the report, ask `Apply changes? [y/N/edit]`. **y** applies the
uncontroversial fixes and prompts for each of the rest. **N** is report-only.
**edit** steps through every change individually.

For every remediation that includes a Jira comment, compose the complete set of
comment bodies first, then invoke `/prose-editing` once on that set in the
**flavored** register. Preserve issue keys, resolutions, links, and quoted
rationales. The write adapter must not edit them again.

Whatever survives the selection is an external write. After every comment body
is final, invoke `/mutation-gate` once and follow it, with one row per issue key
and the edited bodies included in the plan.

**Applied without individual prompts:**

- Setting Priority to the parent's priority when the child reads "Undefined".
- Adding a missing Component when the parent Epic has exactly one.

**Always needs the user:**

- Setting Size or Story Points — these need estimation, not inference.
- Linking to a parent Feature or Epic — needs a choice among candidates.
- Marking as duplicate — add a comment linking the original and set resolution to
  `Duplicate`.
- Closing stale issues — needs relevance confirmation, and **always** a comment
  with the rationale ("Closing as stale — no activity for 90 days, no longer on
  the roadmap") plus a resolution (`Won't Do`, `Duplicate`, `Done`). A closed
  issue with no resolution and no comment loses the decision trail entirely.
  `/rhdh-jira-update` applies the same rule when it closes an issue.

Writes follow the adapter order in `/rhdh-jira-api` — the local CLI for
anything it supports, the authenticated host adapter for the rest.

> Tooling: `references/tooling.md#writes`

## Error handling

| Error | Action |
|---|---|
| `issueSearchStable` returns errors | Fall back to the paginated local search and say the beta endpoint failed. REST search is not an option. |
| Comment fetch fails (403) | Skip Check 4 for that issue and note "comments not accessible". |
| GraphQL rate limit (429) | Wait 5 seconds, retry once, then report partial results. |
| JQL returns 0 results | "No issues match. Check the JQL or the team/sprint filter." |
| Issue type not recognized | Skip the exit-criteria check and say so. |

## Caveats

1. **Duplicate detection is keyword-based.** It catches obvious duplicates and
   misses semantically similar issues worded differently. When in doubt, say
   "possibly related", not "duplicate".
2. **Comment analysis is heuristic.** Detecting questions by looking for `?` has
   false positives — rhetorical questions, URLs with query strings. Treat it as a
   signal, not a verdict.
3. **Team may need the host adapter.** Read the Team custom field with all
   fields requested first; fall back to the host adapter when it stays absent.
4. **Exit criteria evolve.** They live in `/rhdh-jira-api`. If the process
   changes, that is the file to update.
5. **Triage is automated separately.** An AI CronJob sets Component, Team, and
   Priority on new issues. This check complements it — it validates deeper
   readiness, not initial routing.
6. **Doc Epic automation is a UI action.** Setting the `Documentation` component
   enables **Feature → More → Create Doc EPIC from RHDHPlan** in the Jira UI.
   Prompt the user to run it; an agent cannot. If it is unavailable, coordinate
   with the Docs team directly.
