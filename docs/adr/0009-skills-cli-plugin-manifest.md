# Skills CLI plugin manifest

**Status:** Accepted.

## Context

`npx skills add` shows a flat searchable list unless the cloned repository
declares plugins in `.claude-plugin/marketplace.json` (or `plugin.json`). The
CLI maps each listed skill path to a `pluginName` and switches the install
prompt to a grouped tree (select a category header to toggle every skill in
it).

This repository groups promoted skills into editorial categories in
`catalog.json` (`jira`, `plugins`, `ci`, `release`, `refinement`, `reference`,
`meta`).
Folders remain editorial for readers of the repo — skills still flatten into
host skill directories at install. The installer UI should follow the same
membership, with one exception: `reference` is a shared support layer other
skills invoke by name. Offering it as its own install group invites incomplete
installs (domain skills without the gate, API, or forge they call).

Shipping a Claude Code marketplace plugin was considered and rejected: the pack
installs through skills.sh / `npx skills` and `/setup-rhdh-skills`, not
`claude plugins install`.

The skills CLI does not yet honor a `depends` frontmatter field (proposed
upstream, not shipped). Until it does, the only way a category group install
pulls support skills is to list those paths in that category's plugin `skills`
array.

## Decision

Keep `.claude-plugin/marketplace.json` as a **generated projection** of
`skills/meta/setup-rhdh-skills/assets/catalog.json`:

- One marketplace plugin per **installable** catalog category (`reference` is
  omitted).
- Plugin `name` is the category label shown in the installer (`CI` spelled as an
  acronym so the CLI does not render "Ci").
- Each plugin lists that category's `./skills/<category>/<name>` paths, then the
  transitive `requiresSkills` closure of skills whose catalog category is
  `reference` (not `optionalSkills`).
- No root `plugin.json` umbrella — that shape implies a single Claude plugin
  bundle we do not ship.

Regenerate with `scripts/generate_plugin_manifest.py` (`--write` / `--check`).
Pre-commit rewrites the file when the catalog (or the manifest) changes; tests
fail on drift.

Document the directory in `.claude-plugin/README.md` so the files are not
removed as "leftover marketplace" scaffolding.

## Consequences

- `npx skills add redhat-developer/rhdh-skills` shows six collapsible groups
  (Jira, Plugins, CI, Release, Refinement, Meta). Selecting a group lists that
  domain's skills plus the reference skills they require.
- The `reference/` folder and catalog category remain for authors and
  validators; they are not an installer group.
- The skills CLI assigns each skill path one `pluginName` (last plugin that
  lists it wins). The generator therefore emits installable plugins in reverse
  catalog order so earlier categories (Jira, then Plugins, …) keep shared
  reference skills in their tree group. A Plugins-only or Meta-only select can
  still miss a shared skill that an earlier category also requires and therefore
  owns in the UI. Prefer installing every domain group you need, or the full
  set, until upstream `depends` can attach support skills to each selected
  skill regardless of group.
- Category membership has one source of truth: the setup catalog. The manifest
  cannot invent skills the catalog does not list.
- Contributors must not treat `.claude-plugin/` as a product surface for Claude
  Code plugin distribution.
