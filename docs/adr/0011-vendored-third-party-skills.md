# Vendored third-party skills

**Status:** Accepted.

## Context

The pack used to depend on three skills installed from outside it: `code-review`,
`grilling`, and `handoff` from `mattpocock/skills`. `catalog.json` declared them
under `pack.requiredExternalSkills`, the README told users to run a second
`npx skills add mattpocock/skills` command, and `setup-rhdh-skills` planned that
second install operation.

The new delivery surface changes the math: skills reach engineers through Slack
as plugins on authorized Red Hat repositories, and that surface exposes this
repository's pack — not arbitrary upstream sources. A skill the workflow cannot
install from the pack is a skill the workflow cannot deliver. The same applies
to any consumer who wants one install command instead of two.

Upstream is MIT-licensed, so vendoring and modifying are both permitted.

The `skills` CLI's experimental lockfile sync (`skills-lock.json`,
`experimental_install`) was considered and rejected: it keeps the skills outside
the pack, so the Slack surface would still need to run network installs against
sources it does not authorize, and a verbatim-only link cannot carry the small
adaptations we sometimes need.

## Decision

Vendor third-party skills into `skills/third-party/` as a promoted catalog
category, with provenance and sync policy recorded per skill in
`UPSTREAM.toml`:

- `source` — the `owner/repo` the skill came from.
- `path` — the skill's directory inside that repository.
- `ref` — the pinned upstream commit the vendored copy matches.
- `mode` — `tracked` (vendored files must match the pinned ref; sync
  overwrites) or `adapted` (we forked it; sync never overwrites, drift is
  reported so a human re-ports upstream changes deliberately).

`scripts/sync_third_party.py` fetches each pinned ref from codeload.github.com:
`--check` fails on tracked drift (CI gate), `--write` refreshes tracked skills.
Refreshing means editing `ref` to a new commit and running `--write`; the diff
is reviewed like any other change. Files this repo adds on top of upstream
(`UPSTREAM.toml` itself, harness metadata upstream does not ship) are preserved.

Vendored skills follow upstream's authoring standard for their `SKILL.md`
prose — the catalog validator exempts the category from the `## Completion`
rule, because editing upstream prose would break tracked-mode sync. Everything
else this repo requires still applies: frontmatter names and descriptions,
`agents/openai.yaml` harness metadata, invocation flags, self-containment, and
catalog membership. `pack.requiredExternalSkills` is empty; the former external
dependencies are ordinary `requiresSkills` edges now.

Per ADR-0008 these skills keep their upstream names: they are not about RHDH.

## Consequences

- One install source covers the complete pack: `npx skills add
  redhat-developer/rhdh-skills`. The installer shows a seventh group,
  Third-party, alongside the six domain groups of ADR-0009.
- A Jira-only or Plugins-only group install no longer pulls `grilling` or
  `code-review` implicitly — they sit in their own group. The ADR-0009 advice
  to install the groups you need (or the full set) still stands.
- Upstream improvements arrive only when someone bumps `ref` and runs
  `--write`; the pack deliberately lags upstream instead of drifting from it.
- An `adapted` skill is a fork: re-porting upstream changes is manual, and the
  sync report is the reminder, not the mechanism.
- New third-party skills land the same way: copy from a pinned ref, write
  `UPSTREAM.toml`, add the catalog entry. A skill without `UPSTREAM.toml`
  fails sync discovery.
