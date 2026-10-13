# Full Backstage Upgrade

Read `package.json` and `backstage.json` before changing dependencies. Use
`backstage-cli versions:bump` for aligned package resolution. For an RHDH
target, the compatibility answer established in `SKILL.md` is authoritative; do
not upgrade past the Backstage version shipped by that RHDH release.

<prerequisites>
- Plugin or app with `@backstage/*` dependencies
- `yarn` or `npm` available
- `@backstage/cli` installed (or available via `npx`)
- Network access to fetch release manifests
</prerequisites>

<process>

## Phase 1: Discover

Load `references/discover-versions.md` and identify:

- Current `@backstage/*` versions
- Base Backstage release version
- Any version misalignment across packages

Report findings to the user before proceeding.

## Phase 2: Determine Target

Load `references/determine-target.md`.

- If the user chose **"latest for my RHDH version"**: use the compatibility
  answer established in `SKILL.md`. If it is still unresolved, invoke
  `/rhdh-context` by name for the matrix, or ask the user for both target
  versions.
- If the user chose **"specific version"**: use the version they provided.

Compare current vs target. If they match, report "Already on target version" and stop.

## Phase 3: Bump Dependencies

Load `references/bump-deps.md`. Inventory every `resolutions` and `overrides`
entry and capture its provenance and pre-bump dependency paths before running
the selected repository wrapper or CLI. After installation, compare the graph
for every entry and record its keep, update, or remove decision and evidence.
Review dependency range style, `package.json`, and the lockfile before
continuing. Complete every migration or dedupe step selected for the checkout
before editing source.

## Phase 4: Migrate Moved Packages

Load `references/migrate-packages.md` and run:

```bash
yarn backstage-cli versions:migrate
```

Check for any remaining old-namespace imports.

## Phase 5: Fix Breaking Changes

Load `references/fix-breaking-changes.md`.

1. Identify all Backstage releases between the old and new version
2. Read the changelogs for breaking changes
3. Search the plugin source for affected APIs
4. Apply fixes

If the checkout contains New Frontend System code — or an NFS migration
directed you here — invoke `/backstage-api-changes` by name and apply its
checklist. It owns the NFS API deltas; this workflow owns version numbers.

## Phase 6: Verify

Load `references/verify-upgrade.md` and run every check it selects for the
checkout. Fix any failures before reporting success.

</process>

<success_criteria>

- All `@backstage/*` deps match the target release
- No deprecated or moved package imports remain
- Every resolution and override has a documented provenance, before/after graph
  comparison, decision, reason, and verification evidence
- Every build, test, lint, formatting, monorepo, and generation check selected
  for the checkout passes
- No console errors when running the dev app (if applicable)
</success_criteria>
