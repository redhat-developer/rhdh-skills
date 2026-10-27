# Spike: Make skills chai-bot native (dual-mode: local + chai)

Status: proposal, revision 4 after team feedback. No skill rewritten beyond
the rhdh-jira-api pilot. Deliverable of the research card "Make skills more
chai bot native".

Revision 4 replaces the per-goal tool choice with **verb contracts**. Revision
3 said "use whichever tool you actually have; prefer a native integration" —
which made the chai path non-deterministic: the agent re-derives API calls
whose documented traps (30-row silent truncation, absent-vs-empty fields,
security-on-create, ADF conversion) exist precisely because improvising them
wrong is easy. The fix moves determinism from the command layer to the
contract layer: each external operation is a named verb with pinned inputs,
outputs, and postconditions; the bundled scripts are the **reference
implementation**; and another backend — a chai integration — may execute the
verbs only where it demonstrably meets the same postconditions. Conformance is
checked once per backend, not re-decided at every step.

Revision 3 corrects the mode test: the discriminator is **whether the agent
has the specific tool the sidecar references**, not whether it has a shell.

Revision 3 corrects the mode test: the discriminator is **whether the agent
has the specific tool the sidecar references**, not whether it has a shell.
Chai may have bash; the point is that its **native integrations** (Jira,
Google Workspace, GitHub, GitLab) are preferred over wrapping local CLIs
(`acli`, `gog`, `gh`). Goals are stated tool-free; each agent picks the tool
it actually has, native first.

Revision 2 changes: chai **formats output for Slack itself** — no
presentation-layer work in the skills. The goal is narrower and better:
**separate tooling from process**, so every skill runs both for a local
developer (shell, checkout, CLIs) and for the chai bot (its own Jira / GitHub /
GitLab connectors), with tooling optional where it can be.

## Context

The team runs an agent through the chai bot, whose primary interface is Slack
and which reaches Jira, GitHub, GitLab, etc. through its own connectors. Skills
written for a repo-checkout agent assume a shell, CLIs on PATH, and literal
commands. Chai has none of that but has platform tools covering the same verbs.
The process knowledge in the skills is right for both; the transport is right
for only one of them.

## What the survey found

- 60 `SKILL.md` files across 6 domain folders.
- Skill prose is deeply CLI-coupled:
  - `uv run scripts/…` appears ~156 times in markdown.
  - `acli jira` ~105, `gh pr` ~48, `glab mr` ~17, `podman compose` ~26, plus
    `jq`, `skopeo`, `oc`, `rhdh`, `agentready`.
  - Every SKILL.md frontmatter has a `compatibility:` line naming CLIs
    (`acli on PATH`, `gh authenticated`, `Node on PATH`, …).
- Workflows open with a literal command block (`python scripts/triage-prs.py`)
  before any goal statement.
- ~50 bundled scripts. Two kinds, mixed:
  1. **Transport wrappers** — shell out to `gh`/`glab`/`acli`/Jira REST and
     format output (`create-pr-mr.js`, `link-pr-mr.js`, `gangway_adapter.py`,
     `trigger_nightly_job.py`).
  2. **Computation** — real logic the model should not re-derive
     (`analyze_coverage.py`, `update_rpa_tags.py`, `analyze-pr.py`,
     `bump-yarn.js`, lockfile/RPM analysis in `rhdh-base-images`).
- `mutation-gate` already defines approval-before-write as a protocol, not a
  tool — it survives unchanged in both modes.
- `rhdh-jira-api` is the extreme case: its substance is acli flag traps. Under
  the split, JQL, custom-field IDs, workflow states, and exit criteria are
  process (stay in the body); the flag traps are tooling (move to the tooling
  reference).

## Core design: process in the body, tooling in an optional sidecar

