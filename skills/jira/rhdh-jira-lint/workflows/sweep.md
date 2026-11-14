# Sweep

One pass over a scope: discover dates, find violations, investigate, apply the
procedure, verify, comment, and report. Nothing here assumes a file or wrapper
was prepared beforehand.

## 1. Scope

Ask only when it is not inferable. A sweep is bounded by one of:

- a person (`--assignee me`), the weekly personal pass;
- a team (`--team "RHDH Install"`);
- a release (`--release 1.10.0`), the freeze pass;
- an explicit JQL or key list.

Load [../references/rules.md](../references/rules.md) and
[../references/investigation.md](../references/investigation.md) before acting.
The exemption list decides what not to touch; the investigation rules decide what
may be written.

## 2. Dates

Invoke `/rhdh-release-schedule` for the active releases and for any planned
version in scope. It owns the RHDHPLAN release Feature and the schedule
spreadsheet; do not read either source directly.

Transcribe what it returns into a temporary JSON file:

```json
{
  "releases": [
    {
      "version": "1.10.0",
      "feature_freeze": "2026-04-28",
      "code_freeze": "2026-05-19",
      "ga_announce": "2026-06-10"
    }
  ]
}
```

`ga_announce` is the field that becomes `ga_push`. Never use Go/No Go, Docs
Freeze, or an inferred date. A version the skill reports as TBD is omitted from
the file; the scanner will list it under `calendar_missing_versions`.

If a canonical `release_calendar.yaml` is already available and current, pass it
instead. The scanner accepts both shapes.

## 3. Scan

```bash
uv run scripts/scan.py --assignee me --release-calendar /tmp/release-dates.json
```

Read three things before acting:

- `scope.truncated` — a truncated sweep has not seen the backlog; its count is
  not a backlog count.
- `scope.calendar_missing_versions` and `scope.calendar_problems` — a date rule
  did not run for those versions. Say so; do not report absence as compliance.
- `waived` — active human exemptions. They are not findings.

`mention` on each finding is the person the comment will address: the assignee, or
the reporter when the issue is unassigned.

## 4. Investigate

For each finding, follow [../references/investigation.md](../references/investigation.md)
and gather the evidence its rule requires. A missing field is a question about
the work, not a prompt to pick a default.

Stop at the first of these that applies:

- the evidence supports a value → plan the write;
- a person deliberately exempted it → leave it, no comment;
- the evidence is insufficient or contradictory → mark it blocked with one
  specific question;
- the decision is a release commitment → escalate with the options.

## 5. Plan

Walk the findings in this order: `review-waiver`, `derive`, `escalate`,
`estimate`, `classify`, `draft`. Parents before children.

| Finding | Plan entry |
|---|---|
| `derive` with `proposed` | Copy `proposed` into `set`, with a `reason` |
| `derive` without `proposed` (`choose`) | Do not write. Block or escalate |
| `estimate` | Compute the value from the evidence, then `set` it with the basis |
| `classify` | Resolve the type with `/rhdh-feature-docs`, then `set` it |
| `draft` | Draft the note, convert to ADF with `/rhdh-jira-api`, then `set` it |
| `escalate` | Do not write. Add the options to the summary |
| `review-waiver` | Do not write. Escalate renew, fix, or retire |

The plan is JSON for `scripts/apply.py`. One comment per issue, covering every
change that issue received in the sweep:

```json
{
  "schema": 1,
  "operations": [
    {
      "key": "RHIDP-1234",
      "rule": "LINT-COMPONENT",
      "reason": "the issue changes the authentication provider",
      "set": {"fields": {"components": [{"name": "Authentication"}]}},
      "precondition": {"field": "components", "state": "empty"}
    },
    {
      "key": "RHIDP-1235",
      "rule": "LINT-POINTS",
      "reason": "3 acceptance criteria, one component, integration tests",
      "set": {"fields": {"customfield_10028": 3}},
      "precondition": {"field": "customfield_10028", "state": "empty"}
    }
  ],
  "comments": [
    {
      "key": "RHIDP-1234",
      "lines": [
        "Component -> Authentication (the issue changes the authentication provider).",
        "Story Points -> 3 (3 acceptance criteria, one component, integration tests)."
      ],
      "mention": {"accountId": "5b10a...", "displayName": "Jane", "role": "assignee"}
    }
  ]
}
```

Use the API field name for standard fields (`components`, `priority`,
`fixVersions`) and the resolved ID from the scan's `fields` map for custom ones.
The precondition is the same field the operation writes, `state: empty`.

Write the plan to the temporary directory, not into a checkout.

## 6. Dry run and gate

```bash
uv run scripts/apply.py --plan /tmp/lint-plan.json --dry-run
```

A `skipped` outcome means the field stopped being empty between the scan and now
— someone else fixed it. Drop that operation. A comment `planned` with a batch id
is a new batch; the same id on a retry means the comment already exists.

Interactive: invoke `/mutation-gate` and state the set as a table — one row per
issue with the field, before, after, basis, and the exact comment body. An
unattended run is authorized by the skill's published procedures; the executor
enforces the preconditions and the operation cap. Nothing outside those
procedures is authorized.

## 7. Apply

```bash
uv run scripts/apply.py --plan /tmp/lint-plan.json --confirm --receipt /tmp/lint-receipt.json
```

`apply.py` writes the fields, reads each issue back, then posts one comment per
changed issue. Exemptions and human-authored comments go through
`/rhdh-jira-update`; this sweep does not create exemptions.

When an operation fails, stop adding operations of that class. A validation
failure usually means the payload shape is wrong for the whole batch, and
repeating it forty times is not recovery.

## 8. Escalations and blocked findings

Neither is written to the issue. Group them by owner and send one summary:

```text
Needs your call (2)

RHIDP-1250 — 1.10.0 Feature Freeze (2026-04-28), priority Major
  1. move to 1.11.0          acli ... --fixVersion 1.11.0
  2. escalate to Critical    needs PM + Release Manager exception
  3. descope                 close with the matching resolution

RHIDP-1252 — Story Points blocked
  The issue has no acceptance criteria and one child spike still open.
  Question: is the scope the provider change alone, or does it include migration?
```

If there is no owner — unassigned and no reporter — the escalation goes to the
team lead named in the scope, not into the void.

## 9. Receipt

Report the counts by outcome, every completed operation with before and after,
every comment outcome (`created`, `unchanged`, `planned`), and the blocked and
escalated items. Keep the receipt path: the next sweep diffs against it.

A sweep is not finished when the report is printed. It is finished when every
finding has an outcome, every changed issue carries exactly one comment for that
batch addressed to its assignee or reporter, and every blocked finding names the
one piece of evidence it needs.
