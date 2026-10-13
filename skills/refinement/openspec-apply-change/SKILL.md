---
name: openspec-apply-change
description: >-
  Implements the pending tasks of an OpenSpec change against its proposal,
  specs, and design, looping until done or blocked. Use for "implement this
  change", "start/continue implementing", "work through the tasks", or "keep
  going on <change>". Can be invoked any time tasks exist, before or after
  other artifacts are finished, and interleaved with artifact updates — it is
  not phase-locked to a single point in the change's lifecycle.
compatibility: "Requires the openspec CLI on PATH."
---

# Implement OpenSpec change tasks

Work through a change's task checklist against real code, one task at a time,
checking each off only once it is actually done.

## Steps

1. **Select the change.** Use a given name; otherwise infer from context, or
   auto-select if only one active change exists. If ambiguous, run
   `openspec list --json` and let the user choose. Always announce which
   change is in use.
2. **Check status:** `openspec status --change "<name>" --json` — read
   `schemaName` and which artifact holds the tasks.
3. **Get apply instructions:**

   ```bash
   openspec instructions apply --change "<name>" --json
   ```

   Returns `contextFiles` (artifact ID -> file paths), task progress, the
   task list with status, and a dynamic instruction. If `state: "blocked"`
   (missing artifacts), suggest `/openspec-continue-change`. If
   `state: "all_done"`, congratulate and suggest `/openspec-archive-change`.
4. **Read every file listed under `contextFiles`** before starting — for
   `rhdh-spec-driven` that is proposal, specs, design, and tasks.
5. **Choose an execution mode** for this run, per `/rhdh-spec-driven-schema`'s
   `schema.yaml` apply block: direct mode for mechanical, low-risk work; team
   mode (implementer + independent verifier subagents) for semantically
   complex, ADR-bound, or broad cross-layer work. Announce the choice and
   rationale before making changes; do not silently switch mid-run.
6. **Work through pending tasks** until done or blocked: show which task is
   active, make minimal focused changes, flip `- [ ]` to `- [x]` immediately
   on completion, continue to the next task. Pause on an unclear task,
   a design issue surfaced by implementation, an error, or user interruption.
7. **Journal as you go**, invoking `/openspec-journal`: `mode.chosen` once at
   start, `task.start`/`task.complete` per task (or per assigned range in team
   mode), `verifier.result` per verdict in team mode, `task.blocked` on pause,
   `decision` for load-bearing calls, `handoff` as the last line before
   stopping and the first line on resume. Also keep the default turn
   bookending (`turn.start`/`turn.end`) described there.
8. **On completion or pause, show status**: tasks completed this session,
   overall progress (N/M), and either a suggestion to archive or an
   explanation of the pause with options.

## Output

During implementation, show each task starting and completing. On completion,
show final progress and readiness to archive. On pause, show the issue, 2-3
options, and "Other approach", then wait.

## Guardrails

- Always read context files before starting.
- Keep changes minimal and scoped to each task.
- Pause on errors, blockers, or unclear requirements — never guess.
- Use `contextFiles` from the CLI output; never assume file names.
- If implementation reveals a design issue, pause and suggest an artifact
  update rather than silently diverging from the design.

## Completion

Complete when every task attempted this session is either checked off with
matching code changes, or explicitly reported as paused with the reason and
options — never left silently half-done — and the apply-phase journal events
for the session were written.
