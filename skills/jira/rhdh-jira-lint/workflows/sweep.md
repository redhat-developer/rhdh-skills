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

Every finding becomes exactly one schema 2 entry:

- `supported` — the evidence is sufficient; carry `set` and an empty-only
  precondition;
- `insufficient` — do not write; carry one specific question;
- `human_required` — do not write; carry the decision and options;
- `waived` — do not write; record the existing exemption.

One uncertain field does not block other supported fields on the same issue.

```json
{
  "schema": 2,
  "run_id": "20261120T1015Z-rhidp-backlog",
  "scan_digest": "b17c9f0ad929e440db6e0d9c7bc1a3d9c4dbcbf3b3ea5cd4b8dd6e4e59a01b70",
  "scope": {"jql": "project in (RHIDP) AND updated >= -365d"},
  "fields": {
    "story_points": "customfield_10028",
    "size": "customfield_10029",
    "rn_type": "customfield_10030",
    "rn_text": "customfield_10031",
    "rn_status": "customfield_10032"
  },
  "issues": [
    {
      "key": "RHIDP-1234",
      "summary": "Improve authentication timeout handling",
      "project": "RHIDP",
      "issuetype": "Story",
      "status": "In Progress",
      "labels": [],
      "expected_updated": "2026-11-19T14:22:03.000-0500",
      "mention": {
        "accountId": "5b10a...",
        "displayName": "Jane Doe",
        "role": "assignee"
      },
      "findings": [
        {
          "rule": "LINT-COMPONENT",
          "action": "derive",
          "decision": "supported",
          "reason": "Component inherited from RHIDP-900.",
          "evidence": {
            "basis": "Parent RHIDP-900 has one component: Authentication.",
            "parent": "RHIDP-900",
            "parent_components": ["Authentication"]
          },
          "set": {"fields": {"components": [{"name": "Authentication"}]}},
          "precondition": {"field": "components", "state": "empty"}
        },
        {
          "rule": "LINT-POINTS",
          "action": "estimate",
          "decision": "insufficient",
          "reason": "Scope is ambiguous between the provider change and migration.",
          "evidence": {
            "basis": "The description and child spike disagree about migration scope.",
            "question": "Is the scope the provider change alone, or does it include migration?"
          }
        }
      ]
    }
  ]
}
```

Use the API field name for standard fields (`components`, `priority`,
`fixVersions`) and the resolved ID from the scan's `fields` map for custom ones.
The precondition is always the same field the finding writes, and normal writes
always use `state: "empty"`.

Write the plan to the temporary directory, not into a checkout.

## 6. Dry run and gate

```bash
uv run scripts/apply.py --plan /tmp/lint-plan.json --dry-run
```

A `skipped` outcome means the issue or a field stopped matching the plan. Drop
that issue from the next attempt. A blocked or escalated finding is not a write
and remains in the report.

Interactive: invoke `/mutation-gate` and state the set as a table — one row per
issue with the field, before, after, basis, and the derived comment body. An
unattended run is authorized only by the schema 2 plan and the executor's
mechanical checks.

## 7. Apply

```bash
uv run scripts/apply.py \
  --plan /tmp/lint-plan.json \
  --confirm \
  --receipt /tmp/lint-receipt.json \
  --revert-plan /tmp/lint-revert.json
```

`apply.py` groups writes by issue, verifies scope and preconditions, writes the
issue once, reads every field back, and only then posts one comment. If any
write on an issue fails, that issue gets no comment. Comments are restricted to
the `Red Hat Employee` Jira group.

The executor stops a rule or field class after a `400`, `403`, repeated `429`,
or read-back mismatch. It stops the whole run on `401` or a permission failure
while reading an issue. If any supported rule on an issue is stopped, the whole
issue is skipped so the run never leaves a partial field batch. Other issues and
unaffected rules continue.

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
escalated items. The receipt is required for confirmed writes and contains the
run ID, plan hash, scan digest, Jira host, evidence, before and after values,
comment ID, and comment visibility. Keep it: the next sweep and any guarded
rollback depend on it.

A sweep is not finished when the report is printed. It is finished when every
finding has an outcome, every changed issue carries exactly one comment for that
batch addressed to its assignee or reporter, every blocked finding names the
one piece of evidence it needs, and the durable receipt and guarded revert plan
have been written.
