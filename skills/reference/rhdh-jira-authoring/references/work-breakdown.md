# Work Breakdown

Vocabulary and rules for turning aligned conversation into Jira work under RHDH's Feature → Epic → Story/Task hierarchy.

Load when decomposing a Feature into Epics, an Epic into Stories/Tasks, or when drafting create descriptions from conversation.

## Synthesize, then grill gaps

Once the conversation (and grilling) has aligned the problem, **synthesize** the draft from what you already know. Do not re-interview settled topics.

- Prefer filling template sections from context first, then ask only for true gaps.
- When chained (Feature → Epic → Issue), carry parent scope/AC down; narrow the grill to *this* node's delivery slice.
- Capture **implementation decisions** and **testing decisions** that already landed in the chat as comments (or AC bullets) — don't leave them only in the agent's memory.
- Keep RHDH templates (Feature Exploration, Epic, Story/Task/Bug). Do not replace them with a generic PRD template.

## Tracer bullets (vertical slices)

Prefer **tracer bullet** children — narrow but **complete** paths that are demoable or verifiable on their own — over horizontal layers ("backend tickets" / "frontend tickets" / "docs-only" as a fake slice of the same behaviour).

| Prefer | Avoid |
|--------|--------|
| "User can import a catalog entity via OCI and see it in the catalog" (Story) | "Add OCI API" + "Add UI" + "Add tests" as three tickets for one behaviour |
| Epic that delivers one team's end-to-end outcome for the Feature | Epic that is only a tech layer with no user-visible or ops-visible outcome |
| Prefactor / spike first when unknowns block slicing | Mixing investigation and delivery in one oversized Story |

**RHDH Feature → Epic exception:** RHDH still usually creates Epics **per team** (Eng, Doc, …). Keep that process. Within a team's Epic → Stories/Tasks, apply tracer-bullet slicing. Across Epics, record **blocking edges** (which Epic must land before another can start).

**Wide mechanical refactors** (rename, shared type change with huge blast radius) are the exception to vertical slicing — sequence as expand → migrate batches → contract, each as its own ticket/Epic AC with explicit blockers.

## Blocking edges

Every proposed child should declare what **blocks** it:

- **None — can start immediately**, or
- Explicit parent/sibling keys or provisional titles ("blocked by Epic #1 SDK")

Publish (create) in dependency order when practical: blockers first, so links and sprint planning reflect the real frontier.

Use Jira links (`Blocks` / `is blocked by`) or clear Dependency section text when native linking is awkward cross-project.

## Quiz before create

Before creating a batch of children, present a numbered breakdown and ask:

1. Granularity — too coarse / too fine?
2. Blocking edges — correct?
3. Merge or split any items?
4. (Feature → Epics) Overlap and consolidation — the batch review in `/rhdh-jira-create`

Do not create the batch until the user approves the breakdown.

## Completion criteria (decomposition)

Decomposition is done when:

- Every child is a tracer bullet (or an explicit wide-refactor / spike exception)
- Every child has blocking edges stated
- User approved the batch table
- The customer-identity and `RHDH-Customer` label rules from `/rhdh-jira-context` still hold on every
  new issue
