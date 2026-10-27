# Vendored third-party skills

**Status:** Accepted.

## Context

Skills reach engineers through Slack as plugins on authorized Red Hat
repositories, and that surface exposes this repository's pack — not arbitrary
upstream sources. A skill the workflow cannot install from the pack is a skill
the workflow cannot deliver.

The `skills` CLI's experimental lockfile sync (`skills-lock.json`,
`experimental_install`) was considered and rejected: it keeps the skills outside
the pack, so the Slack surface would still need to run network installs against
sources it does not authorize, and a verbatim-only link cannot carry the small
adaptations we sometimes need.

## Decision

Ship the vendoring mechanism now, with no source vendored yet:
`skills/third-party/registry.json` is the single metadata config. Its
`sources` map records each upstream `owner/repo` with the `directory` its
skills are vendored under, one pinned `ref`, its `license`, and the `skills`
vendored from it — each with `name`, `path` inside that repository, and
`mode`:

- `tracked` — vendored files must match the pinned ref; sync overwrites.
- `adapted` — we forked it; sync never overwrites, drift is reported so a
  human re-ports upstream changes deliberately.

A vendored skill lives at `skills/third-party/<directory>/<name>`, its catalog
entry carries the same `directory`, and the registry is empty today: an empty
`sources` map is valid and syncs clean. `/grilling`, `/code-review`, and
`/handoff` are still installed from `mattpocock/skills` separately, per the
README; vendoring that source (or any other) is a follow-up that adds a
`sources` entry, the `third-party` catalog category with its entries, and a
`scripts/sync_third_party.py` run.

`scripts/sync_third_party.py` reads the registry and fetches each source's
pinned ref from codeload.github.com: `--check` fails on tracked drift (CI
gate), `--write` refreshes tracked skills. The ref lives on the source, so
every skill from one upstream repository is pinned to the same commit by
construction. Files this repo adds on top of upstream (harness metadata
upstream does not ship) are preserved, and the sync copies the entire upstream
skill directory, not just `SKILL.md`.

Vendored skills follow upstream's authoring standard for their `SKILL.md`
prose — the catalog validator exempts the category from the `## Completion`
rule, because editing upstream prose would break tracked-mode sync. Everything
else this repo requires still applies: frontmatter names and descriptions,
`agents/openai.yaml` harness metadata, invocation flags, self-containment, and
catalog membership.

Per ADR-0008 vendored skills keep their upstream names: they are not about
RHDH.

## Consequences

- The mechanism is exercised by tests but carries no content: the installer
  shows only the six domain groups of ADR-0009 until a source is vendored.
- Vendoring a source later does not change the install story for anyone who
  already installs `mattpocock/skills` separately — the skills simply also
  become selectable from this pack's Third-party groups, one per source
  directory.
- Upstream improvements arrive only when someone bumps `ref` and runs
  `--write`; the pack deliberately lags upstream instead of drifting from it.
- An `adapted` skill is a fork: re-porting upstream changes is manual, and the
  sync report is the reminder, not the mechanism.
- Skill names are unique across sources: two vendors shipping the same name is
  a collision the catalog could not express, so the registry rejects it.
