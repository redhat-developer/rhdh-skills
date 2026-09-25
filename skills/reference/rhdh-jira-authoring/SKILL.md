---
name: rhdh-jira-authoring
description: >-
  Supplies the craft of writing good RHDH Jira work in RHIDP, RHDHPLAN,
  RHDHBUGS, and RHDHSUPP: the Feature, Epic, Story, Task, and Bug description
  templates with filled examples, the RHDH challenge matrix that stress-tests
  scope, sizing, acceptance criteria, and Epic independence, the T-shirt and
  Fibonacci sizing scales, keyword duplicate detection, and the tracer-bullet
  rules for breaking a Feature into Epics or an Epic into Stories. Use when
  drafting or judging the text and shape of an issue such as RHIDP-1234 — how
  big is this, is this AC testable, should this be one Epic or three, does this
  already exist. Prose and estimation craft only; it runs no Jira command.
compatibility: "No tools required. The external grilling skill is a prerequisite for the creation interview it feeds."
---

# RHDH Jira authoring

The material that decides whether an issue is worth reading six months later.
Two skills use it — `/rhdh-jira-create` while drafting and `/rhdh-jira-refine`
while auditing — so it lives here rather than in either of them.

This skill produces text and judgements. It never runs a Jira command and never
performs a write.

## Route by need

| Need | Load |
|---|---|
| How to challenge a draft; how to infer RHDH Jira fields from conversation | [references/grill.md](references/grill.md) |
| T-shirt sizes, story points, RHDHSUPP effort points, sizing challenges | [references/sizing.md](references/sizing.md) |
| Does this already exist? | [references/duplicates.md](references/duplicates.md) |
| Splitting a Feature into Epics or an Epic into Stories | [references/work-breakdown.md](references/work-breakdown.md) |

## Templates and examples

Description templates are Jira wiki markup. Each has a filled example next to it
for tone and detail calibration — read the example before drafting, because the
templates alone underspecify how much detail an RHDH reviewer expects.

| Issue type | Usual project | Template | Example |
|---|---|---|---|
| Feature | RHDHPLAN | `assets/templates/feature.txt` | `assets/examples/feature-example.txt` |
| Epic | RHIDP | `assets/templates/epic.txt` | `assets/examples/epic-example.txt` |
| Story | RHIDP | `assets/templates/story.txt` | `assets/examples/story-example.txt` |
| Task | RHIDP | `assets/templates/task.txt` | `assets/examples/task-example.txt` |
| Bug | RHDHBUGS | `assets/templates/bug.txt` | `assets/examples/bug-example.txt` |

Spikes use the Task template with a `SPIKE:` prefix on the summary and a
time-boxed story point estimate. A Vulnerability uses the Story template and
always carries the Security component. Feature Request and Outcome templates
exist in RHDHPLAN; this skill does not carry them, so draft those from the
project's own template in the Jira UI.

Sub-tasks are children of an existing issue, never standalone.

A filled template is wiki markup, and Jira Cloud will render wiki markup or
Markdown as literal characters (`h1.`, `*text*`, `# Heading`) when those bytes
are stuffed into ADF text nodes instead of converted. `/rhdh-jira-api` owns
wiki→ADF conversion; do not hand-build ADF from Markdown paragraphs.

## Boundary with the neighbouring skills

- Running the interview and creating the issue is `/rhdh-jira-create`.
- Auditing issues that already exist is `/rhdh-jira-refine`.
- Field IDs, the component catalog, JQL, `acli` syntax, and workflow exit
  criteria are `/rhdh-jira-api`.
- The general interview cadence is the external `grilling` skill, invoked by
  name. What is here is only the RHDH-specific half.

## Completion

When a person invokes this skill directly and the result is a complete draft
for them to use, invoke `/prose-editing` once on the filled summary and
description in the **flavored** register before returning it. Preserve Jira
wiki markup, template headings, field values, issue keys, links, and acceptance
criteria. When `/rhdh-jira-create` or `/rhdh-jira-refine` calls this skill, hand
back the authoring result without editing; the final caller owns the single
prose pass.

Complete when the draft names its template and its issue type, every section the
template asks for is either filled or explicitly marked out of scope, every
applicable challenge in the matrix has been applied or skipped with a stated
reason, and the proposed size cites the scale it came from rather than a feeling.
A duplicate check reports the query it ran and the row count it saw. Nothing here
is complete on the strength of a draft the user has not seen.
