# Create workflow (Phases 1–5)

Interview, draft, optimize, script, and review a new skill from scratch.

## Phase 1: Interview

### Grilling prerequisite (hard gate)

Creating or interviewing requires an interview skill that stress-tests scope
before drafting — `/grilling` in this collection. This skill neither locates nor
installs its own dependencies; installation belongs to whichever setup entry
point the collection publishes.

If the interview skill cannot be invoked by name, stop before drafting anything,
say that creation is gated on it, and name the setup entry point that installs
it. Never probe host skill directories or improvise a substitute interview.
Resume the original create request once the human reports the dependency
available.

### Interview cadence

Invoke `/grilling` and follow its interface. Do not paraphrase its cadence rules.

Use grilling to walk the focus areas and architecture decision tree below. If a fact can be answered by exploring the codebase, explore instead of asking.

Focus areas, roughly in order:

1. **Purpose and audience.** What task does this skill cover? What specific problem does it solve? What does the user do today without it?
2. **Scope boundaries.** What should this skill NOT do? What adjacent tasks belong to other skills?
3. **Input/output.** What does the user provide? What does the skill produce? Specific formats?
4. **Edge cases.** What goes wrong? Common mistakes? Gotchas for new users?
5. **Success criteria.** How do you know the skill worked correctly?
6. **What can be scripted?** Look for deterministic operations that should be code, not LLM instructions. Scripts are cheaper, faster, and more reliable.
7. **References needed?** Domain knowledge too large for SKILL.md that should live in separate files?
8. **Existing patterns.** Similar skills or workflows to draw from? Check the codebase.
9. **Platform constraints.** macOS, Windows, and Linux? Scripts must handle path separators, temp directories, and shell differences.
10. **External services and APIs.** Does the skill call external APIs or services? If yes, read `api-skill-patterns.md` — it covers credential handling, schema discovery, instance-specific values, and error placement.

### Architecture decision tree

After the interview questions above, decide the architecture. Most skills are one
file — only escalate when the answers demand it.

**Question 1: How many distinct utterances would send a user here?**

- One thing a user would say → one skill
- Several unrelated things → several skills, each named domain-then-verb, each
  with its own description. Stop here and design them separately; a single skill
  answering several utterances is the retired sub-command router
- Several *phrasings* of one intent → still one skill; the phrasings belong in
  its description

**Question 2: Does that one trigger have branches?**

- No, the work is linear → single `SKILL.md` under 200 lines
- Yes, but every branch shares the domain model, the gates, and the completion
  criterion → `SKILL.md` plus conditional references
- The branches share none of those → back to Q1; they are separate skills

**Question 3: How deep is the material behind the one trigger?**

- A workflow and a few rules → conditional references are enough
- A full lifecycle within one vocabulary — build, debug, test, ship the same
  thing → exhaustive references and workflow files, still one trigger

| What you're building | Shape |
|---|---|
| "A skill that commits with a conventional message" | One file |
| "A skill that reviews a PR" | Conditional references |
| "A skill that manages PRs — create, review, merge, close" | Four skills |
| "A skill for building and shipping macOS apps" | Deep references, one trigger |

Beyond the first file, also ask:

- **Does the skill need project-level context?** If every branch needs the same
  background, design a context file pattern with a loader script.
- **Are there mandatory setup gates?** Checks that must pass before any work
  begins. Gates prevent generic output.
- **Does behaviour vary by task type?** If so, design a register/mode system that
  classifies the task first, then loads different references.

Read `architecture-patterns.md` for implementation details of each pattern.

**Consolidation signal check:** if the interview reveals the new skill overlaps
significantly with an existing one — shared scripts, cross-references, a linear
pipeline — consider consolidating instead of creating. Read
`consolidation-guide.md` for the signals, and its counter-signals for how far is
too far.

Do not proceed to Phase 2 until the user confirms the scope is complete.

## Phase 2: Draft the SKILL.md

