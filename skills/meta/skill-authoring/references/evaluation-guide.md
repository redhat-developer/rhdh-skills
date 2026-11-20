# Evaluating skills

Read this whenever creating, changing, consolidating, or considering retirement
of a skill. Use
[agent-eval-harness](https://github.com/opendatahub-io/agent-eval-harness) as the
default evaluation system unless the host repository mandates another one. Its
`/eval-analyze`, `/eval-dataset`, `/eval-run`, `/eval-review`, and
`/eval-compare` skills own configuration, execution, scoring, and reports; use
those interfaces instead of reproducing their mechanics here.

If the harness is unavailable, evaluation design may continue in its native
layout, but execution is blocked. Leave the prepared assets, name the missing
capability, and label the behavior unevaluated. Repository tests, static review,
and a well-formed `SKILL.md` are useful checks, not substitutes for an agent run.

## Define success before cases

State which dimensions matter for the skill:

1. **Routing** — intended requests select a model-invoked skill and near-misses
   do not. Human-invoked skills have no routing score.
2. **Outcome** — the resulting answer, artifact, or external state satisfies the
   task's acceptance criteria.
3. **Process** — required tools, sources, approvals, or operation ordering are
   observed when they are part of the public contract or a safety boundary.
4. **Style and policy** — durable team conventions, privacy requirements, and
   output constraints hold.
5. **Efficiency** — latency, cost, turns, tool calls, and retries stay within a
   budget appropriate to the task.

Do not grade hidden chain of thought. Do grade visible traces when tool use or
ordering is itself required. A final artifact can look correct even though an
agent skipped a mandatory approval or used an untrusted source.

Classify the skill before interpreting results. A **capability skill** fills a
current model or runtime gap and may be retired when an unassisted baseline
catches up. A **preference skill** enforces a durable convention and remains
useful while that convention matters.

## Use the harness layout

Run `/eval-analyze --skill <name>` for behavior and `/eval-analyze --prompt
<analysis-prompt>` for implicit routing. Keep development evals at repository
level, outside the installed skill directory.

For one evaluation, the harness uses root `eval.yaml`. For a repository with
multiple evaluations, use one of its discoverable `eval/` layouts, normally
`eval/<eval-name>/eval.yaml`. Keep `eval.md` beside each config, point
`dataset.path` at case directories relative to that config, and ignore
`eval/runs/`.

Each case is a directory. Its `input.yaml` contains what the agent sees;
`answers.yaml` can answer supported interaction hooks; `annotations.yaml` and
`reference.md` remain judge-only unless explicitly whitelisted. Put runtime
fixtures in the case and declare them through `dataset.workspace.files` so each
trial starts in an isolated workspace. Never create a second JSON or YAML case
contract beside this layout.

## Separate routing from behavior

An `execution.skill` evaluation invokes the skill explicitly. It can measure
behavior but cannot prove that an agent would discover the skill. Use two
evaluations for model-invoked skills:

- a prompt-mode routing suite with explicit, implicit, contextual, negative, and
  keyword-sharing near-miss requests; and
- a skill-mode suite with representative successful, edge, and failure cases for
  each supported workflow.

Reuse the queries designed in `description-guide.md`. Seed both suites with real
requests, production traces, and reported failures when available; add synthetic
boundary cases for missing coverage. Every behavior fix adds a regression case
that fails before the fix and passes after it.

## Choose judges deliberately

Prefer the cheapest reliable judge:

1. Use inline checks or reusable code judges for exit status, file presence,
   schemas, diffs, forbidden identifiers, required tool calls, and budgets.
2. Use a narrow LLM or read-only agent judge for correctness, completeness,
   coherence, or tone that cannot be reduced to stable assertions.
3. Declare `feedback_type`, `score_range`, and repeated `samples` for stochastic
   judges. Validate the judge against obvious pass and fail examples before
   trusting it.
4. Inspect failed traces before editing the skill. The defect may be in the case,
   fixture, judge, model, runtime, or skill.

Write specific rubrics with observable anchors. More automated lower-signal
cases usually provide healthier coverage than a few expensive human-scored
examples; use human review to calibrate ambiguous rubrics and investigate
disagreements.

## Compare and gate changes

Record a successful pre-change run when one exists. Hold the cases, fixtures,
runner, model, tools, and judges constant when comparing runs. Use the harness
baseline and pairwise facilities rather than comparing screenshots or selected
examples.

Run repeated trials when agent behavior is stochastic and compare supported
runners or models without cloning the dataset. A change is ready when:

- deterministic contract checks pass;
- semantic scores meet calibrated thresholds;
- intended routing holds or improves without worsening near-misses;
- existing cases show no unexplained regression; and
- any claim that the skill improves behavior is supported by a comparable
  baseline rather than intuition.

Do not tune against every case and then call the same cases proof of
generalization. Add holdouts or fresh real traces. Initial semantic thresholds
may be conservative and explicitly provisional, but recalibrate them after the
first successful baseline run. Never describe provisional thresholds as
validated.

## Retirement and evidence

Re-run comparisons after meaningful model or runtime upgrades. Retire a
capability skill when an unassisted or smaller replacement matches its reliability
across the supported matrix. Retire a preference skill only when the convention
is obsolete or enforced by a stronger source of truth. Keep the cases after
retirement so later degradation remains visible.

Report the config and run IDs, case coverage, runner and models, passes or scores,
threshold failures, judge reasons, baseline comparison, and decision. If no run
was possible, report the configs and cases prepared plus the exact blocker. The
evidence is sufficient when another author can rerun it and understand why it
supports shipping, revising, or retiring the skill.
