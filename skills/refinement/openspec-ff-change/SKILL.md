---
name: openspec-ff-change
description: >-
  Fast-forwards an OpenSpec change by generating every remaining artifact
  needed before implementation — proposal, specs, design, and tasks — in one
  pass, for a brand-new or an existing change, with progress tracked via
  TodoWrite. Use for "fast-forward this change", "generate all the artifacts
  now", "create every remaining artifact", or "get this ready to implement".
compatibility: "Requires the openspec CLI on PATH."
---

# Fast-forward an OpenSpec change

Generate every artifact the schema requires before implementation can start,
without pausing between them, then hand off to implementation.

## Steps

1. **Ensure the project schema is installed.** Check whether
   `openspec/config.yaml` and `openspec/schemas/rhdh-spec-driven/` already
   exist. Only if either is missing, invoke `/rhdh-spec-driven-schema` and run
   its project-install step. Then confirm with `openspec schemas --json`.
2. **Get the change name or description.** Derive a kebab-case name from a
   description if no name was given (e.g. "add user authentication" ->
   `add-user-auth`); do not proceed without knowing what to build.
3. **Create the change directory** (skip if it already exists — see
   Guardrails): `openspec new change "<name>"` (default schema from
   `openspec/config.yaml`, or pass `--schema rhdh-spec-driven`).
4. **Get the build order:**

   ```bash
   openspec status --change "<name>" --json
   ```

   Read `applyRequires` (artifact IDs needed before implementation) and
   `artifacts` (status + dependencies for each). Specs and design are
   siblings: after proposal, either may be ready; create them in either order
   once their dependencies are satisfied.
5. **Create every required artifact in dependency order.** Track progress
   with TodoWrite. For each artifact whose dependencies are satisfied, follow
   the artifact creation loop in `/rhdh-spec-driven-schema` — read
   dependencies, use the template,
   apply context/rules without copying them into the file, write to
   `outputPath`. Re-check status after each write; stop once every ID in
   `applyRequires` reports `status: "done"`.
6. **If an artifact needs input the description didn't cover,** ask — but
   prefer a reasonable default to keep momentum; this skill exists to avoid
   stopping between artifacts.
7. **Show final status:** `openspec status --change "<name>"`.

## Output

Change name and location, every artifact created with a one-line description,
"All artifacts created! Ready for implementation.", and: "Run
`/openspec-apply-change` to start working on the tasks."

## Guardrails

- Create every artifact `applyRequires` needs — not a subset.
- Always read dependency artifacts before creating the next one.
- Verify each artifact file exists after writing, before moving on.
- If a change with that name already exists, do not re-scaffold or overwrite
  artifacts already written. Read current status and fill only the remaining
  `applyRequires` artifacts in dependency order — this skill finishes an
  existing change as well as it starts a new one.

## Completion

Complete when every artifact ID in `applyRequires` shows `status: "done"` in
`openspec status`, each was verified to exist on disk, and the user has been
pointed at `/openspec-apply-change` to start implementation.