Write the skill following the spec. Read `spec-guide.md` for the full format reference before drafting. Read `skill-quality.md` before drafting (predictability via information hierarchy, checkable completion criteria, strong context pointers, pruning) and again during Phase 5 Quality.

**Starter template:** copy `templates/simple-skill.md`, then replace its generic
boundaries with the real interface and completion criterion. A skill with
branches starts from the same template and adds conditional pointers — there is
no separate multi-command template, because a skill with several commands is
several skills.

### Frontmatter

```yaml
---
name: skill-name        # lowercase, hyphens, max 64 chars
description: |           # max 1024 chars — implicit trigger for model-invoked skills
  What the skill does. Use when [specific triggers].
  Also use when [additional triggers].
---
```

For a model-invoked skill, make the description slightly "pushy" because agents tend to undertrigger.
Include what it does and genuine phrases or contexts that should activate it. A human-invoked entry
skill disables implicit invocation; its description is catalog copy, not a model trigger.

### Body structure

Follow progressive disclosure — three loading levels:

1. **Metadata** (~100 tokens): `name` and `description` are available for model-invoked skills;
   human-only entries are selected explicitly
2. **Instructions** (< 500 lines): Full SKILL.md body loaded when skill activates
3. **Resources** (as needed): `references/`, `scripts/`, `assets/` loaded only when required

Keep the SKILL.md body under 500 lines. If approaching this limit, split domain-specific content into `references/` files with clear pointers about when to read them.

That limit governs `SKILL.md` alone, and splitting satisfies it without fixing anything. Watch the directory total too, and ask the question the total only hints at: **which of these vocabularies does a caller have to learn?** One trigger phrase should commit the caller to one. See `consolidation-guide.md` → Size heuristics.

### Deduplication check

Before writing domain knowledge into a new reference file, check if it already exists in another reference. Shared data (exit criteria, field mappings, workflow rules) must live in exactly one file. New references should point to the existing source — not embed a copy.

Common trap: a new branch reference duplicates tables from an existing reference because it "needs them for context." Instead, add a one-line pointer: "Load `references/workflows.md` for exit criteria per status."

**Exception: intentional duplication.** When two branches need the same query pattern but referencing each other would create a transitive loading chain (A → B → C), duplicate the pattern and add a note: "Same query pattern as X.md Step N — duplicated here to avoid transitive loading." This is cheaper than forcing the agent to load an unrelated file.

The exception stops at the skill boundary. Across skills there is no file to point at and no note that keeps two copies honest — apply the extract/enforce/document rule in `architecture-patterns.md` → Duplication between skills.

### Writing patterns

- **Imperative form**: "Run the command" not "You should run the command"
- **Explain WHY, not just what**: Avoid rigid ALWAYS/NEVER rules without reasoning. Agents generalize from principles better than from rigid rules. Instead of "ALWAYS use pdfplumber. NEVER use PyPDF2," write "Use pdfplumber over PyPDF2 — it handles malformed PDFs more gracefully and preserves layout metadata needed for table extraction." Principles adapt to edge cases; rigid rules break.
- **Don't explain what the agent already knows**: Skip basic programming concepts, standard library usage, and well-known tool behavior. Only add context the agent doesn't have — project-specific conventions, non-obvious behavior, domain-specific gotchas. A 30-token code example beats a 150-token explanation of what a library is.
- **Output templates**: Define exact formats when the output structure matters
- **Concrete examples**: Show input → output for non-obvious workflows
- **Gotchas sections**: Common mistakes the agent should avoid
- **Checklists**: Multi-step workflows with validation gates
- **Conditional loading**: "Read `references/api-errors.md` if the API returns a non-200 status code" — not "see references/ for details"
- **Absolute bans**: When certain patterns are always wrong, use match-and-refuse lists. "If you're about to write X, stop and do Y instead." More effective than vague "be careful" guidance.
- **Avoid hardcoded thresholds**: Don't write arbitrary numbers as rules (e.g., "when you have 3+ branches" or "if more than 5 issues") unless the threshold comes from a real constraint (API limit, spec requirement). Instead, describe the signal that triggers the behavior (e.g., "when you're copying the same text into another branch file"). Hardcoded numbers feel authoritative but are usually guesses that don't generalize.

