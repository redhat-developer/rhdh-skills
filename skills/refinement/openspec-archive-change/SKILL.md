---
name: openspec-archive-change
description: >-
  Archives a completed OpenSpec change into openspec/changes/archive/, after
  confirming artifact and task completion and offering to sync any delta
  specs into the main specs first. Use for "archive this change", "finalize
  <change>", or "this is done, wrap it up". Warns but does not block on
  incomplete artifacts or tasks — the user decides whether to proceed anyway.
compatibility: "Requires the openspec CLI on PATH."
---

# Archive an OpenSpec change

Move a change from active to archived, confirming completeness and offering
to sync its delta specs into the long-lived main specs first.

## Steps

1. **Select the change.** If not given, run `openspec list --json`, show only
   active (non-archived) changes with their schema, and let the user choose.
   Never guess.
2. **Check artifact completion:** `openspec status --change "<name>" --json`
   — read `schemaName` and each artifact's status. If any are not `done`,
   show a warning listing them and confirm the user wants to proceed anyway.
3. **Check task completion.** Read the tasks file (typically `tasks.md`),
   count `- [ ]` vs `- [x]`. If incomplete tasks exist, warn with the count
   and confirm before proceeding. No tasks file means no warning needed.
4. **Assess delta spec sync state.** Check
   `openspec/changes/<name>/specs/`. If delta specs exist, compare each
   against its main spec at `openspec/specs/<capability>/spec.md`, determine
   what would change, and show a combined summary before offering: "Sync now
   (recommended)" vs "Archive without syncing" (or, if already synced,
   "Archive now" / "Sync anyway" / "Cancel"). If the user chooses sync,
   delegate via the Task tool (`subagent_type: general-purpose`) with the
   prompt "Invoke `/openspec-sync-specs` for change '<name>'" plus the
   analyzed delta summary — then archive regardless of the sync choice made.
5. **Perform the archive:**

   ```bash
   mkdir -p openspec/changes/archive
   mv openspec/changes/<name> openspec/changes/archive/YYYY-MM-DD-<name>
   ```

   Use the current date. If the target directory already exists, fail with an
   error and suggest renaming the existing archive or using a different date.
   `.openspec.yaml` moves with the directory automatically.
6. **Display a summary:** change name, schema, archive location, whether
   specs were synced, and any warnings from steps 2-3.

## Output

```
## Archive Complete

**Change:** <change-name>
**Schema:** <schema-name>
**Archived to:** openspec/changes/archive/YYYY-MM-DD-<name>/
**Specs:** synced to main specs / no delta specs / sync skipped
```

## Guardrails

- Always prompt for change selection if not given — never auto-select.
- Warnings inform and require confirmation; they never silently block.
- Preserve `.openspec.yaml` when moving to archive.
- If delta specs exist, always run the sync assessment and show the combined
  summary before prompting, regardless of the user's eventual choice.

## Completion

Complete when the change directory has moved to
`openspec/changes/archive/YYYY-MM-DD-<name>/`, any chosen spec sync has run,
and the summary — including every warning surfaced along the way — has been
shown to the user.
