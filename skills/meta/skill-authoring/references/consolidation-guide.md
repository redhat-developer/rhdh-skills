# Consolidating multiple skills

Read this when asked to merge, consolidate, or combine existing skills into
fewer, and read it again after the merge to check the result did not overshoot.

## When to consolidate

Look for these signals that separate skills should be one.

### Strong signals (consolidate)

- **One cohesive trigger**: users describe the outcomes with the same leading
  intent and expect one completion criterion.
- **Shallow boundaries**: deleting a skill moves only routing prose or a small
  checklist into its caller rather than exposing a meaningful interface.
- **Near-identical scripts**: two scripts with the same structure, differing only
  in a flag value or a file path.
- **Duplicate prose**: the same reference doc, example, or version map shipped by
  more than one skill.
- **One source of meaning**: the split forces the same policy or domain fact to
  be maintained in several places.
- **A costly misroute**: choosing wrong between the two produces a wrong *write*
  rather than an obviously wrong answer. A user who cannot tell Feature from
  Story in advance should not be asked to.

Duplication on its own is not one of these signals. Two skills with independent
triggers that share material need the material moved, not the skills merged:
apply the extract/enforce/document rule in `architecture-patterns.md` →
Duplication between skills first, and consolidate only when the boundary itself
turns out to be shallow.

### Weak signals (maybe consolidate)

- **Same audience**: the skills target the same persona, but the workflows are
  genuinely independent.
- **Same domain**: the skills cover the same product area while handling
  unrelated concerns, such as CI debugging versus local testing.
- **Linear pipeline**: producer and consumer may be better as two deep skills
  joined by a named invocation.
- **Shared setup**: central setup can remove the duplicated prerequisite without
  merging the task-oriented skills.

### Don't consolidate

- **No shared context**: different prerequisites, different audiences, no
  cross-references.
- **Different tools**: one skill uses `acli`, another uses `yarn` — they share
  nothing but the product name.
- **Deep seam**: a skill hides substantial policy, transport, state, or adapter
  complexity behind a small interface.
- **Independent trigger**: users reasonably ask for either outcome without the
  other, and each has distinct completion criteria.

## Counter-signals: the consolidation went too far

In one collection this guide's own rule was ignored, and a 24-to-18 merge folded
four independent triggers into one 7,784-line skill. These are the marks it leaves.
Any one of them means split the skill back out.

- **No citation edges.** Partition the references by which ones cite each other.
  Components with no edges between them are separate skills that happen to share
  a directory.
- **References reachable from only one entry point.** A file that loads under
  exactly one branch belongs to that branch's skill. The inverse is as telling: a
  reference layer carrying in-degree 3–9 that the skill's own pointers never name
  is serving several skills at once.
- **Rows that name no shared behaviour.** A route table whose rows share no
  domain model, gates, or completion criterion is a discovery system wearing the
  clothes of progressive disclosure. A row that says "matching file in
  `workflows/`" instead of naming a behaviour is the table admitting it.
- **A `compatibility:` line that is a union.** "acli, yarn, podman, and an
  OpenShift login" describes several jobs wearing one description.
- **One-to-one with a script's sub-commands.** Seventeen workflows mapping onto
  seventeen sub-commands of one CLI makes the skill a **shallow module**: its
  interface costs as much to learn as the thing it hides.

### Size heuristics

The 500-line limit governs `SKILL.md` only, and both runaway skills passed it
while their directories reached 4,029 and 7,784 lines. Measure the whole
directory — `SKILL.md`, `references/`, `workflows/`, `assets/` — because that is
what a caller has to navigate.

Line counts are a symptom, though, not the test. The test is: **which of these
vocabularies does a caller have to learn?** One trigger phrase should commit the
caller to one vocabulary — one set of nouns, one toolchain, one mental model. If
answering the question requires "it depends which part of the skill you land in",
the skill is several skills, whatever its line count. A short skill can fail this
test and a long one can pass it.

## Consolidation workflow

### Step 1: Analyze

Before writing any code:

1. Read every `SKILL.md` in the candidate set.
2. Map the cross-references. Draw the dependency graph — which skills point to
   which.
3. Inventory shared content: scripts, references, examples, version maps,
   prerequisites.
4. Apply the deletion test to every candidate boundary: identify where its
   complexity would move if the skill disappeared.
5. Identify the seams: which meaning becomes local to a deep skill, and which
   crosses a named skill boundary.

### Step 2: Design the consolidated skill

Choose the architecture from trigger independence, interface depth, locality, and
leverage. File length shapes progressive disclosure after the boundary is chosen;
it does not choose the boundary.

When the merged skill keeps branches:

