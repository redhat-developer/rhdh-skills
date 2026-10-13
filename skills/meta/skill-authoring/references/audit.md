# Audit workflow

Use this workflow when reviewing, improving, or debugging an existing skill.

## Step 1: Locate and read the skill

Read the full `SKILL.md` and list every file in the skill directory
(`references/`, `workflows/`, `scripts/`, `templates/`, `assets/`). Record the
total line count of the directory, not only of `SKILL.md`. Discover any
repository-level agent-eval-harness configs for the skill separately.

## Step 2: Run the audit checklist

Check each category and note issues as you go. Map structural and content
findings to the failure modes in `skill-quality.md` — premature completion,
duplication, sediment, sprawl, no-op, negation — when diagnosing why a skill
misfires or bloats.

**Frontmatter:**

- [ ] `name` matches the directory name, lowercase and hyphens, max 64 chars
- [ ] `name` carries the name prefix its collection publishes under, and reads
      domain then verb
- [ ] `description` is under 1024 chars, non-empty, third person
- [ ] `description` includes trigger phrases, not just a summary of behaviour
- [ ] `description` names the literal proper nouns the skill owns — project keys,
      repository names, tool names, an example issue key such as `RHIDP-1234`
- [ ] `description` covers edge phrasings users would actually say
- [ ] `description` front-loads a leading word, one trigger per branch (see
      `skill-quality.md`)

**Scope:**

- [ ] The skill claims exactly one trigger phrase — one thing a user would say
- [ ] No other installed skill's description claims that same utterance; read the
      sibling descriptions and name any collision found
- [ ] The body starts work from the request rather than asking which mode to run
- [ ] Branches, if any, share one domain model, one set of gates, and one
      completion criterion
- [ ] A caller has to learn one vocabulary to use the skill, not several

**Size:**

- [ ] `SKILL.md` body is under 500 lines
- [ ] The whole directory is proportionate to one trigger phrase. Thousands of
      lines behind one description means the skill absorbed triggers that belong
      to skills of their own — read `consolidation-guide.md` → Counter-signals
- [ ] A pointer reaches every reference, and the references cite each other:
      a component with no citation edges to the rest is a separate skill

**Structure:**

- [ ] Every-branch material is inline in `SKILL.md`, not only in a reference
- [ ] All referenced files exist — check every path in `SKILL.md`
- [ ] References are one level deep, with no chains A → B → C
- [ ] Context pointers name *when* to load, not a vague "see `references/`"
- [ ] `## Completion` states what the skill leaves behind

**Content quality:**

- [ ] No rigid ALWAYS/NEVER rules without reasoning — explain why
- [ ] No explanations of what the agent already knows from training (no-ops)
- [ ] Steps are specific and verifiable, not "handle errors appropriately"
- [ ] Completion criteria are observable and testable
- [ ] Examples use fake data where appropriate
- [ ] Steering names a positive target rather than only a prohibition

**Composition (where the host repository publishes a collection):**

- [ ] Promoted membership, invocation mode, and dependencies match the machine
      catalog
- [ ] Skills compose by stable name — no sibling paths, no imports, no host
      layout probing
- [ ] Handoffs are prose: a producer reports its result in the conversation and a
      consumer reads what the skill it invoked by name reported. An external write
      invokes the skill that owns the write gate; context that must survive into a
      later session is the user running a session-handoff skill
- [ ] A missing capability stops the branch and names the exact setup entry point
      and route, and the skill neither installs nor authenticates anything itself
- [ ] Human-invoked skills are limited to the approved wayfinding and setup entry
      points
- [ ] Prompt duplication is absent: instructions, protocols, and domain rules
      appear in exactly one skill. Where the same material appears twice, say
      whether the fix is extract, enforce, or document (see
      `architecture-patterns.md` → Duplication between skills)
- [ ] Duplicated *code* in bundled scripts is fine and needs no finding — a
      script is self-contained so its skill installs alone. Flag only duplicated
      data such as field IDs, which goes stale silently
- [ ] Tests exercise scripts, adapters, catalog membership, and clean installs
      rather than prose shape

**Scripts** (if present):

- [ ] Scripts have shebangs, `--help`, and structured output
- [ ] No interactive prompts — all input via flags, env, or stdin
- [ ] Cross-platform paths (`pathlib`, no hardcoded separators)
- [ ] Error messages explain what went wrong and what to do
- [ ] Changed Python passes the host formatter and linter (`ruff format` and
      `ruff check` when the host uses ruff)

**Evaluations:**

- [ ] Read `evaluation-guide.md`; evaluation assets use agent-eval-harness rather
      than a skill-local case format
- [ ] Separate prompt-mode routing from explicitly invoked skill behavior
- [ ] Cases test outcome, relevant process, style, and efficiency without
      inspecting hidden chain of thought
- [ ] Model-invoked skills test intended activation and keyword-sharing
      near-misses; user-invoked skills do not pretend routing is under test
- [ ] Runs use isolated case workspaces and repeat stochastic judges
- [ ] The report uses a recorded baseline or pairwise comparison when claiming
      that the skill improved behavior
- [ ] Existing failures and production traces become regression cases
- [ ] Judge logic is deterministic where possible and uses a narrow semantic
      rubric only where necessary
- [ ] Thresholds are calibrated from a successful baseline rather than presented
      as validated guesses
- [ ] Capability skills have retirement evidence; preference skills state the
      durable convention that still requires enforcement

Read `anti-patterns.md` for the full catalog of common failures.

## Step 3: Generate the report

Present findings grouped by severity:

1. **Critical** — the skill won't trigger, or produces wrong output
2. **Important** — structural issues, missing files, spec violations
3. **Minor** — style, conciseness, optimization opportunities

For each finding, state the issue, cite the specific line or section, and
recommend a fix.

## Step 4: Offer fixes

Ask the user which findings to fix. Apply changes surgically — don't rewrite
sections that aren't broken. Before finishing, verify modified skills against the
Phase 5 review checklist in `create.md`, Basics through Quality, and run the
applicable agent-eval-harness configs from `evaluation-guide.md`.

An audit that only reads and reports does not need the `grilling` skill. Invoke
it only when the audit opens an interview, such as clarifying ambiguous scope
with the user.
