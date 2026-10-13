# Contributing

This guide explains how to change the promoted skill pack without widening its
interfaces or breaking distribution.

## Set up the repository

```bash
uv sync --extra dev
git config core.hooksPath .githooks
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`.githooks/pre-commit` runs the ruff hooks in `.pre-commit-config.yaml`. Set
`core.hooksPath` as above so those hooks fire; a Red Hat `rh-pre-commit` hook in
`.git/hooks/` does not format Python.

For end-to-end skill use, install the complete pack documented in
[README.md](README.md), including `/grilling`, `/code-review`, and `/handoff`.

## Choose the owning module

Before editing, identify the one skill that owns the behavior. Category folders
are editorial and are stripped at install:

- `skills/jira/`
- `skills/plugins/`
- `skills/ci/`
- `skills/release/`
- `skills/refinement/`
- `skills/reference/`
- `skills/meta/`

A category move must not change how callers invoke a skill. Compose with a
stable `/skill-name`; never reference another category's internal file.

A skill claims exactly one trigger phrase. Split by verb rather than by noun, and
weight the split by what a misroute costs: merge where a misroute produces a wrong
write, split where it produces an obvious wrong answer. Put branch-only knowledge
in an owned reference and deterministic work in a script.

When the same material appears in two skills, do not copy it a third time. Ask
which module owns it and pick one of three answers: **extract** it into a
reference skill when nothing owns it, **enforce** the existing seam when a
module owns it and a caller copied past its interface, or **document** it once
when it is a rule rather than a capability: in `AGENTS.md` for rules governing
this repository, in `skills/meta/skill-authoring/` for rules that must ship
with the pack, because `AGENTS.md` does not travel with it.

That applies to prose only. Bundled scripts are self-contained and may duplicate
utility code; there is no shared runtime package. See
[ADR-0006](docs/adr/0006-duplication-by-layer.md).

Draft work belongs under `internal/in-progress/`, outside the promoted discovery
root. Retired history belongs under `internal/deprecated/`. Neither ships.

## Add or change a promoted skill

1. Create `skills/<category>/<name>/SKILL.md`, with the frontmatter `name`
   lowercase and equal to the directory name.
2. Write the `description`, under 1024 characters, stating the capability and
   its genuine trigger branches.
3. Keep the `SKILL.md` body to every-branch steps. Put branch-only material in
   `references/` behind a pointer that says when to read it.
4. Add `agents/openai.yaml` with a display name and short description.
5. Add the skill to `skills/meta/setup-rhdh-skills/assets/catalog.json` with its
   category, invocation, and required skills.
6. Regenerate the routing table:
   `cd skills/meta/ask-rhdh && python scripts/render_routes.py --write`
7. Let pre-commit regenerate `.claude-plugin/marketplace.json` from the catalog
   (or run `uv run python scripts/generate_plugin_manifest.py --write`). That
   file groups `npx skills add` by installable category and folds required
   `reference` skills into each consumer group; it is not a Claude Code
   marketplace product — see [ADR-0009](docs/adr/0009-skills-cli-plugin-manifest.md).
8. Update `README.md` if membership or naming changed.
9. Add script, adapter, and catalog contract tests as applicable.
10. Run `uv run ruff format` and `uv run ruff check` on every changed `.py`
    file, then `uv run pytest`.

### Rules the validator and reviewers enforce

**Naming.** Name a skill after its subject. `rhdh-` belongs on a skill about Red
Hat Developer Hub; a genuinely generic skill takes a generic name.

**The description is the routing surface.** It is all the router sees. Keep the
literal proper nouns: project keys, repository names, tool names. Never name a
sibling skill, and never include a literal you are disclaiming: the token fires on
presence, so "a key such as ABC-123 is not a sprint" makes the skill a candidate
for exactly that request.

**Compose by name.** Invoke other skills by name and read what they report. There
are no artifact contracts, no versioned envelope, no store, and no material hash.

**External writes go through the gate.** State each operation with its target,
exact command, preview, and failure behaviour; get approval for that stated set;
execute; report the outcome of every operation, including the skipped ones. Cite
`/mutation-gate` rather than restating it.

**A skill may not depend on this repository.** Only its own directory is
installed, so `AGENTS.md`, `CONTEXT.md`, this file, and `docs/adr/` do not travel
with it. A skill citing them is broken for everyone who installs it. Restate the
rule locally instead.

Human-only metadata is for entry points a person explicitly invokes and the
router must never select. A delegating entry point contains no domain behavior,
names exactly one model-invoked target, and passes the person's input to it;
`clean-prose` is the current example. A skill missing from `catalog.json` fails
`scripts/validate_skill_catalog.py`, and nothing installs it.

Do not add prose-shape assertions. Tests should survive editorial improvements
that preserve the skill interface.

## Preserve setup and state compatibility

Changes to skill layout must retain established runtime locations unless an ADR
explicitly changes them:

- `~/.config/rhdh-skills/config.json`
- `.rhdh/worklog.jsonl`
- `.rhdh/TODO.md`

Keep the existing `rhdh` and `rhdh-local` CLI behavior compatible. Update setup
routing rather than introducing a second configuration source.

Keep credentials inside an authenticated adapter backed by a native tool store
or host connector. Only the adapter retrieves a transient credential and
authenticates its request. Keep workflow inputs and outputs credential-free, name
the missing capability and its exact `/setup-rhdh-skills <route>` when one is
absent, and leave login to the human setup router.

For external writes, report one outcome for each approved operation, including
failures and skips, naming the target it changed.

## Document architectural changes

Update an ADR when a change alters distribution, invocation, composition,
adapters, or CLI portability. Preserve superseded ADRs as history and link them
to the replacing decision, unless the decision never shipped, in which case
rewrite it in place rather than recording a supersession no reader ever saw.

Keep `CONTEXT.md` limited to domain language. Skill names and implementation
layout belong in architecture or contributor documentation.

## Release

Git tags are authoritative. Do not add a version file.

- Patch tag: compatible behavior fix.
- Minor tag: new backward-compatible skill or capability.
- Major tag: breaking rename, removal, or interface change.

The decomposition to one skill per trigger phrase ships as one major cutover. Old
skill aliases and a mixed old/new catalog are intentionally excluded.

After the breaking branch is merged and tagged, a maintainer signs in at
`https://skills.sh/packs/create`, creates the `RHDH complete` pack from the
tagged repository plus `grilling`, `code-review`, and `handoff`, and records the resulting
`https://skills.sh/p/<pack-id>` URL in the setup catalog. Packs are unlisted,
not access-controlled, so never include credentials or private files. Until
that URL exists, `/setup-rhdh-skills` emits the equivalent two-source install
plan.