- Preserve outcomes, not old folder boundaries. Several old skills may become one
  branch, or one old skill may split across deeper owners.
- Shared setup goes through the repository setup entry point. Shared domain
  meaning belongs to one owner skill and is reached by name.
- Deep-dive references from the old skills move into `references/` with their
  original filenames.
- Run the counter-signals above against the design before writing it. A merge
  that fails one of them has already gone too far.

### Step 3: Merge scripts

When consolidating near-identical scripts:

1. Diff them. Identify what actually differs — usually a flag value, a directory
   name, or an optional step.
2. Keep the more mature script's structure: better error handling, more features.
3. Add a `--type` or `--mode` flag to express the variant behaviour.
4. Verify both paths still work — run `--help` and test with both values.
5. **Harmonize patterns between scripts** in the same skill. Watch for:
   - One script checks `NO_COLOR`, the other doesn't
   - One builds a shell command string while the other uses validated argv;
     retain the structured `shell=False` boundary
   - One checks `stdout.isatty()` but logs to `stderr`
   - Different exit code conventions
   - Different JSON output formats

Scripts that stay in separate skills stay duplicated, and that is correct — a
bundled script is self-contained so its skill installs alone.

### Step 4: Consolidate examples

- Diff example files across the old skills. Often 60%+ is identical.
- Create one unified example file with sections for each variant.
- Remove duplicates — one example per pattern, not one per old skill.

### Step 5: Update all consumers

This is where consolidations break. Search the **entire project** for old skill
names:

```bash
grep -rn "old-skill-name" --include="*.md" --include="*.py" --include="*.json" --include="*.yaml" --exclude-dir=.git .
```

**Must update:**

| Location | What to change |
|----------|---------------|
| Setup catalog | Promoted name, category, invocation, dependencies |
| Human entry skills | Wayfinding and setup routes |
| README.md | Generated or summarized catalog documentation |
| ADRs / docs | Historical references to old skill names |
| Script docstrings | `--help` text referencing old workflow names |
| Other skills' references | Cross-references like "see the X skill" |
| CI / build configs | Paths to moved files |

**Gotcha: the new description has to win its trigger without stealing another
skill's.** Read the surviving descriptions side by side. A merged skill that now
claims two utterances has to claim both cleanly, and must not claim a third that
belongs to a neighbour.

### Step 6: Audit reference paths

Reference files use relative paths, and moving files breaks them in subtle ways:

- A reference in `references/export.md` that says `Read references/export-options.md`
  is wrong — it resolves to `references/references/export-options.md` from that
  file's perspective.
- Choose a convention: paths relative to the file, or paths relative to
  `SKILL.md`. Document which.
- Be consistent — don't mix conventions within one skill.

**Recommended convention:** paths in `SKILL.md` are relative to `SKILL.md`. Paths
in reference files name siblings by filename only, such as
`Read export-options.md (in this directory)`.

### Step 7: Review

Run the same pre-change agent-eval-harness cases against the consolidated design
using `evaluation-guide.md`; a smaller catalog is not an improvement if routing
or task outcomes regress. Then run the Phase 5 review checklist from `create.md`,
plus these consolidation-specific checks:

- [ ] No references to old skill names anywhere in the project
- [ ] None of the counter-signals above fire against the merged skill
- [ ] The merged description claims its utterances and collides with no sibling
- [ ] Named dependencies match the setup catalog
- [ ] Script docstrings and `--help` text reference the new skill name
- [ ] Reference paths resolve correctly from each file's location
- [ ] All example files from the old skills are represented
- [ ] Scripts in the same skill use consistent patterns (NO_COLOR, shell flags,
      TTY checks, exit codes)
- [ ] README skill tables and directory trees match the new structure
- [ ] Script, adapter, catalog, and clean-install tests pass without prose-shape
      assertions
- [ ] Pre-change and consolidated runs are compared through the harness baseline
      on the same isolated cases, including near-misses for every surviving
      description

## Anti-patterns

### Incomplete grep

Searching for old names in `skills/` only. Old names appear in README, ADRs, CI
configs, and script help text. Search the entire project.

### Path assumptions after moves

Copying a reference file without updating its internal relative paths. A file
that said `../rhdh/references/versions.md` needs a different path after moving.

### Keeping empty directories

After deleting old skills, empty directories or `__pycache__/` may linger. Clean
up.

### Forgetting the description

The consolidated description must cover every trigger phrase from every old
skill. Check each old description and verify the new one would fire for the same
queries.

### Merging to hit a number

A skill count is an output of one-trigger-one-skill, never a target. "24 skills
feels like too many" is not a signal; it is how the 7,784-line skill happened.
