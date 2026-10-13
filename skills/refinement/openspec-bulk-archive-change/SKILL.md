---
name: openspec-bulk-archive-change
description: >-
  Archives several completed OpenSpec changes in one batch, detecting and
  agentically resolving spec conflicts by checking the codebase for what is
  actually implemented. Use for "archive these changes", "clean up finished
  changes", or "archive everything that's done" when more than one change
  needs archiving at once. For a single change, use openspec-archive-change
  instead.
compatibility: "Requires the openspec CLI on PATH."
---

# Bulk-archive OpenSpec changes

Archive multiple parallel changes at once, resolving delta-spec conflicts
between them by checking which is actually implemented rather than failing or
guessing.

## Steps

1. **Get active changes:** `openspec list --json`. If none, tell the user and
   stop.
2. **Let the user select** (multi-select, never auto-select): show each
   change with its schema, offer "All changes", and allow any number of
   selections (1+ works; 2+ is the typical case).
3. **Gather status for every selected change**: artifact status
   (`openspec status --change "<name>" --json`), task completion (count
   `- [ ]`/`- [x]` in `tasks.md`, or note "No tasks" if absent), and delta
   specs under `openspec/changes/<name>/specs/` with their requirement names.
4. **Detect spec conflicts.** Build `capability -> [changes touching it]`; a
   conflict is 2+ selected changes touching the same capability.
5. **Resolve each conflict agentically**: read each conflicting change's
   delta spec, search the codebase for implementation evidence, and decide —
   only one implemented -> sync that one; both implemented -> apply in
   chronological order (older first, newer takes precedence); neither
   implemented -> skip spec sync for that capability and warn. Record the
   resolution and its rationale per conflict.
6. **Show a consolidated status table** (change, artifacts, tasks, specs,
   conflicts, ready/warn), with conflict resolutions and incomplete-change
   warnings called out beneath it.
7. **Confirm the batch operation** with a single prompt: "Archive N changes?"
   offering "Archive all N", "Archive only the ready ones (skip incomplete)",
   or "Cancel". Make clear that choosing "all" archives incomplete changes
   with warnings, not silently.
8. **Execute per confirmed change**, in the resolved order: if the change has
   delta specs to sync, delegate the merge to `/openspec-sync-specs` (via the
   Task tool, `subagent_type: general-purpose`, with the prompt "Invoke
   `/openspec-sync-specs` for change '<name>'" plus this change's resolved
   conflict decision from step 5) — conflict detection and resolution stay
   here; the merge mechanics belong to that skill. Then
   `mkdir -p openspec/changes/archive && mv openspec/changes/<name>
   openspec/changes/archive/YYYY-MM-DD-<name>`. Track success/failed/skipped
   per change; an existing archive target fails that change but does not stop
   the batch.
9. **Display the final summary**: archived changes with their destinations,
   skipped changes with the reason, failed changes with the error, and a spec
   sync summary (deltas synced, conflicts resolved).

## Guardrails

- Always prompt for selection — never auto-select, even for "archive
  everything".
- Detect conflicts before confirming the batch, and resolve them by checking
  the codebase, not by guessing or by change order alone.
- Preserve `.openspec.yaml` on every archived change.
- One failure must not abort the rest of the batch.

## Completion

Complete when every selected-and-confirmed change has a recorded outcome —
archived, skipped, or failed with a reason — and the spec-sync summary
accounts for every capability that had a conflict.
