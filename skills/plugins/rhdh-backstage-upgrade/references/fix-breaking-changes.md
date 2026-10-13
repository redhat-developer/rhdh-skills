# Fix Breaking Changes

## Find relevant changelogs

Identify the Backstage versions between your current and target release. For each version, check the changelog:

- **Release notes:** `https://github.com/backstage/backstage/blob/master/docs/releases/v<VERSION>.md`
- **Detailed changelog:** `https://github.com/backstage/backstage/blob/master/docs/releases/v<VERSION>-changelog.md`

Focus on the **"Breaking Changes"** and **"Minor Changes"** sections. Patch changes rarely require code updates.

## Process

For each breaking change in the changelogs:

1. **Read the change description** — understand what was renamed, removed, or restructured
2. **Search the plugin's source** — `grep -r '<old API name>' src/` to check if the plugin is affected
3. **Apply the fix** — follow the changelog's migration guidance
4. **Verify** — `yarn tsc` after each fix to confirm the type error is resolved

## Common breaking change patterns

| Pattern | What to look for | Fix |
|---------|-----------------|-----|
| Renamed export | `import { OldName }` → `import { NewName }` | Update import |
| Moved package | `@backstage/plugin-x` → `@backstage-community/plugin-x` | Run `versions:migrate` |
| Removed API | `import { removedFn }` | Replace with recommended alternative from changelog |
| Changed signature | Type errors on function calls | Update call site per changelog |
| New required field | Missing property errors | Add the new field |
| New or renamed service factory | Missing backend service errors | Compare `@backstage/backend-defaults` exports and update the checkout's default service factory registration |

When a failure points to an `@red-hat-developer-hub/*` package, inspect its peer
ranges and release metadata. Choose the smallest published version compatible
with the target Backstage release rather than upgrading to latest by default.

## Per-package changelogs

Each `@backstage/*` package has its own `CHANGELOG.md` in the Backstage repo. If `yarn tsc` flags errors in a specific package, check:

```
https://github.com/backstage/backstage/blob/master/packages/<package-name>/CHANGELOG.md
https://github.com/backstage/backstage/blob/master/plugins/<plugin-name>/CHANGELOG.md
```

## Composability with other skills

If a migration workflow directed you here, apply both checklists:

1. The upstream Backstage changelogs (this file)
2. The New Frontend System checklist owned by `/backstage-api-changes` — invoke it by name

The upstream changelogs cover all Backstage breaking changes. That checklist covers the NFS blueprint and param changes that do not appear in the upstream changelog.

## Backstage Upgrade Helper

For visual diffs between Backstage versions, use the Upgrade Helper tool:

```
https://backstage.github.io/upgrade-helper/
```

Select your current and target versions to see a diff of all template changes in `create-app`.
