---
name: openspec-sync-specs
description: >-
  Syncs a change's delta specs into the long-lived main specs under
  openspec/specs/, without archiving the change. Use for "sync specs for
  <change>", "update main specs with these changes", or as a step inside
  openspec-archive-change/openspec-bulk-archive-change. This is agent-driven
  intelligent merging (partial updates, not wholesale replacement) — not a
  mechanical diff apply.
compatibility: "Requires the openspec CLI on PATH."
---

# Sync delta specs to main specs

Read delta specs and directly edit main specs to apply their intent —
allowing partial updates like adding one scenario without copying an entire
requirement.

## Steps

1. **Select the change.** If not given, run `openspec list --json`, show
   changes that have delta specs under `specs/`, and let the user choose.
   Never guess.
2. **Find delta specs** at `openspec/changes/<name>/specs/*/spec.md`. Each may
   contain `## ADDED Requirements`, `## MODIFIED Requirements`,
   `## REMOVED Requirements`, `## RENAMED Requirements` (FROM:/TO: format). If
   none found, tell the user and stop.
3. **For each capability with a delta spec**, read both the delta and the
   main spec at `openspec/specs/<capability>/spec.md` (may not exist yet),
   then apply intelligently:
   - **ADDED** — add if new; if it already exists, update it to match
     (treat as an implicit MODIFIED).
   - **MODIFIED** — find the requirement and apply the changes: add
     scenarios, modify existing ones, or change the description. Preserve
     content the delta doesn't mention.
   - **REMOVED** — remove the entire requirement block.
   - **RENAMED** — find the FROM requirement, rename to TO.
   - If the capability has no main spec yet, create
     `openspec/specs/<capability>/spec.md` with a Purpose section (brief, can
     be TBD) and the ADDED requirements.
4. **Show a summary**: which capabilities were updated and what changed
   (added/modified/removed/renamed requirements).

## Key principle: intelligent merging

The delta represents intent, not a wholesale replacement. To add a scenario,
include just that scenario under MODIFIED — don't copy existing ones. Use
judgment to merge sensibly; the operation should still be idempotent (running
it twice gives the same result).

## Guardrails

- Read both delta and main specs before changing anything.
- Preserve existing content the delta doesn't mention.
- Ask for clarification if intent is unclear rather than guessing.
- Show what's changing as you go.

## Completion

Complete when every delta spec found in step 2 has been applied to its main
spec (or a new main spec created), the summary lists every capability
touched, and re-running the sync on the same inputs would produce no further
changes.
