# Bump Backstage Dependencies

## Primary command

Before running either command, complete the pre-bump inventory and dependency
graph capture in **Audit resolutions and overrides** below.

Use a repository-provided wrapper when one exists; it may enforce pinning and
update generated metadata that the CLI does not know about. In
`redhat-developer/rhdh`, run:

```bash
yarn versions:bump --release <version>
```

Otherwise run:

```bash
yarn backstage-cli versions:bump --release <version>
```

Replace `<version>` with the validated target Backstage release (e.g., `1.45.3`).

This command:

- Reads the release manifest for the target version
- Updates all `@backstage/*` packages in `package.json` to their correct versions for that release
- Runs `yarn install` to update the lockfile
- Runs `versions:migrate` to handle moved packages (unless `--skipMigrate`)

## Useful flags

| Flag | Effect |
|------|--------|
| `--release <version>` | Target a specific release (default: `main`) |
| `--pattern '@{backstage,roadiehq}/*'` | Include additional package scopes |
| `--skipInstall` | Skip `yarn install` (useful if you want to review changes first) |
| `--skipMigrate` | Skip automatic migration of moved packages |

## Workspace / monorepo usage

In a monorepo (like `rhdh-plugins`), run from the workspace root. The command updates all packages across the workspace.

If you only want to bump a single plugin package, you can run it from that package's directory -- but be aware that shared workspace deps may need alignment too.

## Preserve dependency style

Record whether each dependency section uses exact versions, carets, tildes, or
workspace ranges before the bump. `versions:bump` may rewrite that style. Restore
the existing convention after the command, then review every changed dependency
and the lockfile. In `redhat-developer/rhdh`, `@backstage/*` dependencies remain
exact pins.

## Audit resolutions and overrides

Audit every `resolutions` and `overrides` entry in every upgrade root discovered
before the bump. Do not limit the inventory to packages changed directly by
`versions:bump`; an obsolete transitive pin may only become visible when the
new dependency graph no longer reaches it.

Before the bump:

1. Record each entry's root, field, selector, and replacement value.
2. Capture why the package is present and which dependency paths the entry
   changes. Use the package manager's graph command, such as `yarn why -R
   <package>` or `npm explain <package>`.
3. Trace the entry to its introducing commit with history such as `git log -S
   '<selector>' -- <manifest>` and `git blame`, then follow any linked issue,
   advisory, or patch comment. State the compatibility, security, singleton, or
   build condition it was meant to enforce.

After the bump and install, rerun the graph query for every inventoried entry and
compare its dependency paths, requested ranges, and resolved versions with the
pre-bump graph. Classify every entry as **keep**, **update**, or **remove**:

- Keep or update it only when the original condition still applies to the new
  graph; record the graph evidence and the regression check that protects it.
- Remove it only after testing the graph without it and confirming that the
  original condition no longer applies. Run the relevant regression check as
  well as install and build. A green install or build alone does not prove that
  a pin is obsolete.

Report one row per entry with: root, field and selector, provenance, before and
after dependency paths, decision, reason, and verification evidence. Entries
that are unchanged still require a recorded keep reason.

## What it doesn't do

- Fix breaking API changes in your source code (see `fix-breaking-changes.md`)
- Update non-`@backstage/*` dependencies
- Migrate your code from legacy to NFS APIs

## Troubleshooting

**"Could not fetch release manifest"** — Check network connectivity. The CLI fetches from `https://versions.backstage.io`. You can also set `BACKSTAGE_MANIFEST_FILE` to a local file.

**Lockfile conflicts** — Diagnose the conflicting dependency or resolution and
rerun the bump or install. Do not delete a committed lockfile to hide the
conflict.

**Version not found** — Verify the release version exists. Check available releases at `https://github.com/backstage/backstage/releases`.

**Workspace resolution errors** — In monorepos, ensure all workspace packages are using compatible version ranges. Run `yarn dedupe @backstage/*` after the bump.

Every step selected for the checkout must succeed before manual source fixes
begin. This includes install, any required migration, and dedupe when the
repository wrapper runs it or workspace resolution requires it. If a selected
step fails, diagnose it and rerun that phase. Do not use build errors from a
partial install as migration guidance.
