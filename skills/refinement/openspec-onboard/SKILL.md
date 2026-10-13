---
name: openspec-onboard
description: >-
  Guided, narrated walkthrough of one complete OpenSpec cycle — explore,
  create a change, build proposal then sibling specs/design then tasks,
  implement, archive — using a real small task in the user's own codebase.
  Use for "walk me through OpenSpec", "teach me the OpenSpec workflow",
  "onboard me to OpenSpec", or a first-time user asking what OpenSpec even
  is. Does real work, not a simulation; teaches by doing rather than
  lecturing.
compatibility: "Requires the openspec CLI on PATH; stops early with a clear message if it is not installed. The external grilling skill is optional — used only if a genuine design uncertainty comes up."
---

# Onboard to OpenSpec

Teach the full OpenSpec cycle by actually running it, once, on a small real
task — narrating each step as you go rather than lecturing first and doing
later. Prefer invoking the real `/openspec-*` skills by name so the user
learns the same triggers they will use later.

## Preflight

Check the CLI is installed (`openspec --version`, or the PowerShell
equivalent). If not installed, say so and stop: "OpenSpec CLI is not
installed. Install it first, then come back to onboarding."

Check whether `openspec/config.yaml` and `openspec/schemas/rhdh-spec-driven/`
already exist. Only if either is missing, invoke `/rhdh-spec-driven-schema`
and run its project-install step before creating a change.

## Phase 1: Welcome

State what will happen: pick a small real task, explore it briefly, scaffold a
change, draft proposal, then specs and design as siblings (either order; both
depend only on proposal), then tasks, implement, archive — about 15-20
minutes. Then move to task selection.

## Phase 2: Task selection

Scan the codebase for small opportunities: `TODO`/`FIXME`/`HACK`/`XXX`
comments, swallowed errors or risky operations without try/catch, functions
missing tests, `any`/`as any` in TypeScript, stray `console.log`/`debugger`,
user input handlers missing validation. Check recent activity with
`git log --oneline -10`. Present 3-4 specific, concretely-scoped suggestions
(location, scope estimate, why it's good) plus a "something else?" option; let
the user pick or describe their own. If nothing turns up, ask directly what
small thing they've been meaning to fix.

**Scope guardrail:** if the chosen task is a major feature or multi-day work,
say so and offer to slice it smaller, pick something else, or do it anyway —
a soft guardrail; respect the user's choice if they insist on the larger
scope.

## Phase 3: Explore demo

Briefly demonstrate explore mode by invoking `/openspec-explore` on the
chosen task: 1-2 minutes reading the relevant file(s), an ASCII diagram if it
helps, a short note of considerations. Explain that this is what
`/openspec-explore` is for — thinking before implementing, usable any time.
**Pause** for acknowledgment before creating the change.

## Phase 4: Create the change

Explain a "change" is a container for the work, living at
`openspec/changes/<name>/`, holding proposal, specs, design, and tasks.
Invoke `/openspec-new-change` for the derived kebab-case name — it scaffolds
the folder and shows the first artifact template, then stops. Show the
resulting folder structure.

## Phase 5: Proposal

Explain the proposal captures why and what, at a high level. Invoke
`/openspec-continue-change` so it drafts and writes exactly the next ready
artifact (`proposal`). **Pause** for approval or feedback before moving on;
if the user wants edits, revise `proposal.md` and continue.

## Phase 6: Specs and design (siblings)

Explain that after proposal, **specs** and **design** are both ready: each
depends only on proposal, not on each other, so either order (or parallel
drafting in other workflows) is valid. For this walkthrough, invoke
`/openspec-continue-change` twice — once for each — narrating which sibling
you are writing and why. Typical teaching order is specs then design; if the
user prefers design first, do that instead.

**Optional: resolve open questions with grilling.** If the design draft left
a real trade-off unresolved — several plausible approaches, an ambiguous
Decision, an open question you can't confidently answer for the user — offer
to run the external `/grilling` skill on it before moving to tasks: "This
design has an open question about `<X>`. Want to run a quick grilling pass to
pin it down before we break it into tasks?" This is a soft offer, not a gate
— if the user declines, or `/grilling` is not installed, say so (naming
`/setup-rhdh-skills install` as the next step) and move on with the design as
drafted. If the user accepts, invoke `/grilling`, fold the resolved answers
back into `design.md`'s Decisions, then continue. Skip this entirely when the
design has no real open question — most small onboarding tasks won't.

## Phase 7: Tasks

Explain tasks break the work into checkboxes that drive implementation, and
that tasks require **both** specs and design. Invoke
`/openspec-continue-change` to write `tasks.md`. **Pause** for confirmation
the user is ready to implement.

## Phase 8: Apply (implementation)

Invoke `/openspec-apply-change` for the change. Keep narration light — teach
without over-explaining every line. After all tasks, confirm completion and
move to archiving.

## Phase 9: Archive

Explain archiving moves the change to
`openspec/changes/archive/YYYY-MM-DD-<name>/` and becomes part of the
project's decision history. Invoke `/openspec-archive-change` for `<name>`
and show the archive location.

## Phase 10: Recap and next steps

Recap the cycle: Explore → New (scaffold) → Continue (proposal) → Continue
(specs | design, either order) → Continue (tasks) → Apply → Archive. Show the
command reference:

| Command | What it does |
|---|---|
| `/openspec-explore` | Think through problems before/during work |
| `/openspec-new-change` | Scaffold a change directory; stop before drafting |
| `/openspec-continue-change` | Create exactly the next ready artifact |
| `/openspec-ff-change` | Generate every remaining artifact in one pass |
| `/openspec-apply-change` | Implement tasks from a change |
| `/openspec-archive-change` | Archive a completed change |
| `/openspec-audit-change` | Audit artifacts for cross-artifact consistency (pre-implementation) |
| `/openspec-verify-change` | Verify implementation matches artifacts (post-implementation) |
| `/grilling` (external, optional) | Resolve a genuinely open design question before moving to tasks |

Close with: "Try `/openspec-ff-change` on something you actually want to build."

## Graceful exit handling

**User wants to stop mid-way:** reassure the work is saved at
`openspec/changes/<name>/`, and that `/openspec-continue-change` or
`/openspec-apply-change` picks it back up later. Exit without pressure.

**User just wants the command reference:** show the table above (same
content) and stop the tutorial there.

## Guardrails

- Follow EXPLAIN -> DO -> SHOW -> PAUSE at key transitions (after explore,
  after the proposal draft, after tasks, after archive).
- Keep narration light during implementation — teach without lecturing.
- Don't skip phases even for a tiny change — the goal is teaching the
  rhythm, not speed.
- Do not teach a linear `proposal -> specs -> design -> tasks` dependency —
  specs and design are siblings.
- Pause for acknowledgment at marked points; don't over-pause elsewhere.
- Handle exits gracefully — never pressure the user to continue.
- Use a real codebase task — never simulate or fabricate one.
- Guide toward a smaller scope gently; respect the user's final choice.

## Completion

Complete when the user has either finished a full real cycle through archive,
or exited gracefully at a marked pause point with their change intact and
saved — and, either way, can name which `/openspec-*` skill to reach for next.
