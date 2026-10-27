---
name: skill-authoring
description: >-
  Creates, audits, and consolidates Agent Skills that follow the Agent Skills
  open standard, and hands back a drafted or repaired skill with the review
  checklist for its branch applied. Use for "create a skill", "draft a
  SKILL.md", "package this expertise as a skill", "why does this skill never
  trigger", "audit this SKILL.md", "improve this skill", or merging overlapping
  skills into fewer deeper modules. Covers frontmatter, descriptions that
  trigger, progressive disclosure, completion criteria, and bundled scripts.
compatibility: "No tools required. Requires an interview skill such as /grilling for the create path."
---

# Skill Authoring

Create predictable Agent Skills through progressive disclosure, strong context
pointers, checkable completion criteria, and single-sourced behavior.

## Principles

- **One skill per trigger phrase.** A skill claims one thing a user would say.
  Two skills that would answer the same utterance are one skill; one skill that
  answers several unrelated utterances is several skills.
- **Split by verb, never by noun.** Verbs route; nouns collide. `create` and
  `refine` are two skills. Feature, Epic, and Story are one skill that infers the
  type, because the user often does not know which they want.
- **Weight the split by what a misroute costs.** Merge where a misroute produces
  a wrong *write*; split where it produces an obvious wrong *answer*. A read-only
  misroute is visible immediately; a wrong mutation is not.
- **A skill needing a disambiguating sub-command is two skills.** If the body
  opens by asking which mode the user wants, the router should have decided.
- Keep every-branch steps in `SKILL.md`; disclose branch-only reference behind
  a pointer that says when to read it.
- Keep references one level deep and independently usable.
- Keep descriptions below 1024 characters and skill bodies below 500 lines.
  The body limit governs `SKILL.md` only — measure the whole directory too, and
  settle it with the question the line count only hints at: **which of these
  vocabularies does a caller have to learn?** One trigger phrase commits the
  caller to one. Two skills in this pack reached 4,029 and 7,784 total lines
  while their `SKILL.md` files stayed comfortably compliant.
- Put deterministic validation and transformation in scripts.
- **Contract, then reference implementation.** Process (verbs with pinned
  inputs, outputs, and postconditions; gates; exit criteria) carries no CLI
  names and no free-form "use whatever tool you have"; exact commands live in
  one `references/tooling.md` sidecar that is the reference implementation any
  other backend must match. See Dual-mode below.

## Duplication

Judge it by layer, not by volume.

**Prompt duplication is forbidden.** When the same instructions, protocol, or
domain rule would appear in two skills: **extract** a reference skill when nothing
owns it, **enforce** the existing interface when a module already does, or
**document** it once when it is a rule rather than a capability. Two callers is
the threshold for extracting; one caller means it belongs inside its owner.

**Code duplication is expected.** Bundled scripts are self-contained so a skill
can be installed alone. Copy the helper rather than reaching across a seam.

A rule the agent needs at *runtime*, in whatever repository it is working in, has
to live in a skill. A repository's own `AGENTS.md`, decision records, and
glossary govern work inside that checkout and do not travel with an installed
skill — so a skill that cites them is broken for everyone who installs it.

## Naming

A name describes its subject. Name by domain then verb, matching the trigger
phrase the skill claims: `<domain>-create`, `<domain>-review`. Sibling skills use
the same word for the same thing.

Ask what the skill is *about*, and let the answer decide the name. A skill about
one product or system takes that product's name; a skill that is genuinely
generic takes a generic name, even when it is published alongside product-specific
ones. A prefix that overstates scope is worse than none — it promises knowledge
the skill does not have.

Names are read by people, in a flat list where the folder is gone. Routing is a
separate problem, solved by the description: keep the literal proper nouns —
project keys, repository names, file names, tool names, an example identifier —
because a literal token is the strongest anchor available.

That anchoring works on presence, so never put a literal in a description in
order to disclaim it. "A key such as ABC-123 is not a sprint" makes the skill a
candidate for exactly the request it is refusing. State the exclusion without the
token: "works on a team and a board, never on a single issue key".

## Dual-mode: contract and reference implementation

A skill that drives CLIs must also run for an agent that has native
integrations (ADLC tools) instead — without handing that agent a free-form
"pick a tool and improvise" step. Separate the layers:

- **Process** — verbs with pinned inputs, outputs, and postconditions; gates;
  exit criteria; sequencing; templates — stays in `SKILL.md`, `workflows/`,
  and domain `references/`, with zero CLI names and zero script invocations.
  The only exception is a one-line pointer naming `references/tooling.md`.
- **Reference implementation** — exact commands, flags, traps, auth notes,
  script invocations — lives in one `references/tooling.md`. These are what
  run locally, and they are the behavior any other backend must reproduce:
  same inputs, same outputs, same postconditions. An ADLC integration may
  serve the verbs only where it meets them — conformance is checked, never
  assumed from nativeness.
- **Frontmatter** splits accordingly: `compatibility:` names process
  prerequisites true in every execution mode; `local-tooling:` names the
  reference implementation's CLIs.

Each skill restates the verb-execution paragraph in its own words — an
installed skill cannot rely on a host repository's conventions — and never
names the bot or platform: shipped prose says "ADLC tools". Rule of thumb: if
a conforming backend needs to know it to meet the contract, it is process; if
it is how one particular backend runs, it is reference implementation. The
full authoring pattern, with the paragraph to adapt, is in
[references/create.md](references/create.md) → Dual-mode.

## Working inside a host repository

Before designing a skill, read whatever conventions the repository states —
typically `AGENTS.md`, a glossary, and any decision records. Those bind the skill
you are about to write. They do not bind the skill once installed, so nothing you
write into the skill may depend on being able to read them.

Where the repository publishes a collection, expect it to define: which skills are
human-invoked, whether a name prefix applies, how skills compose, where the
membership manifest lives, and what the tests protect. Follow its answers.

## Interview dependency

Creating or interviewing for a skill requires an interview skill that stress-tests
scope before drafting — `/grilling` in this collection. If the host cannot invoke
it by name, stop before drafting anything and say that creation is gated on it.
Audit and consolidation do not require it unless they open an interview.

## Conditional references

Load exactly one branch. Its own pointers name any specification, description,
architecture, script, or quality reference needed later.

- Read [references/create.md](references/create.md) to interview, draft, and
  review a new skill from scratch — "create a skill", "draft a SKILL.md",
  "package this expertise".
- Read [references/audit.md](references/audit.md) to review, repair, or diagnose
  an existing skill — "why does this never trigger", "check this SKILL.md",
  "improve this skill".
- Read [references/consolidation-guide.md](references/consolidation-guide.md) to
  merge overlapping skills into fewer, or to test whether a merge already went
  too far. Finish through the Phase 5 review in
  [references/create.md](references/create.md).

## Completion

Work is complete when the selected branch's review checklist passes, every
referenced resource resolves, no behavior remains duplicated under an old
skill name, and every changed `.py` file passes the host linter.
