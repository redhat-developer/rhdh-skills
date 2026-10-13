---
name: openspec-continue-change
description: >-
  Creates exactly the next ready OpenSpec artifact for a change, one at a
  time — proposal, then specs or design (siblings), then tasks. Use for
  "what's the next artifact", "create the next artifact", "draft the next
  OpenSpec file", or when the user wants to progress artifacts step by step
  rather than generating everything at once. Stops after one artifact. Does
  not implement code.
compatibility: "Requires the openspec CLI on PATH."
---

# Continue an OpenSpec change

Create one artifact — the next one whose dependencies are satisfied — and
stop, so the user reviews each step before the next is generated.

## Steps

1. **Select the change.** If not named or inferable from context, run
   `openspec list --json` and ask the user to pick from the most recently
   modified 3-4 changes, marking the most recent as "(Recommended)". Never
   guess.
2. **Check status:**

   ```bash
   openspec status --change "<name>" --json
   ```

   Read `schemaName`, `artifacts[].status`, and `isComplete`. Specs and design
   each depend only on proposal — when both are `ready`, pick one (either
   order is valid); do not treat YAML list order as a hard dependency.
3. **Act on status:**
   - **All complete (`isComplete: true`)** — congratulate, show final status,
     suggest implementing (`/openspec-apply-change`) or archiving
     (`/openspec-archive-change`). Stop.
   - **An artifact is `ready`** — pick one ready artifact and create it by
     following the artifact creation loop in `/rhdh-spec-driven-schema`.
     Create exactly one artifact, then stop.
   - **Nothing is ready and nothing is complete** — this should not happen
     with a valid schema; show status and suggest checking for a schema
     issue.
4. **Show progress:** `openspec status --change "<name>"`.

## Output

After each invocation: which artifact was created, the schema in use, current
progress (N/M complete), and what is now unlocked. Close with: "Want to
continue? Just ask me to continue or tell me what to do next."

## Guardrails

- Create exactly one artifact per invocation — never more.
- Never skip required dependencies; when multiple artifacts are ready (specs
  and design after proposal), either order is fine.
- If context for the artifact is unclear, ask before creating it.

## Completion

Complete when exactly one artifact was written (verified to exist on disk)
and the user has seen updated progress and what it unlocked — or, if already
complete, when that state was reported without attempting a write.
