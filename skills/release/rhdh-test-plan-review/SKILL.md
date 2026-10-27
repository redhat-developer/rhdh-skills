---
name: rhdh-test-plan-review
description: >-
  Reviews the platform and integration version tables and the key-date table in
  an RHDH test-plan Jira issue against vendor lifecycle data and the release
  schedule, then applies the accepted edits. Covers OCP, ARO, OSD, ROSA, AKS,
  EKS, GKE, PostgreSQL, RHBK, and Quay rows. Use for "review the test plan for
  1.11", "which platform versions should the 1.10 test plan list", "update the
  test plan dates", or a test-plan Jira URL or key such as RHIDP-1234.
compatibility: "Python 3.9+ and uv; a Jira tool for the plan issue; gog for the RHDH release schedule spreadsheet."
---

# RHDH test-plan review

Compare the version tables and key dates a test-plan issue carries against what
the lifecycle sources and the release schedule actually say, then apply what the
user accepts.

Read first. Nothing reaches Jira until the user has walked the diff row by row
and approved a stated set of writes.

## Route

1. Resolve the plan key or URL and the target RHDH version.
2. Load `workflows/review-test-plan.md` and follow it end to end.
3. Load `references/sources.md` at Step 4 — it holds every lifecycle URL and the
   extraction rules per product.
4. Load `references/google-sheets-setup.md` only when schedule access fails.

## Named-skill handoffs

Invoke each by name and use what it reports. Never read, execute, or locate a
sibling skill's files. When a named skill is absent, say so and name the review
dimension that stays unverified.

| Need | Skill |
|---|---|
| The plan issue, its linked issues, ownership, labels, and status | your Jira tool; `/rhdh-jira-context` for fields |
| Supported OCP, Kubernetes, PostgreSQL, RHBK, and Quay versions | `/rhdh-platform-lifecycle` |
| Feature Freeze, Code Freeze, and GA dates | `/rhdh-release-schedule` |
| What is still open against the release | `/rhdh-release-status` |
| Editing the plan description or posting a comment | `/rhdh-jira-update` |
| Creating a child task | `/rhdh-jira-create` |

`scripts/check_gsheets.py` and `scripts/fetch_schedule.py` are this skill's own
schedule adapters, not cross-skill interfaces. `gog` keeps Google credentials
behind its native interface.

## What the review reports

State the plan key and the release version, then, for every platform and
integration row and every key date:

- the current value, the suggested value, and the lifecycle or schedule source
  behind the suggestion;
- rows left unchanged, and why;
- rows the review could not evaluate, naming the source or skill that was
  unavailable.

A row with no suggested version is a gap. A row whose source could not be read is
unverified. Neither may be dropped, and neither may be reported as the other.

## Writing to Jira

Editing the description, posting a comment, and creating child tasks are writes.
Follow `/mutation-gate`: state each operation with its target ticket and the
exact ADF document, comment body, or child-task title it will land; get approval
for that stated set; execute; then report every operation as completed, failed,
or skipped. A failed operation stops the workflow and is reported, never retried
into a different shape.

## Completion

Complete when every platform row, integration row, and key date in the plan
carries a verdict — changed, unchanged, or unverified — and every suggested value
cites the lifecycle source or schedule tab behind it. Gaps and unverified rows
are listed separately; a row may not be omitted from both. When the user asked to
publish, complete only after every approved write has been reported by target and
outcome, including the ones that were skipped.
