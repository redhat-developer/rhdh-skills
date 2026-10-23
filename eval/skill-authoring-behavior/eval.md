---
skill: skill-authoring
analyzed_at: 2026-08-25T00:00:00-05:00
skill_hash: a10ce876d2ff
execution_mode: case
headless: true
dry_run: false
status: unevaluated
thresholds: provisional
suggested_judges:
  - name: produced_output
    type: check
    description: Require a non-empty collected artifact.
  - name: behavior_quality
    type: agent
    description: Score observable results against each case rubric.
---

# Skill-authoring behavior evaluation

This skill-mode evaluation invokes `skill-authoring` explicitly. It contains six
isolated cases: two each for create, audit, and consolidate. Routing is measured
separately by `skill-authoring-routing`.

## Prerequisites

Install agent-eval-harness, then install the complete current RHDH pack and its
required external `/grilling` skill into the Codex environment. The repository's
category folders are editorial and must not be converted into a root Claude
plugin merely to satisfy `runner.plugin_dirs`. Run
`/eval-check --config eval/skill-authoring-behavior/eval.yaml` before the first
evaluation and confirm that the installed `skill-authoring` resolves to the
revision under test.

The primary runner and the read-only semantic judge use Codex. Compare a later
Claude Code run against the same dataset through the harness baseline and
comparison commands rather than maintaining a second config or case copy.

## Status and calibration

The config was validated against the upstream harness, but no authenticated run
was made against a project-staged copy of the changed skill and its external
`/grilling` dependency. The checkout's category layout is intentionally not an
executable plugin, and an installed copy could differ from this working tree.
The cases are therefore unevaluated. `produced_output` is a deterministic
contract. The `behavior_quality` threshold and three-sample judge are
provisional: validate the rubric with clear pass and fail artifacts, establish a
successful baseline, then calibrate the threshold from observed score
distributions. Preserve failing cases as regressions.
