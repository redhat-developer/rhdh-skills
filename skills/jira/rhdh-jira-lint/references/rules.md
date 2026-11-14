# Lint rules

The complete rule set, with the exemption that suppresses it and the action class
that owns its remediation. The scanner implements this table; the procedure for
each class is in [remediation.md](remediation.md).

## Scope

| Bound | Value |
|---|---|
| Projects | `RHIDP`, `RHDHPLAN`, `RHDHBUGS` |
| Default window | `updated >= -365d` |
| Statuses skipped | `Closed`, `Release Pending` |
| Types skipped | Subtasks, `Outcome`, summaries containing `[test execution]` |

The window exists because the search endpoint rejects unbounded JQL in this Jira
instance. It is not a business rule: an issue dormant for more than a year is out
of a hygiene sweep's reach, and saying so is better than reporting a count that
silently excludes it.

## Rules

| Rule | Fails when | Exempt when | Class | Severity |
|---|---|---|---|---|
| `LINT-COMPONENT` | `components` is empty | never | `derive` → else `choose` | error |
| `LINT-PRIORITY` | `priority` is empty or `Undefined` | never | `derive` → else `choose` | error |
| `LINT-SIZE` | Epic or Feature has no `Size` | Team is `RHIDP - Documentation` | `estimate` | warning |
| `LINT-POINTS` | Story, Task, or Bug has no Story Points | Team is `RHIDP - Documentation` | `estimate` | error |
| `LINT-FIXVERSION-MULTI` | more than one Fix Version | never | `derive` → else `choose` | error |
| `LINT-FF-PRIORITY` | After Feature Freeze, priority is not Critical or Blocker | Component `Release` | `escalate` | error |
| `LINT-CF-PRIORITY` | After Code Freeze, priority is not Blocker | Component `Release` | `escalate` | error |
| `LINT-GA-OPEN` | After GA, the issue is still open | never, including `Release` | `escalate` | error |
| `LINT-RN-TYPE` | Feature or Bug after Feature Freeze has no Release Note Type | Component `Release` | `classify` | warning |
| `LINT-RN-TEXT` | Release Note Text is empty and the type is not `Release Note Not Required` | Component `Release` | `draft` | warning |
| `LINT-RN-STATUS` | Release Note Status is empty, type is set and not `Release Note Not Required` | Component `Release` | `derive` | warning |

`choose` is not a separate rule: it is the class a `derive` finding falls back to
when the parent and the active release do not settle the answer. The finding is
still emitted, so the decision is visible instead of silently dropped.

## Release phases

Phases come from the release milestones. Only versions with usable dates are
enforced; a version with no entry has no phase.

| Phase | Starts | What it enforces |
|---|---|---|
| Development | before Feature Freeze | Nothing phase-specific |
| Feature Freeze | `feature_freeze` | Priority must be Critical or Blocker |
| Code Freeze | `code_freeze` | Priority must be Blocker |
| GA Push | `ga_push` | The issue must be closed |

Release Note rules begin at Feature Freeze and stay on through GA Push.

`ga_push` is the **GA announce** date, never Go/No Go.

The skill discovers dates itself rather than requiring a file prepared outside
it. The scanner accepts:

- the YAML `release_calendar.yaml` mapping;
- the JSON `/rhdh-release-schedule` returns, either
  `{"releases": [{version, feature_freeze, code_freeze, ga_announce, ...}]}` or a
  `{version: {...}}` mapping.

Resolution order: `--release-calendar`, then `JIRA_LINT_RELEASE_CALENDAR`, then
`./release_calendar.yaml`, then a calendar the sweep writes from
`/rhdh-release-schedule`. A version whose dates are TBD or incomplete is reported
in `scope.calendar_problems` and its date-dependent rules are skipped. A version
in scope with no usable entry is listed in `scope.calendar_missing_versions`.
The skill never estimates a milestone date.

## Exemptions

A deliberate blank is a first-class state, not a finding to repeat every week.

| Label | Meaning |
|---|---|
| `hygiene-waived` | Permanent. The reason is on the issue |
| `hygiene-waived-YYYY-MM` | Expires at the end of that month, then becomes `review-waiver` |

The scanner skips an active exemption and lists it separately. An expired one
comes back as `review-waiver`, which is escalated with three options: renew it
with a new reason, fix the field, or retire it.

**The skill never creates an exemption.** Only a person can decide that a blank is
correct, and a bot that grants itself exemptions is closing its own findings.

## Parity notes

The scanner reproduces the deployed Python bot's rule set, with four deliberate
differences. All four make a silent failure loud; none add or remove a violation.

- **Field IDs are resolved by name**, never hard-coded. The bot refreshes names
  and falls back to legacy IDs; a legacy ID that no longer exists reads as an
  empty field, which is indistinguishable from a real gap. A missing field is now
  a warning and a skipped rule.
- **The bot fetches on conditions it never reports.** `affectedVersion is EMPTY`
  and the staleness conditions widen the fetch set but produce no finding. The
  scanner does not fetch on them. They are dead filters, not lost checks.
- **Release Note Status is enforced only when the field exists.** The bot's
  legacy fallback for it can report every Feature and Bug as missing a field the
  instance does not have.
- **An empty ADF body counts as empty.** A structured document with no text is a
  blank release note, not a populated one.

The human-facing feature list also describes `RHIDP`-only scope and a stale
seven-day staleness rule. The code above is the source of truth.
