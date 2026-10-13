---
name: rhdh-spec-driven-schema
description: >-
  Owns RHDH's project-local OpenSpec workflow definition — the
  `rhdh-spec-driven` schema (proposal -> {specs, design} -> tasks -> apply),
  its four artifact templates, the Canonical Touchpoints rule that ties a
  change back to `specifications/prd/`, `specifications/adr/`, and
  `openspec/specs/<capability>/spec.md`, and the shared artifact-creation-loop
  mechanics every openspec-* skill drives through the `openspec` CLI. Also
  installs `config.yaml` and `schemas/rhdh-spec-driven/` into a product repo's
  `openspec/` so the CLI can resolve that schema. Invoked by name from
  openspec-new-change, openspec-continue-change, openspec-ff-change, and
  openspec-onboard; not a standalone entry point. Use for "what does the
  spec-driven schema require", "install the rhdh-spec-driven schema", "what
  goes in Canonical Touchpoints", "how do I fill in an artifact template", or
  "why did an artifact instruction reject my capability name".
compatibility: "openspec CLI on PATH for --schema rhdh-spec-driven. Python 3 for the install helper."
---

# RHDH spec-driven schema

Give every openspec-* skill one shared place to read the actual RHDH workflow
definition, instead of each restating the schema's rules from memory.

## What this skill owns

- `config.yaml` — the project-local schema selection (`rhdh-spec-driven`), the
  RHDH context block (split canonical model, journal obligation), and the
  per-artifact house rules.
- `schemas/rhdh-spec-driven/schema.yaml` — the authoritative artifact graph:
  `proposal -> {specs, design} -> tasks -> apply`, each artifact's instruction
  text, and the `apply` block's direct-vs-team mode guidance.
- `schemas/rhdh-spec-driven/templates/{proposal,spec,design,tasks}.md` — the
  structural template for each artifact.
- [references/artifact-loop.md](references/artifact-loop.md) — the shared
  mechanics for driving `openspec instructions <id> --change <name> --json`
  and turning its response into a written artifact file.
- `scripts/install_project_schema.py` — copies `config.yaml` and
  `schemas/rhdh-spec-driven/` into a product repo's `openspec/` so the OpenSpec
  CLI can resolve the schema there.

## Install into the product repo (startup / setup)

OpenSpec loads schemas from the project's `openspec/`, not from this skill
directory. Before any `openspec new change` that should use `rhdh-spec-driven`,
ensure those files are on disk:

```bash
python3 scripts/install_project_schema.py
```

Run that from the product repo (or pass the project root as the first
argument). The helper lives next to this skill — resolve
`scripts/install_project_schema.py` relative to this skill's install path, not
under the product repo's `scripts/`. Use `--force` only when deliberately
replacing a customized copy.

Callers (`/openspec-new-change`, `/openspec-ff-change`, `/openspec-onboard`,
and `/setup-rhdh-skills` when seeding a product checkout) check for
`openspec/config.yaml` and `openspec/schemas/rhdh-spec-driven/` first and run
this install step only when either is missing. Idempotent: existing files are
kept unless `--force` is set.
Writing into the product repo is an external write — take it through
`/mutation-gate` when the caller is in a setup or multi-operation plan; a
single scaffold turn that already creates `openspec/changes/` may include this
copy in the same stated set.

Confirm with `openspec schemas --json` that `rhdh-spec-driven` is listed, then
omit `--schema` to take the configured default (or pass
`--schema rhdh-spec-driven` explicitly).

## Canonical Touchpoints, non-negotiable

Every `proposal.md` states a `Canonical Touchpoints` section naming every
affected PRD/ADR file under `specifications/` and every affected long-lived
capability spec under `openspec/specs/`, or explicitly `None`, plus the change
type: product | architecture | feature-spec | migration | workflow-only |
docs-only. `design.md` and `tasks.md` carry that same touchpoint set forward —
see `schema.yaml`'s per-artifact `instruction` field for the exact wording
each artifact requires. A caller skipping this because "it's a small change"
is exactly the case the rule exists for: state `None` explicitly rather than
omitting the section.

## Journal obligation

`config.yaml`'s context block states the turn-bookending discipline (log
`turn.start` before work, `turn.end` after, every prompt, inside an active
change) and the apply-phase event set. The mechanics of writing those events
belong to `openspec-journal`, invoked by name — this skill states *when* the
obligation applies; `openspec-journal` states *how* to satisfy it.

## Completion

Complete when the caller has either installed `openspec/config.yaml` and
`openspec/schemas/rhdh-spec-driven/` into the product repo, or read the exact
schema/template/context text it needed for the artifact in front of it —
rather than guessing at wording. A caller citing this skill without reading
`schema.yaml`'s `instruction` field for that artifact is the failure mode
this skill exists to prevent.
