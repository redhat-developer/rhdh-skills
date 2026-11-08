# One skill per trigger phrase

**Status:** Accepted. Supersedes [ADR-0003](0003-orchestrator-plus-sub-skills.md).

## Context

The repository grew to 24 top-level skills plus a broad model-invoked `rhdh`
orchestrator whose description competed with every skill it routed to.

The first attempt at a fix consolidated 24 skills into 18 coarse ones. Measuring
the result showed the consolidation had gone the wrong way. `rhdh-plugin-development`
reached 7,784 lines across 45 references that partition into **seven components
with almost no edges between them**. `rhdh-jira` reached 4,029 lines with zero
workflows and a reference layer of six files carrying in-degree 3–9 that were not
even named in its route table. `rhdh-release`'s seventeen workflows mapped 1:1 onto
the seventeen subcommands of `scripts/release.py` — its own route table gave it away
by saying "matching file in `workflows/`" instead of naming anything.

Those are shallow modules: the interface is as complex as what it hides, and a
caller still has to learn which of seven vocabularies applies. The pack's own
authoring guidance already forbade this — `consolidation-guide.md` says "two skills
with independent triggers that share material need the material moved, not the
skills merged" — and the consolidation merged four independent triggers anyway.

## Decision

A promoted skill claims exactly one **trigger phrase**. Where two skills would
claim the same utterance, they are one skill. Where one skill answers to several
unrelated utterances, it is several skills.

Split by verb, never by noun. `to-feature`, `to-epic`, and `to-issue` differ only
by the issue type produced, which is a hierarchy level rather than a user intent —
and the user usually does not know which one they want, so deciding it is the
skill's job, not the router's. Their Step 0 was byte-identical and `to-issue`
already inferred the type at runtime.

Weight the decision by the cost of a misroute. In the creation cluster a misroute
produces a **wrong mutation** — an Epic where a Story belonged — so those merge.
Sprint planning and sprint reporting share a rare noun and distinct verbs, and a
misroute there is read-only and immediately visible, so those split.

The same rule keeps a release-data RPA tag update separate from a Tekton task
digest or migration update. Both use Konflux, but they act on different
repositories, artifacts, and publication paths; the shared noun is not a route.

Shared material becomes a **reference skill**: a model-invoked skill whose reason
for existing is material two or more skills would otherwise copy, reached by name
like any other skill. Two callers is the threshold; one caller means the material
belongs inside its single owner.

Skills are grouped into editorial folders by domain — `jira/`, `plugins/`, `ci/`,
`release/`, `security/`, `refinement/`, `reference/`, `meta/`. Folders carry no
technical meaning: they are
stripped at install, no skill references a category path, and the only coupling is
a validation constant. The previous audience-based split (`engineering/`,
`operations/`, `maintainers/`) predicted nothing; the dependency graph crossed it
in both directions and only one skill of eighteen had an unambiguous home.

Skills compose by stable name. A caller invokes `/rhdh-context`; it never opens
`../reference/rhdh-context/references/…`, imports another skill's implementation,
or reads its private files. Human-invoked skills are entry points for people and
are never invoked by a model-invoked skill.

Setup preserves the existing `rhdh` and `rhdh-local` CLI behaviour,
`~/.config/rhdh-skills/config.json`, and worklog and todo locations.
`/setup-rhdh-skills` is the exclusive human setup router; a domain skill may detect
a missing capability and name the setup command, but never installs, authenticates,
or probes host skill directories itself.

External variation stays behind adapters. Real seams today are issue sources,
forges, container runtimes, lifecycle sources, CI systems, and release data.

Draft and retired skills live outside the promoted discovery root under
`internal/in-progress/` and `internal/deprecated/`, and catalog validation fails on
a skill directory that sits outside a promoted category, so an off-catalog skill
cannot ship by accident.

Git tags are the authoritative skill versions.

## Consequences

- A request matches one skill, because no two descriptions claim the same phrase.
- Skill interfaces survive editorial folder moves.
- More skills, each smaller. The pack is ~41 rather than 18; the count is an
  output of the rule, not a target.
- Every skill costs a description that must not collide, which is the real budget.
  See [ADR-0008](0008-skill-naming-and-namespace-isolation.md).
- Tests protect scripts, adapters, catalog membership, invocation metadata, and
  distribution. Incidental prose shape is deliberately untested.
