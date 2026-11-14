# Unattended remediation for one skill

**Status:** Proposed.

## Context

The RHDH Jira lint job finds hygiene violations and sends them to assignees in
Slack. The findings are frequently seen and not acted on, so the job's output is
not the outcome the team wants: a compliant issue.

An agent can now do the work instead — investigate the issue, size it from its own
scope, set the field, and record why. But [ADR-0007](0007-write-gate.md) requires
every external write to be stated and approved, and [ADR-0001](0001-agent-assisted-workflows-over-ci-automation.md)
chose agent-assisted workflows over always-on bots. Neither anticipated an agent
doing routine, bounded field updates on a schedule.

Three options were considered for authorizing an unattended run:

- **A runner-side policy file** listing pre-approved operation classes. Rejected:
  it duplicates the skill's rules in a second artifact that drifts, and the
  safety decision moves to whoever edits the runner configuration.
- **A blanket exemption for Jira writes.** Rejected: unbounded, and it would
  authorize transitions and closures nobody asked for.
- **The skill's published procedures are the authorization.** The invocation
  authorizes exactly the rule set and remediation procedures that ship in the
  skill, and the executor enforces them mechanically.

## Decision

For `/rhdh-jira-lint` only, an unattended invocation authorizes the operation
classes and limits published in that skill. There is no separate policy file.

The authorization is bounded by what the executor checks immediately before each
write:

- the field still holds the expected empty value;
- the issue is still in the resolved scope and status set;
- the payload uses a field and value the rule supports;
- the plan does not exceed the operation cap;
- every write is read back, and a mismatch is reported as failed.

The skill never writes transitions, closures, assignments, or exemptions, and
never derives `Blocker` or `Critical`. Those remain behind `/mutation-gate` and a
person, in every mode.

Interactive invocations keep the existing gate. Other skills are unchanged: they
still state their operations and get approval.

## Consequences

- Changing the skill's procedure set changes what an unattended run may do, so
  procedure changes are reviewed as authorization changes, not as prose edits.
- The first scheduled runs are report-only, then dry-run, then writes, so the
  team sees the values before the bot can land them.
- A comment is still irreversible once posted. The batch hash prevents duplicates
  but not the first notification; the operation cap is the notification cap.
- Rollback is receipt-driven: the before values are recorded, and a revert is a
  new plan through the same gate.
- This does not authorize unattended writes for any other skill. A second skill
  that wants the same treatment needs its own decision.
