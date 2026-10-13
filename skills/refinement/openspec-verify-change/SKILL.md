---
name: openspec-verify-change
description: >-
  Verifies that an implementation matches its OpenSpec change's artifacts —
  completeness (tasks, spec coverage), correctness (requirement and scenario
  coverage), and coherence (design adherence, pattern consistency) —
  post-implementation, before archiving. Use for "verify this change", "does
  the code match the spec", or "is this ready to archive". For pre-
  implementation artifact-to-artifact consistency, use openspec-audit-change
  instead.
compatibility: "Requires the openspec CLI on PATH."
---

# Verify an OpenSpec implementation

Check that code actually satisfies a change's specs, tasks, and design —
after implementation, before archiving — and report gaps with actionable,
file-referenced recommendations.

## Steps

1. **Select the change.** If not given, run `openspec list --json`, show
   changes with implementation tasks, mark ones with incomplete tasks
   "(In Progress)", and let the user choose. Never guess.
2. **Check the schema:** `openspec status --change "<name>" --json`.
3. **Load artifacts:** `openspec instructions apply --change "<name>" --json`
   returns `contextFiles` (artifact ID -> paths); read everything available.
4. **Verify completeness.** Tasks: parse `- [ ]`/`- [x]` in every
   `contextFiles.tasks` file; each incomplete task is CRITICAL with a
   recommendation ("Complete task: <description>" or "Mark done if already
   implemented"). Spec coverage: for each requirement in delta specs, search
   the codebase for implementation evidence; an apparently-unimplemented
   requirement is CRITICAL ("Requirement not found: <name>").
5. **Verify correctness.** For each requirement, search for implementation
   evidence and assess whether it matches intent; a divergence is WARNING
   with a file/line-referenced recommendation. For each scenario, check
   whether code and tests cover it; an uncovered scenario is WARNING.
6. **Verify coherence.** If `design.md` exists, extract key decisions and
   check the implementation follows them; a contradiction is WARNING. No
   `design.md` means skipping this check and noting it. Check new code
   against project naming/structure/style conventions; a significant
   deviation is SUGGESTION.
7. **Generate the report**: a summary scorecard (Completeness /
   Correctness / Coherence), issues grouped CRITICAL / WARNING / SUGGESTION
   each with a specific recommendation and `file.ts:123`-style references,
   and a final assessment — "X critical issue(s) found, fix before
   archiving" / "No critical issues, Y warning(s) to consider, ready for
   archive" / "All checks passed, ready for archive".

## Heuristics

Completeness leans on objective checklist items; correctness and coherence
use keyword search and reasonable inference, not certainty. When uncertain,
prefer SUGGESTION over WARNING, WARNING over CRITICAL. Every issue needs a
specific, actionable recommendation — never "consider reviewing".

## Graceful degradation

Only `tasks.md` exists -> verify task completion only. Tasks + specs exist ->
skip design coherence. Full artifacts -> verify all three dimensions. Always
state which checks were skipped and why.

## Completion

Complete when all three dimensions were assessed (or their skip was stated
and why), every issue has a severity, a file reference, and an actionable
recommendation, and the final assessment names whether the change is ready
to archive.