Read `anti-patterns.md` during drafting to avoid known pitfalls.

### Instruction structure

Use descriptive Markdown headings and short sections. Structure is an authoring
aid, not a public protocol; never require tests to preserve headings, tags, or
menu numbering.

### Conditional references (when the skill has branches)

Disclose a branch with a pointer that names the material and the condition for
reaching it. The condition fires on something the request already settled — a
pointer that asks the user which mode they want is the retired sub-command
router, and means the branches are separate skills. Read
`architecture-patterns.md` → Conditional references, not routes.

```markdown
Load `workflows/create-issue.md` — it covers every level of the hierarchy.

Add `references/support-intake.md` when the work originates from a support case:
an RHDHSUPP conversation, a customer escalation, or an SLA question.
```

The filenames above are **example only** — substitute the real ones for the skill
you are building.

### Dual-mode: goals and an optional tooling sidecar (when the skill drives CLIs)

State goals, not tools. The same skill must run for an agent with native
integrations (ADLC tools) and for an agent with a shell and local CLIs, so
process and tooling separate:

- **Process** — goals with inputs, outputs, and failure modes; gates; exit
  criteria; sequencing; templates — stays in `SKILL.md`, `workflows/`, and
  domain `references/`. Zero CLI names, zero script invocations; the only
  exception is a one-line tooling pointer
  (`> Tooling: references/tooling.md#anchor`). Where a wrong call fails
  silently — a truncated search, an unread custom field — state the
  postcondition on the goal; it binds whichever tool executes.
- **Tooling** — exact CLI commands, flags, traps, auth notes, script
  invocations — lives in one optional `references/tooling.md` sidecar, framed
  for agents that actually have the CLIs. An ADLC tool may serve the same
  goals; stated postconditions bind it too.
- **Frontmatter splits accordingly**: `compatibility:` names process
  prerequisites (true in every mode); `local-tooling:` names the optional
  CLIs and says so.

Restate a short goals paragraph in the skill's own words — it must travel with
the installed skill, so it cannot live only in a host repository's
conventions:

> Every step below states its goal, never which tool to use. Use whichever
> tool you actually have — an ADLC tool, or the optional local commands in
> `references/tooling.md`. Postconditions stated on a goal bind whichever
> tool executes it.

The discriminator is **tool availability, not shell access**: an agent with a
shell and a native integration should use the integration, not wrap a CLI.
Rule of thumb: if an agent using only native integrations still needs to know
it, it is process; if it is how one particular tool runs, it is tooling. Never
name the bot or platform in shipped prose — say "ADLC tools".

### Setup and capability gates (when applicable)

Non-negotiable checks before any file edits. Gates prevent generic output from missing context, and every gate follows one rule: when a required precondition is missing, stop that branch, name the missing capability, and name the exact setup entry point and route that supplies it. Write them as a table with a required check and a fail action per row, mutation last — the table pattern and where that rule stops are in `architecture-patterns.md` → Setup and capability gates.

### Register/mode system (when applicable)

When behaviour varies sharply by task type while the trigger stays one, classify the task first and load the matching reference. See `architecture-patterns.md` → Register and mode systems for the pattern and its limit: registers that share no gates or completion criterion are separate skills.

### Handoffs between skills

When one skill produces work another consumes, the producer states the result in
the conversation, structured enough to act on, and the consumer states what it
requires before it starts. A user who needs context to survive into a later
session runs a session-handoff skill. Skills compose by name, so the handoff interface is
what the producer said, never a reference file or script path. See
`architecture-patterns.md` → Handoffs between skills for the producer and consumer
shapes.

### Self-critique loops

For a branch that builds something, mandate inspect-and-fix passes with an
explicit exit bar. "Looks good" is not a bar; "all tests pass, every expected
scenario is handled, no placeholders remain" is. The loop template is in
`architecture-patterns.md` → Self-critique loops.

