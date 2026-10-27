# Vendored third-party skills

**Status:** Accepted.

## Context

Skills reach engineers through Slack as plugins on authorized Red Hat
repositories, and that surface exposes this repository's pack — not arbitrary
upstream sources. A skill the workflow cannot install from the pack is a skill
the workflow cannot deliver. The same applies to any consumer who wants one
install command instead of several.

`mattpocock/skills` is MIT-licensed, so vendoring and modifying are both
permitted.

The `skills` CLI's experimental lockfile sync (`skills-lock.json`,
`experimental_install`) was considered and rejected: it keeps the skills outside
the pack, so the Slack surface would still need to run network installs against
sources it does not authorize, and a verbatim-only link cannot carry the small
adaptations we sometimes need.

## Decision

Vendor third-party skills into `skills/third-party/` as a promoted catalog
category, grouped one directory per upstream source, with all provenance and
sync policy in one registry: `skills/third-party/registry.json`.

The registry's `sources` map records each upstream `owner/repo` with the
`directory` its skills are vendored under, one pinned `ref`, and its `license`.
Its `skills` array records each vendored skill's `name`, `source`, `path`
inside that repository, and `mode`:

- `tracked` — vendored files must match the pinned ref; sync overwrites.
- `adapted` — we forked it; sync never overwrites, drift is reported so a
  human re-ports upstream changes deliberately.

A vendored skill lives at `skills/third-party/<directory>/<name>`, and its
catalog entry carries the same `directory`. The ref lives on the source, not
the skill: every skill vendored from one upstream repository is pinned to the
same commit by construction, and bumping a source refreshes all of its skills
at once.

`scripts/sync_third_party.py` reads the registry and fetches each source's
pinned ref from codeload.github.com: `--check` fails on tracked drift (CI
gate), `--write` refreshes tracked skills. Refreshing means editing the
source's `ref` to a new commit and running `--write`; the diff is reviewed
like any other change. Files this repo adds on top of upstream (harness
metadata upstream does not ship) are preserved.

Vendored skills follow upstream's authoring standard for their `SKILL.md`
prose — the catalog validator exempts the category from the `## Completion`
rule, because editing upstream prose would break tracked-mode sync. Everything
else this repo requires still applies: frontmatter names and descriptions,
`agents/openai.yaml` harness metadata, invocation flags, self-containment, and
catalog membership.

Per ADR-0008 these skills keep their upstream names: they are not about RHDH.

## Consequences

- One install source covers the complete pack: `npx skills add
  redhat-developer/rhdh-skills`. Third-party skills install as one selectable
group per vendored source (`mattpocock-skills` today), alongside the six
  domain groups of ADR-0009.
- A Jira-only or Plugins-only group install does not pull `grilling` or
  `code-review` — they sit in their source's group. The ADR-0009 advice
  to install the groups you need (or the full set) still stands.
- Upstream improvements arrive only when someone bumps `ref` and runs
  `--write`; the pack deliberately lags upstream instead of drifting from it.
- An `adapted` skill is a fork: re-porting upstream changes is manual, and the
  sync report is the reminder, not the mechanism.
- New third-party skills land the same way: add the source and skill to
  `registry.json`, copy the files from the pinned ref into the source's
  directory, add the catalog entry with its `directory`. A skill directory
  missing from the registry fails sync.
