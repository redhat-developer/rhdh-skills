---
name: rhdh-jira-create
description: >-
  Opens new work in RHDH Jira and decides what kind of work it is — Feature or
  Feature Request in RHDHPLAN, Epic, Story, Task, Spike or Vulnerability in
  RHIDP, Bug in RHDHBUGS, support conversation in RHDHSUPP — then interviews,
  drafts, and creates it with the right fields and parent link. Use for "file a
  ticket", "create a feature", "open an epic for this", "raise a bug", "log a
  spike", "we should track this in Jira", or turning an RHDHSUPP support case
  into an RHDHBUGS defect or an RHDHPLAN feature request. Picking the issue type
  is this skill's job, not the caller's. Editing or transitioning an issue that
  already exists, such as RHIDP-1234, is not creation.
compatibility: "acli on PATH with a Jira session; Python 3.9+ and uv. Requires the external grilling skill — creation is blocked without it."
---

# Create RHDH Jira work

One skill for "this should be a ticket". It decides the issue type and project,
runs the interview, drafts from the RHDH template, and creates the issue.

A caller who says "file this in Jira" almost never knows whether they want a
Feature, an Epic, or a Story. Deciding that is this skill's job. Getting it wrong
writes the wrong issue type into a public project, so the decision happens up
front and out loud, and the user confirms it before anything is created.

## Route

Load `workflows/create-issue.md`. One workflow covers every level of the
hierarchy — the type decision is its first real step, and the steps after it
converge.

Add `references/support-intake.md` when the work originates from a support case:
an RHDHSUPP conversation, a customer escalation, an SLA question, or a request to
turn a case into a defect or a feature request.

## Grilling is a hard gate

Creation requires the external `grilling` skill. It is not bundled with this
pack. If the host cannot invoke it by name, stop before creating anything, say
that creation is gated on `grilling`, and name `/setup-rhdh-skills install`.
Never probe host skill directories, install it yourself, or improvise a
substitute interview.

`/rhdh-jira-authoring` carries the RHDH half of the interview — the challenge
matrix, field inference, sizing, and templates. Invoke it by name.

## Every create is an external write

Invoke `/mutation-gate` and follow it before any `acli` command that
creates, links, comments, or edits. One create is rarely one operation — the
create, the field update `create` could not carry, the parent link, and the
comment go into the same stated set so a single approval covers them.

Afterwards, read the issue back. A create that succeeded followed by a field
update that silently failed is a half-created issue, not a success.

**Private issues are not "set after create."** On public projects (RHIDP,
RHDHPLAN, RHDHBUGS), put `security` on the create payload
(`/rhdh-jira-api` — Private issues). RHDHSUPP is project-private; level optional.
Never create-then-restrict. If `security` cannot be set when required, stop.

## Boundary with the neighbouring skills

- Judging whether an existing issue is ready is `/rhdh-jira-refine`.
- Changing status, assignee, comments, or links on a known key is `/rhdh-jira-update`.
- `acli` syntax, field IDs, the component catalog, and workflow exit criteria are
  `/rhdh-jira-api`.
- Templates, the challenge matrix, sizing, duplicate detection, and decomposition
  rules are `/rhdh-jira-authoring`.
- Creating a PR and linking it back to an issue is `/rhdh-jira-link`.

## Completion

Complete when the user confirmed the issue type before creation, the duplicate
check ran and its result was reported, the grilling interview happened, and every
created key has been read back and reported with its resulting status, parent
link, and the fields that were actually set. Report any field the API refused as
unset, never as set. A decomposition is complete only when the user approved the
batch table before any child was created, and every child in that table has
either a key or a stated reason it was skipped.
