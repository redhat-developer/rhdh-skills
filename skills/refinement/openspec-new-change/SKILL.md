---
name: openspec-new-change
description: >-
  Scaffolds a new OpenSpec change directory and shows the first artifact's
  template without writing it. Use for "start a new change", "scaffold a
  change", "set up a change for X", or "what's the first artifact I need" —
  when the user wants the folder and the first template, not a drafted
  proposal. Creates the change directory and stops — it does not draft or
  write any artifact content, and it does not implement code.
compatibility: "Requires the openspec CLI on PATH."
---

# Start a new OpenSpec change

Scaffold a change directory and hand the caller the first artifact's template,
then stop — drafting content is a separate turn.

## Steps

1. **Ensure the project schema is installed.** Check whether
   `openspec/config.yaml` and `openspec/schemas/rhdh-spec-driven/` already
   exist. Only if either is missing, invoke `/rhdh-spec-driven-schema` and run
   its project-install step. Then confirm with `openspec schemas --json` that
   `rhdh-spec-driven` is listed.
2. **Get the change name.** If the user's request already names it or
   describes what they want to build, derive a kebab-case name (e.g. "add
   user authentication" -> `add-user-auth`). Otherwise ask what they want to
   build or fix; do not proceed without knowing.
3. **Pick the schema.** Prefer `rhdh-spec-driven` (now on disk). Pass
   `--schema rhdh-spec-driven`, or omit `--schema` to take the configured
   default from `openspec/config.yaml`. If the user names another available
   schema from `openspec schemas --json`, use that instead.
4. **Create the change directory:**

   ```bash
   openspec new change "<name>" [--schema <name>]
   ```

   This scaffolds `openspec/changes/<name>/` with the selected schema.
5. **Show status:**

   ```bash
   openspec status --change "<name>"
   ```

6. **Get the first artifact's instructions.** Find the first artifact with
   `status: "ready"` in the status output (schema-dependent — `proposal` for
   `rhdh-spec-driven`), then:

   ```bash
   openspec instructions <first-artifact-id> --change "<name>" --json
   ```

   Read `/rhdh-spec-driven-schema` for what the `context`, `rules`, and
   `template` fields in that response mean before summarizing them.
7. **Stop and wait for user direction.**

## Output

Summarize: change name and location, schema and its artifact sequence
(`proposal -> {specs, design} -> tasks` for `rhdh-spec-driven` — specs and
design are siblings that each depend only on proposal), current status (0/N
artifacts complete), and the template for the first artifact. Close with:
"Ready to create the first artifact? Describe what this change is about and
I'll draft it, or ask me to continue."

## Guardrails

- Do not create any artifacts yet — only show the first artifact's template.
- Do not advance beyond the first artifact.
- If the name is not valid kebab-case, ask for a valid one.
- If a change with that name already exists, suggest continuing that change
  instead of creating a duplicate.

## Completion

Complete when the change directory exists, its schema is confirmed, and the
first artifact's template has been shown to the user — without any artifact
file having been written yet.