## Phase 3: Description Optimization

For model-invoked skills, the description is the only skill content agents see at startup. Human-invoked descriptions are human-facing catalog text. Read `description-guide.md` for the full optimization process.

Quick validation:

1. Write should-trigger queries — at least enough to cover each branch and near-miss; prefer 8–10 per `description-guide.md`, minimum cover each branch
2. Write should-not-trigger queries — near-misses that share keywords but need different skills (same coverage bar as should-trigger)
3. Check: would the description correctly distinguish these?
4. Revise if needed — broaden for missed triggers, narrow for false triggers
5. Verify under 1024 characters

The description competes against every skill installed on the machine, not only
against its own collection. Read the neighbouring skills' descriptions and confirm
none of them claims the same utterance; keep the collection's name prefix and the
literal proper nouns — project keys, repository names, tool names — because a
literal token is the strongest routing anchor available.

## Phase 4: Scripts

Read `scripts-guide.md` for shebangs, portability, and the host-linter gate.

**Bias toward scripts.** Every deterministic operation should be a script, not an instruction. Scripts are cheaper (no LLM tokens), faster (no reasoning), and more reliable (no hallucination).

For each piece of the skill's workflow, ask: "Could a script do this?" If yes, write the script.

**Should be scripts:**

- Validation (input format, required fields, schema compliance)
- File generation from templates
- Data extraction and transformation
- API calls with structured responses
- Setup and environment checks
- Output formatting
- Context loading (read project files, resolve paths, return JSON)
- Cleanup (remove deprecated files after skill updates)

**Should stay as instructions:**

- Deciding between architectural approaches
- Reviewing code for quality or style
- Explaining tradeoffs to the user
- Creative writing or design decisions
- Interview/discovery conversations

Key patterns:

- **Python without dependencies**: stdlib only, `argparse` for CLI parsing
- **YAML round-trip exception**: PEP 723 with `ruamel.yaml` and `uv run --script`, the one dependency
  worth taking on, because stdlib cannot round-trip YAML without losing comments and order
- **All scripts**: Structured output (JSON when piped), clear exit codes, descriptive `--help`

### Context loader pattern

For skills that need project-level context, write a loader script:

The script should follow all standard patterns: `argparse` with `--help`, structured JSON output (pretty when interactive, compact when piped), clear exit codes (0 = found, 1 = missing), `pathlib` for cross-platform paths, and stdlib-only imports. See the "Context file system" section in `architecture-patterns.md` for a skeleton.

The SKILL.md references it — for example only: "Load context via `python scripts/load_context.py`. Consume the full JSON output. Never pipe through `head`, `tail`, or `grep`." Rename the script to match the skill.

## Phase 5: Review

Before presenting the final skill, verify against this checklist:

### Basics

- [ ] `name` is lowercase, hyphens only, max 64 chars, and carries the collection's name prefix
- [ ] `description` is under 1024 chars and includes trigger phrases
- [ ] `description` is slightly pushy — covers edge phrasings that should activate the skill
- [ ] `description` names the literal proper nouns the skill owns, and collides with no sibling skill
- [ ] SKILL.md body is under 500 lines, and the whole directory stays proportionate to one trigger
- [ ] Instructions use imperative form

### Architecture (if applicable)

- [ ] The skill claims one trigger phrase; nothing in the body asks the user which mode they want
- [ ] Branch pointers name a load condition, and every branch shares the domain model, gates, and completion criterion
- [ ] Every gate names a required precondition and a fail action; a missing precondition stops the branch and names the exact setup entry point and route — no gate proceeds anyway
- [ ] Register/mode system classifies before loading references
- [ ] Dual-mode split holds: process prose (`SKILL.md`, `workflows/`, domain
      `references/`) carries goals, gates, and exit criteria with zero CLI names
      or script invocations — the only exception is a one-line tooling pointer;
      a postcondition is stated on every goal whose failure mode is silent;
      exact commands live in one optional `references/tooling.md` framed for
      agents that have the CLIs
