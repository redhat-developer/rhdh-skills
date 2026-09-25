# Create a Jira issue

One spine for every level of the RHDH hierarchy. Steps 0 and 1 decide *what* to
create; steps 2 onward are the same shape regardless of the answer, with the
type-specific detail called out inline.

## Step 0 — Prerequisites

Invoke `grilling` by name. If it is unavailable, stop here and follow the hard
gate in SKILL.md.

Load `/rhdh-jira-authoring` for the challenge matrix, sizing scales, and
templates. Load `/rhdh-jira-api` for field IDs, the component catalog, and `acli`
syntax. Do not read either skill's files by path.

## Step 1 — Decide the type and project

This is the step that makes the difference between a useful ticket and a
mis-filed one. Read the conversation and pick a row:

| What the conversation describes | Create | Project |
|---|---|---|
| A capability the product lacks, spanning teams or a whole release | **Feature** | RHDHPLAN |
| A customer asked for a capability through a support case | **Feature Request** | RHDHPLAN |
| One team's delivery slice of an existing or proposed Feature | **Epic** | RHIDP |
| User-facing behavior change, UI, API contract | **Story** | RHIDP |
| Internal engineering work: CI, refactor, tooling, tests, infra | **Task** | RHIDP |
| Something is broken — regression, defect, unexpected behavior | **Bug** | RHDHBUGS |
| A live engineering ↔ support conversation about a customer case | **Bug** | RHDHSUPP |
| CVE, vulnerability, security advisory | **Vulnerability** | RHIDP, Security component |
| "Investigate", "research", "spike", "explore", "POC", unknown scope | **Task**, summary prefixed `SPIKE:` | RHIDP |

Then confirm out loud: "This sounds like a {type} in {project}. Correct?"

Disambiguate when the signals are mixed:

- **Feature vs Epic** — does this need work from more than one scrum team, or
  span a release? Feature. Is it one team's slice? Epic.
- **Epic vs Story** — could this be acceptance criteria on something that already
  exists? Then it is not an Epic. See Challenge epic independence in
  `/rhdh-jira-authoring`.
- **Story vs Task** — is this user-facing (Story) or internal engineering work
  (Task)?
- **Bug project** — from a support case? RHDHSUPP for the conversation, RHDHBUGS
  for the defect itself. A product defect found independently goes straight to
  RHDHBUGS. **Never create a Bug in RHIDP.**
- **Vulnerability** — a CVE or security advisory is a Vulnerability in RHIDP with
  the Security component, not a Bug.

If the work came out of a support case at all, load
`references/support-intake.md` before continuing — it decides which project
receives what, and it carries the customer-identity rules that RHDHBUGS and
RHDHPLAN being public makes non-negotiable.

**Bugs and Spikes have entry requirements.** A Spike without a time-box does not
get created: ask "Spikes require a time-box. How many story points?" and wait.

## Step 2 — Establish context

Two entry modes, and they change how much you ask:

- **Chained** — created as a child during a decomposition. The parent's scope,
  acceptance criteria, and customer considerations are already settled. Narrow
  the interview to this node's own delivery slice. Do not re-ask settled
  parent-level topics.
- **Standalone** — full interview. Ask whether there is a parent: "Is this part
  of an existing Feature/Epic? [key / no]"

### Sibling awareness (Epic under a Feature only)

Before drafting an Epic under a parent Feature, list what is already there:

```bash
jql: "parent = FEATURE-KEY AND issuetype = Epic AND status != Closed"
```

Present the siblings with summaries and sizes, then ask which the new Epic
relates to and whether it overlaps any. Carry that list into the interview — the
Challenge epic independence and Challenge sibling overlap behaviors in
`/rhdh-jira-authoring` need it. If the proposed Epic overlaps a sibling,
recommend adding scope as acceptance criteria on the sibling rather than creating
a new Epic.

Skip this for standalone Epics and for every other type.

## Step 3 — Draft from the template

Load the template and its filled example for the chosen type from
`/rhdh-jira-authoring`. Read the example — the templates alone underspecify how
much detail an RHDH reviewer expects.

Apply **synthesize, then grill gaps** from `/rhdh-jira-authoring`: fill from the
conversation first, and do not re-interview settled topics. Fold implementation
and testing decisions that already landed in the chat into acceptance criteria or
Out of Scope, or note them for a comment after creation, so they are not lost.

Keep the RHDH template. Do not substitute a generic PRD.

When drafting anything customer-derived, check it against the customer-identity
rules in `/rhdh-jira-api`: support case key, persona, and use case only — no
customer names.

Present the draft: "Based on our conversation, here's what I have. Review and
tell me what's missing or wrong."

## Step 4 — Fill gaps and challenge