Three layers, down from three concerns to two (presentation is chai's job
locally-formatted by the local agent's own UI):

| Layer | Where it lives | Loaded when |
|---|---|---|
| **Process** — verb contracts (inputs, outputs, postconditions), decision tables, exit criteria, templates, sequencing, gates, failure modes | `SKILL.md` + `workflows/` + domain `references/` | always |
| **Reference implementation** — exact CLI commands, script invocations, flags, auth notes | one `references/tooling.md` per skill | locally, always; another backend only where it meets the verb postconditions |

### Anatomy

```
skill/
  SKILL.md            # process only; zero CLI names, zero script invocations
  workflows/*.md      # process steps, same rule
  references/         # process references (label priorities, fields, templates)
  references/tooling.md   # optional: local-mode commands, keyed to process steps
  scripts/            # optional: exact implementations, invoked only from tooling.md
```

### The rewriting pattern

Every command block in process prose becomes a **verb invocation with pinned
inputs, outputs, and postconditions**, plus a one-line pointer to the reference
implementation:

```markdown
Run the open-overlay-PRs read (verb contract: every open overlay PR with
labels, assignee, and staleness; postcondition: the result states the total
and whether it was truncated). Then classify each PR by the table below …

> Tooling: `references/tooling.md#list-prs` — the reference implementation
```

- **Local agent**: runs the exact command behind the pointer. Deterministic.
- **Chai agent**: executes the same verb through its integration — but only
  after that backend has demonstrated the postconditions (a probe or a
  verified run); until then it runs the same scripts through its shell. Either
  way the verb contract, not per-step judgment, decides the shape of the call.
- The pointer is the *only* place a CLI or script name appears in process prose.

### How a verb gets executed

One standard paragraph, stated in `SKILL.md` (restated per skill — skills may
not cite repo-level files, per AGENTS.md):

> Every external operation below is a verb with pinned inputs, outputs, and
> postconditions. Invoke the verb; never improvise a raw API call. The bundled
> scripts are the reference implementation (`references/tooling.md` locally).
> An ADLC integration may serve the verbs only where it meets the same
> postconditions — a backend that silently truncates results or drops fields
> is not an implementation, it is a bug.

The test is **conformance, not availability or preference**. Revision 3 let
the agent pick a tool per goal, which turned every chai-path execution into an
untested re-derivation of calls whose traps are documented because getting
them wrong is easy. Conformance is established once per backend, not decided
per step: a probe asserts the postconditions (pagination returns the total,
enrichment returns custom fields, absent is reported as unretrieved), and only
a backend that passed serves the verbs. The local scripts remain the fallback
that always works — "prefer the native integration" is aesthetics until that
integration is conformance-tested.

**Naming rule for shipped prose:** skills never name the specific bot or
platform ("chai bot") — they say **ADLC tools**. The skill outlives whichever
front end runs it. Internal repo docs (this spike, AGENTS.md, memory) may name
chai concretely.

**Placement:** the runtime paragraph lives in each `SKILL.md`, restated in its
own words — `AGENTS.md` does not travel with an installed skill, so a chai-side
agent would never see it. The *authoring* rule ("skills state goals, not tools;
commands live in `references/tooling.md`; restate the tool-picking paragraph
per skill") lives in `skill-authoring`, which ships with the pack, and in this
repo's `AGENTS.md` for contributors. Per the repo's own restatement rule, the
runtime copy is what travels; the definition lives once.

### Frontmatter: two lines instead of one

```yaml
compatibility: "Read access to RHIDP Jira; ability to create GitHub PRs. Core Team role."
local-tooling: "acli on PATH with a Jira session; gh; Python 3.9+ and uv. The reference implementation — see references/tooling.md."
```

`compatibility:` becomes **process prerequisites** (access, role, capability) —
true in both modes. `local-tooling:` names the reference implementation's
CLIs; another backend may replace them only where it meets the verb
postconditions.

## What "optional" means — three tiers

1. **Mandatory process**: decision tables, exit criteria, sequencing,
   `mutation-gate`, the `prose-editing` pass. Never optional — these are
   composition contracts in AGENTS.md, not tooling. If a gate must soften for
   chai, that is a separate explicit decision, not a side effect of this
   migration.
2. **Reference implementation**: the `tooling.md` reference and every script
   invocation. Exact locally. Another backend replaces it only by meeting the
   verb postconditions — conformance, not absence, is what makes it
   replaceable.
3. **Already-optional steps** (`--no-open`, `--draft`, "open the diffs page",
   "push before create"): these are tooling conveniences, not process. They
   move into `tooling.md` entirely; process prose keeps only the decision
   ("push the branch, then create the PR" stays as sequencing; the flag that
   suppresses it is tooling detail).

Rule of thumb: **if an agent using only native integrations still needs to
know it, it is process; otherwise it is tooling.**

## Scripts strategy (unchanged from revision 1, now simpler)

- **Transport wrappers**: extract sequencing knowledge into process prose
  ("push, create, link, open — in that order; missing Jira auth fails the
  link step, not the create"), then the wrapper either stays in `tooling.md`
  as the reference implementation or is deleted once nothing references it.
- **Computation scripts**: keep. `tooling.md` says "run this for the exact
  result"; the owning reference documents the algorithm so a conforming
  backend can reproduce it. Script stays the exact implementation, not a
  dependency.
- Net effect: identical skill, one contract, backends that are checked rather
  than trusted.

## What does not change

- Router-facing descriptions, trigger phrases, `ask-rhdh` catalog rows —
  routing, not transport.
- `mutation-gate` protocol — presentation-free already; chai renders its plan
  table however it renders.
- `prose-editing` as the outbound-text gate.
- Composition contracts and named-skill invocation.
- Output formatting entirely: chai formats for Slack; local agents format for
  their own UI. Skills stop caring.

## Migration plan

1. **Define the pattern** in `skill-authoring` (anatomy, verb-execution
   paragraph, frontmatter split, tier rule) + update the repo-level rule here
   in AGENTS.md if needed.
2. **Pilot on three skills** covering the range:
   - `rhdh-jira-api` (hardest: CLI mechanics are its substance — proves the
     split and shows how much moves to `tooling.md`),
   - `rhdh-overlay` triage workflow (read-heavy, script-classification —
     proves the computation-script pattern),
   - `rhdh-jira-link` (write-heavy transport wrappers — proves the
     wrapper-extraction pattern).
3. **Conformance probe**: extend capability detection (`setup.py`) into a
   probe that asserts the verb postconditions per backend — pagination
   totals, enrichment, absent-vs-empty — so backend eligibility is checked,
   not assumed. Until a backend passes, the local scripts are the only
   executor.
4. **Sweep remaining skills by domain**, jira first (most chai traffic), then
   plugins, release, ci, refinement.
5. **Sweep tests alongside each domain**: tests that assert CLI text in
   SKILL.md or workflows need updating to point at `tooling.md`; catalog,
   membership, and invocation-metadata tests should be unaffected.
6. **Scripts last**: after nothing in process prose requires them, decide
   wrapper-by-wrapper whether to keep as reference implementation or delete.

Each step its own card/commit; tag per AGENTS.md versioning (the frontmatter
meaning change and moved content warrant a major bump at the sweep).

## Open questions

1. Which integrations does chai actually expose (Jira, Google Workspace,
   GitHub, GitLab), and do any lack a capability the local CLI path has?
   (The design does not depend on the answer, but the probe idea on the card
   would settle it and shape each skill's goal wording.)
2. Should `local-tooling:` live in frontmatter (visible before opening the
   skill) or only inside `tooling.md`? Proposal: frontmatter, one line, so a
   chai-side router can ignore it cheaply.
3. Do any gates need explicit chai-mode softening (tier 1 above says not
   without a separate decision) — e.g. the external `grilling` dependency in
   `/rhdh-jira-create`, which today blocks creation without it?
