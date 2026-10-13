# Artifact creation loop

Shared mechanics for turning one `ready` artifact into a written file. Every
caller (`openspec-new-change`, `openspec-continue-change`,
`openspec-ff-change`) drives this same loop; only how many artifacts it runs for
and when it stops differs, and each of those skills states that difference
itself.

## Get instructions for one artifact

```bash
openspec instructions <artifact-id> --change "<name>" --json
```

The response includes:

- `context` — project background. A constraint for you, never content for the
  file.
- `rules` — artifact-specific rules. Also a constraint for you, never content
  for the file.
- `template` — the structure to use for your output file.
- `instruction` — schema-specific guidance for this artifact type.
- `outputPath` — where to write the artifact.
- `dependencies` — completed artifacts to read for context before writing.

## Write the artifact

1. Read every file listed in `dependencies` before drafting anything.
2. Use `template` as the structure; fill in its sections rather than
   inventing a new shape.
3. Apply `context` and `rules` as constraints while writing.
4. Write the finished file to `outputPath`.
5. Verify the file exists and is non-empty before reporting progress or
   moving to the next artifact.

## The one rule every caller gets wrong at least once

`context`, `rules`, and any `<project_context>` block in the instructions
response are inputs to your judgment, not content for the artifact. Never copy
them into the file verbatim — a proposal that contains a literal `<rules>`
block failed to apply the rules, it just quoted them.

## Loop termination

Re-run `openspec status --change "<name>" --json` after each artifact and
check `artifacts[].status`. A caller creating every remaining artifact stops
once every ID in `applyRequires` reports `status: "done"`; a caller creating
one artifact per invocation stops after that single write regardless of what
remains.
