---
skill: skill-authoring
analyzed_at: 2026-08-25T00:00:00-05:00
skill_hash: a10ce876d2ff
execution_mode: case
headless: true
dry_run: true
status: unevaluated
thresholds: provisional
suggested_judges:
  - name: routing_match
    type: check
    description: Match observable skill consultation to should_trigger.
---

# Skill-authoring routing evaluation

This prompt-mode evaluation measures whether an agent selects `skill-authoring`
without explicit invocation. It contains twelve cases: four explicit requests,
three implicit or contextual requests, and five negative near-misses.

## Prerequisites

Install agent-eval-harness and install the complete current RHDH skill pack into
the Codex environment. The routing suite needs the surrounding skills installed
because several negative cases belong to adjacent capabilities. Run
`/eval-check --config eval/skill-authoring-routing/eval.yaml` before the first
evaluation.

The harness's generic config validator warns that this prompt-mode suite has no
file outputs. That is intentional: the judge reads the captured event stream and
visible response rather than an artifact directory.

The committed primary runner is Codex. Use the harness's comparison workflow to
run the same cases with Claude Code; do not copy the dataset for another runner.

## Status and calibration

The config was validated against the upstream harness, but no authenticated run
was made against a project-staged copy of the changed skill pack. The checkout's
category layout is intentionally not an executable plugin, and an installed copy
could differ from this working tree. The suite is therefore unevaluated. The
deterministic routing threshold is intentionally strict, but the trace markers
must be confirmed against the first Codex report. Record that run as the initial
baseline, investigate every mismatch, and update markers only when the trace
proves that activation occurred through a different observable event.