Invoke `grilling` once for Fill Gaps and Challenge. Do not re-implement its
cadence. Then apply the RHDH challenge matrix from `/rhdh-jira-authoring`, which
says which behaviors apply to which issue type.

Ask targeted questions only for the sections the draft could not fill.

**Feature** — Feature Overview (elevator pitch), Goals and which persona
benefits, Requirements and acceptance criteria including non-functional ones, Out
of Scope, Customer Considerations, Documentation Considerations, and upstream
Backstage engagement.

**Epic, chained** — what does *this team's* delivery achieve within the parent
Feature; internal and external dependencies; team-specific acceptance criteria
(DEV, QE, DOC).

**Epic, standalone** — EPIC Goal, Background and origin, why it matters, User
Scenarios, dependencies, full acceptance criteria.

**Story** — the user story ("As a \<persona\> trying to \<action\> I want
\<outcome\>"), background, out of scope, technical approach, dependencies
including QE and Doc impact, and acceptance criteria with edge cases and a
minimum test list.

**Task** — what needs to happen and why, background if not obvious, dependencies
and blockers, and what "done" looks like.

**Bug** — description of the problem, prerequisites (setup, versions, operators),
numbered steps to reproduce, actual results, expected results, reproducibility
(Always / Intermittent / Only Once), build details, and any logs or screenshots.

**Spike** — what is being investigated, what decision depends on the answer, the
time-box in story points, and what deliverable closes it (doc, ADR, prototype,
go/no-go).

**Vulnerability** — follow the Story questions and always set the Security
component.

Skip anything the draft already answered well.

## Step 5 — Infer the fields

Do not make the user fill a form. Infer values from the conversation and present
them all at once for confirmation, following Field Inference in
`/rhdh-jira-authoring`.

By type, the fields that matter most:

| Type | Key fields |
|---|---|
| Feature | Priority, Team, Size (T-shirt), Assignee as Feature Owner, Components, Labels |
| Epic | Team, Priority, Size (T-shirt), Component, Assignee as Epic Owner |
| Story / Task / Spike | Priority, Component, Assignee, Story Points (required for Spikes) |
| Bug (RHDHBUGS) | Priority, Component, Assignee, **Affects Version** (required at create — see `/rhdh-jira-api`) |

When chained, inherit Priority, Team, and Component from the parent unless the
conversation contradicts them.

**Components** are required on an Epic at New status and affect Feature Freeze
and Code Freeze queries, so they are not a detail to skip. Infer them, validate
them against the component catalog in `/rhdh-jira-api`, and confirm with the user
— never auto-set a component.

**Affects Version** (RHDHBUGS Bugs): required at create. Infer from Build Details /
prerequisites, confirm with the user, and put it on the create payload (Step 8).
Authoritative constraint and payload field name: `/rhdh-jira-api` (`fields.md`,
Bug workflow).

**Labels — ask about each during the interview:**

| Label | Question |
|---|---|
| `demo` | Does this need a customer-facing demo? |
| `rhdh-testday` | Should this be tested during release test day? |
| `rhdh-X.Y-candidate` | Which release does this target? |
| `stretch` | Is this a stretch goal? |
| `RHDH-Customer` | Did this come from a support case or customer engagement? |

Apply exactly one `RHDH-Customer` label — never also `rhdh-customer`, because
Jira label search is case-insensitive and the two spellings collide.

**Documentation.** If the work involves documentation, set the `Documentation`
component. After creating a Feature, prompt the user to run the Jira UI action
**Feature → More → Create Doc EPIC from RHDHPlan** — an agent cannot.

**Cross-team dependencies.** Ask whether other scrum teams are affected. If so,
note them; they become Epics in Step 10.

## Step 6 — Review before creating

Invoke `/prose-editing` once on the final summary and filled description in the
**flavored** register. `/rhdh-jira-authoring` supplies the template and challenge
rules but does not edit this caller's draft. Preserve template headings, field
values, acceptance-criteria checkboxes, and customer-identity restrictions.

Render the filled template and the inferred fields as a temporary markdown file
and hand it to the user. Use a portable temp path (`$TMPDIR`, `%TEMP%`, or Python
`tempfile`):

```bash
REVIEW=$(mktemp "${TMPDIR:-/tmp}/jira-review.XXXXXX.md")  # Windows: %TEMP% or tempfile
cat > "$REVIEW" << 'EOF'
## {Type}: {summary}

### Description
{filled template content}

### Fields
- **Project**: {project}
- **Priority**: {value} — {rationale}
- **Team**: {value}
- **Size / Story Points**: {value} — {rationale}
- **Component**: {value}
- **Assignee**: {value}
- **Labels**: {values}
- **Affects Version**: {value} — RHDHBUGS Bugs only; required at create (see `/rhdh-jira-api`)
EOF
```

Present it: "Review before creating. Edit the file or tell me what to change.
[approve / edit / cancel]"

## Step 7 — Duplicate check

Run the pre-creation check from `/rhdh-jira-authoring` using the proposed
summary, scoped to the target project and type. If a likely duplicate turns up,
present it and ask: "This may already exist as {KEY}: {summary}. Use the existing
issue instead?"

**For a Feature, also look for the Feature Request it may satisfy:**

```bash
jql: "project = RHDHPLAN AND issuetype = 'Feature Request' AND status = Accepted AND summary ~ \"KEYWORD1 KEYWORD2\""
```

If one matches, offer to add a `Related` link after creation.

## Step 8 — Create

Re-check the customer-identity and label rules from Validate before creating in
`/rhdh-jira-authoring` one last time. Strip customer names from the summary and
description if any survived; confirm at most one `RHDH-Customer` label.

Write the filled template to a temp file, then invoke `/rhdh-jira-api` to convert
it to ADF and hand back the JSON file path (`jira-wiki-to-adf.py`). Jira Cloud
renders raw wiki markup and Markdown as literal characters when stuffed into ADF
text nodes, so an unconverted description ships broken. Always use that helper —
do not hand-split Markdown or wiki into ADF paragraphs, and do not reach into
`/rhdh-jira-api`'s directory for the script; invoke the skill so it runs the
converter. When creating through the Atlassian MCP instead of `acli`, pass
`contentFormat: markdown` and skip the wiki→ADF step.

`create` does **not** accept `--priority`, `--component`, `--yes`, or
`--version` / Affects Version flags; passing unknown flags fails. For most
types, create with `--description-file` (ADF from `/rhdh-jira-api`), then set
the rest. **Exception — RHDHBUGS Bug:** Affects Version must be on the create
call. Use a single `--from-json` file that embeds both `versions` and the ADF
`description` — do **not** also pass `--description-file` on that create.
Scaffold with `acli jira workitem create --generate-json`, or create through
the Atlassian MCP with Affects Version / `versions` set. Details:
`/rhdh-jira-api` (`fields.md`, `acli-commands.md`).

```bash
# Feature
acli jira workitem create --project RHDHPLAN --type Feature \
  --summary "Feature summary" --description-file "$ISSUE_ADF" \
  --assignee "ACCOUNT_ID" --label "rhdh-2.1-candidate"

# Epic
acli jira workitem create --project RHIDP --type Epic \
  --summary "Epic summary" --description-file "$ISSUE_ADF" --assignee "ACCOUNT_ID"

# Story
acli jira workitem create --project RHIDP --type Story \
  --summary "Story summary" --description-file "$ISSUE_ADF" --assignee "ACCOUNT_ID"

# Bug — Affects Version + ADF description inside one JSON file
acli jira workitem create --from-json "$BUG_CREATE_JSON"

# Spike
acli jira workitem create --project RHIDP --type Task \
  --summary "SPIKE: Research multi-source catalog merging" \
  --description-file "$ISSUE_ADF" --assignee "ACCOUNT_ID"
```

Minimal RHDHBUGS Bug `--from-json` shape (ADF `description` from
`/rhdh-jira-api` wiki→ADF conversion; start from `--generate-json` if unsure):

```json
{
  "projectKey": "RHDHBUGS",
  "type": "Bug",
  "summary": "Bug summary",
  "description": { "type": "doc", "version": 1, "content": [] },
  "additionalAttributes": {
    "versions": [{ "name": "1.10.0" }],
    "components": [{ "name": "Actions" }]
  }
}
```

Then set the fields `create` could not, in one update through the authenticated
host adapter. Show the payload for approval alongside the create command:

```json
{
  "fields": {
    "priority": {"name": "Major"},
    "components": [{"name": "Catalog"}],
    "customfield_10795": {"value": "M"},
    "customfield_10028": 5
  }
}
```

**Parent links differ by direction, and getting this wrong produces false "no
child Epics" reports later.** A same-project Story or Task under an RHIDP Epic
uses the native field:

```json
{"fields": {"parent": {"key": "RHIDP-XXX"}}}
```

A cross-project Epic under an RHDHPLAN Feature uses the Parent Link
(`customfield_10018`) or `parent.key` — never `issuelinks`, which returns nothing
for a cross-project parent:

```json
{"fields": {"customfield_10018": "RHDHPLAN-XXX"}}
```

Team is one of the fields `acli` cannot set at all. Follow the adapter order and
the Team payload in `/rhdh-jira-api`.

## Step 9 — Comments

Follow the comment suggestions behavior in `/rhdh-jira-authoring`: proactively
offer the decision trail, elaboration, and abandoned approaches as comments, so
the reasoning survives outside the description.

After choosing the comment set, invoke `/prose-editing` once on the complete set
of proposed comment bodies in the **flavored** register. Use those edited bodies
for the preview and write gate; the Jira adapter must not edit them again.

```bash
acli jira workitem comment create --key RHIDP-XXX --body "comment text"
```

Customer-identifying detail goes only in a restricted-visibility comment, and
only when the project supports security levels.

## Step 10 — Decompose

Leaf types stop here. A Story, Task, Bug, or Spike is not decomposed further — if
the scope is too large, split it into sibling issues or promote it to an Epic.

**After a Feature:** "Break this Feature into Epics? The RHDH process typically
creates Epics per team (Eng, QE, Doc). [y/N]"

Load `/rhdh-jira-authoring` for the breakdown rules, then:

1. Ask which teams are involved. Default suggestion: Eng and Doc, since QE is
   often covered inside the Eng Epic.
2. Propose the whole batch **before creating any of it**, as a table with
   blocking edges and a team-scoped outcome per Epic — not a horizontal tech
   layer.
3. Run the batch review below.
4. For each approved Epic, re-enter this workflow at Step 2 in chained mode.
   The Feature's scope, acceptance criteria, and customer considerations are
   settled; the Epic interview narrows to that team's delivery slice,
   dependencies, and team-specific acceptance criteria.
5. Link each Epic to the parent Feature with the cross-project Parent Link from
   Step 8.

### Batch review (Feature → Epics)

| # | Epic summary | Size | Blocked by | Overlaps with |
|---|---|---|---|---|
| 1 | Entity-Provider SDK | M | None | — |
| 2 | OCI Skill Registry | S | #1 (SDK) | — |
| 3 | Annotation Scheme | XS | #1 (SDK) | #1 (same package) |

- **Overlap check** — would any two of these naturally ship in the same PR or
  package? Flag the pair.
- **Count challenge** — more than five Epics under one Feature is a signal.
  "Are any of these implementation details that should be acceptance criteria on
  a broader Epic?"
- **Consolidation check** — several XS or S Epics targeting the same technical
  domain usually want merging.

The user merges, drops, or approves before any Epic is created.

**After an Epic:** "Break this Epic into Stories/Tasks? [y/N]"

1. Draft **tracer bullet** slices — vertical, demoable or verifiable on their
   own — not horizontal backend/frontend/docs splits of one behavior. When
   unknowns block slicing, propose a prefactor or spike first.
2. Present a numbered batch with **Blocked by** per slice and quiz granularity
   and edges before creating anything.
3. For each approved slice, re-enter this workflow at Step 2 in chained mode with
   the type inferred per slice — Story if user-facing, Task if internal.
4. Create in dependency order when practical, blockers first, and set `Blocks`
   links where the edges are real.

## Error handling

| Error | Action |
|---|---|
| Target project inaccessible | Stop. The user lacks project access. |
| Type inference ambiguous | Ask the user directly. Do not guess a hierarchy level. |
| `acli create` fails | Retry through the authenticated host adapter in `/rhdh-jira-api`; if the payload changes, get approval again. |
| Field update after create fails | Report it. The issue exists — say which fields are unset. |
| Parent link fails | Report it. The issue exists and can be linked manually. |
| Spike without a time-box | Do not create. Ask for the story points first. |
| Duplicate check finds a match | Present it. If the user confirms it is a duplicate, work the existing issue instead. |

## Caveats

1. **Bugs never go in RHIDP.** RHDHBUGS is public: support case key in the
   summary and description, a single `RHDH-Customer` label, and no
   customer-identifying detail in any unprotected field.
2. **Owner responsibility is real.** A Feature's assignee is the Feature Owner —
   single point of contact, coordinates cross-team dependencies, owns sizing and
   labels. An Epic's assignee is the Epic Owner and is responsible for sizing the
   Epic. Make sure the person named knows.
3. **Candidate labels are load-bearing.** The format is `rhdh-X.Y-candidate`.
   Removing one silently drops a Feature from release tracking, so **do not
   remove a candidate label without PM approval.**
4. **Descriptions stay structured.** Only template sections belong in the
   description. Decision trail, elaboration, abandoned approaches, and
   customer-identifying detail belong in comments.
5. **Rescoping.** If a Feature is too large for one release, suggest splitting
   it, document what is deferred and why as a comment, and adjust the candidate
   label if the target release moves.
6. **Spikes are Tasks.** Identified by the `SPIKE:` prefix, always time-boxed —
   there is no separate Spike issue type.
7. **Done Checklist.** The Story template carries one. Remind the user it is part
   of the definition of done.
8. **After creating a Feature**, it should pass the full Feature Exploration
   checklist in `/rhdh-jira-refine` before it moves to Backlog.