- [ ] Frontmatter carries the split: `compatibility:` names process
      prerequisites true in every mode; `local-tooling:` names the optional
      local CLIs and says so
- [ ] The goals paragraph is restated in the skill's own words, and shipped prose
      says "ADLC tools", never a bot or platform name
- [ ] Material shared with another skill is extracted, enforced, or documented, never copied
- [ ] Skills compose by stable name — no sibling paths, no imports, no host layout probing
- [ ] Handoffs are prose the producer states and the consumer reads; an external write invokes the skill that owns the write gate
- [ ] Human/model invocation metadata matches the approved repository boundary

### References

- [ ] Domain knowledge split into `references/` with clear "when to read" pointers
- [ ] Each reference is self-contained — no transitive loading (see `spec-guide.md` → Reference Architecture)
- [ ] Reference loading is conditional, not eager ("Read X if Y happens")
- [ ] Shared concerns (auth, config) extracted into their own reference, not embedded in a consumer
- [ ] Error handling lives in the reference for the tool that produces the error
- [ ] Multi-approach skills include a decision table naming which reference covers which approach
- [ ] Model-invoked skills do not start browser-only setup; the human-invoked setup entry point
      may own required OAuth consent or installation steps

### Scripts

- [ ] Scripts (if any) have shebangs, structured output, and `--help`
- [ ] Changed Python passes the host formatter and linter (`ruff format` and
      `ruff check` when the host uses ruff)
- [ ] Context loader returns JSON, handles missing files, resolves fallback paths
- [ ] Scripts are cross-platform (pathlib, tempfile, no hardcoded paths)
- [ ] Scripts are idempotent — safe to re-run
- [ ] A script that writes externally runs only from an approved plan, and every operation it was
      given ends up reported, including the ones that were skipped

### API and service skills (if applicable)

- [ ] Credentials remain inside an authenticated adapter backed by a native tool store or host
      connector; workflow commands, plans, and logs contain no credential material
- [ ] Credential setup delegates to the human-invoked setup skill; domain skills only detect capability
- [ ] Capability gate checks authenticated adapter readiness without inspecting credential material
- [ ] API schema discovery is documented (OpenAPI download, GraphQL introspection, or live endpoints)
- [ ] API examples have been validated against the live endpoint
- [ ] Instance-specific values include programmatic discovery methods

### Consolidation (if merging existing skills)

- [ ] No references to old skill names anywhere in the project (`grep -rn` the entire repo)
- [ ] The setup catalog contains the new promoted names, categories, invocation modes, and dependencies
- [ ] None of the counter-signals in `consolidation-guide.md` fire against the merged skill
- [ ] Script docstrings and `--help` text reference the new skill name, not the old ones
- [ ] Reference paths resolve correctly from each file's location (no `references/references/` nesting)
- [ ] All example files from old skills are represented in the consolidated examples
- [ ] Scripts in the same skill use consistent patterns (NO_COLOR, shell flags, TTY checks, exit codes)
- [ ] README, ADRs, and other docs updated to reflect new skill structure
- [ ] New description covers all trigger phrases from all old skills' descriptions
- [ ] Tests cover scripts, adapters, catalog membership, and clean installation — not prose shape

### Quality

Read `skill-quality.md` again during this Quality pass (same file as before drafting).

- [ ] No time-sensitive information (URLs to specific versions, dates that will go stale)
- [ ] Examples use fake data where possible (emails, names, tokens) — see `spec-guide.md` → Fake Data in Examples
- [ ] Consistent terminology throughout
- [ ] Concrete examples included for non-obvious workflows
- [ ] Absolute bans defined for patterns that are always wrong (pair with positive target — avoid negation-only)
- [ ] Self-critique loops defined for build and implementation branches with explicit exit bars
- [ ] Steps have checkable completion criteria; no obvious premature-completion traps
- [ ] No duplication / sediment / no-ops left after pruning (see `skill-quality.md`)
