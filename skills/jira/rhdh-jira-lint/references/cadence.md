# Running without a person in the loop

The skill is built to be scheduled. The runner authenticates, invokes it, and
reports; it does not need a policy file, a wrapper workflow, or a calendar-refresh
job. Everything the unattended run needs is published here.

## What authorizes a write

An interactive invocation behaves like any other skill: state the plan through
`/mutation-gate` and get approval.

An unattended invocation is authorized by **invoking the skill** for its published
scope. That scope is this skill's procedure set — the rules in
[rules.md](rules.md) and the actions in [remediation.md](remediation.md) — and
nothing else. There is no separate automation policy to drift out of sync with
the skill, and no class of write that exists only in a runner configuration.

The executor enforces the limits; the prose is not the control:

- every operation carries the field that must still be empty, checked immediately
  before the write;
- the issue must still be in the resolved scope and status set;
- the payload must use a field and value the rule supports;
- a plan above `--max-operations` (default 50) is refused outright;
- every write is read back, and a mismatch is reported as failed.

If a run needs a write outside that set, it stops and escalates. It does not widen
its own authority.

## The loop

1. **Dates.** Discover milestones through `/rhdh-release-schedule` and pass the
   result to the scanner. A version with no usable date is reported; its
   date-dependent rules are skipped and unrelated rules continue.
2. **Scan.** `scripts/scan.py` applies the rule set and reports findings,
   exemptions, and calendar gaps.
3. **Investigate.** Each finding is resolved from the issue and its context, per
   [investigation.md](investigation.md).
4. **Plan.** Build the operation and comment set.
5. **Apply.** `scripts/apply.py --confirm` performs the bounded writes and
   comments.
6. **Summarize.** Return what was fixed, what is blocked, and what needs a person.

Steps 1 and 2 are read-only. A failure there stops before any write.

## Guardrails

**Empty-only.** A value that appeared since the scan is someone else's decision.
The operation is skipped, not forced.

**Estimate only before work starts.** A Story Point written onto an in-progress
story changes the sprint's velocity after the fact. Restrict estimation to issues
that have not started; escalate the rest.

**Derive before estimate.** Fix the parent's component and priority first, so a
child inherits the corrected value in the same pass.

**Stop on a shape failure.** A 400 means the payload is wrong for every issue of
that class: stop the class, keep the receipt, report. A 403 is a permission, not
a retry. A 429 backs off once. A 401 stops the run; never repair credentials
inside the sweep.

**Bounded reads.** One issue, its parent, its children, its links, its recent
comments. A sweep that starts crawling the project for comparables has stopped
being deterministic.

## Idempotency

A second run with no new work must change nothing.

- Preconditions make a repeat write a skip.
- The comment carries a batch hash; a retry finds it and posts nothing.
- An existing human exemption is honored, not re-litigated.
- The receipt records before and after, so a value that flipped back is visible.

## Comments and notification budget

The comment is the audit trail: it turns a silent field edit into a record the
assignee can check. It is also the only place a run generates notifications.

- One comment per distinct batch of changes, never one per field and never a
  duplicate on retry.
- No comment when nothing changed.
- Mention the assignee, else the reporter; if neither exists, post without a
  mention and escalate the unowned issue.
- Escalations do not get a comment; they go in the summary.
- `--max-operations` is also the comment budget for a run.

Jira notifies watchers per comment, so a cap is a notification cap. At the default
fifty, a run touches at most fifty issues.

## Reverting

Field changes are auditable in Jira history but not one-click undoable. The
receipt carries the before values: a revert is a plan built from the receipt,
through the same gate, with the preconditions inverted.

A posted comment can be edited but not removed by the bot, and everyone mentioned
has already been notified. That is why the batch hash exists and why the body is
part of the approved set in interactive runs.

## First run

Run `scan.py` alone first. Read the findings, the warnings, and the calendar gaps.
Then run `apply.py --dry-run` on the plan and read the preconditions and comment
bodies. Only then use `--confirm`. On a scheduled runner, the first week should be
report-only: the receipt tells you what the skill would have done and whether the
values were right, before anything is written.
