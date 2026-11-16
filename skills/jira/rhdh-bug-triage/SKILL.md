---
name: rhdh-bug-triage
description: >-
  Triages aged RHDHBUGS reports for high-confidence duplicate and already-fixed
  closure recommendations, with clear linked proof and one canonical tracker or
  released fix. Use for "triage aged bugs", "clean up old RHDHBUGS", "are these
  old bugs still valid", "which aged bugs can we close", or "bug backlog triage".
  Leaves all other issues unchanged without a comment or reproduction request.
  Read-only: recommendations stay local for human approval; never writes to Jira.
compatibility: "acli on PATH with a Jira session, or a JSON Jira export; gh for read-only PR evidence; Python 3.9+; the offline path needs no network access."
---

# Triage aged RHDH bugs

Find defensible opportunities to consolidate or close aged, non-customer bugs.
Humans review conclusions and proof, not a new list of investigations. The
current milestone surfaces **only duplicate and already-fixed recommendations**;
it does not create fixes, PRs, backports, or Jira mutations.

## Route

Follow [workflows/triage-aged-bugs.md](workflows/triage-aged-bugs.md), the single
entry point for selection, evidence, independent adjudication, policy, and report.

- [references/disposition-rubric.md](references/disposition-rubric.md) owns close
  gates, canonical selection, abstention, and the exact output contract.
- [references/evidence-sources.md](references/evidence-sources.md) owns evidence
  collection and its limitations.
- [references/report-schema.md](references/report-schema.md) owns structured proof
  inputs and output artifacts.
- [TESTING.md](TESTING.md) owns verification and migration checks.

## Operating contract

- **Recommend, do not announce.** Each surfaced issue gets `Re:`, `Duplicate:` or
  `Already Fixed:`, `Recommendation:`, `Proof:`, and evidence-derived confidence.
  Link the compared reports, implementation, tests, and release evidence. Never
  claim a close or runtime test happened when it did not.
- **Abstain silently.** Missing, conflicting, weak, partial, or unreleased proof
  produces no Jira-facing comment, reminder, reproduction request, or handoff
  file. Internal `still_valid`, `no_longer_valid`, `needs_repro`, and `unclear`
  evidence states may remain in the local audit; they are not outward outputs.
- **No forced quota.** Zero recommendations is valid. Do not inflate confidence
  or rename an uncertain finding to avoid abstention. No software, model score,
  or pair of reviewers can guarantee 100% factual accuracy.
- **Read-only.** This skill cannot comment, transition, link, assign, close,
  create a PR, or backport. Local `proposed/` files are not authorization or Jira
  posting history. Existing advice/pending requests must not generate reminders.
- **Human gate.** For a human-approved recommendation, invoke `/prose-editing`
  once in the Jira register, preserve the verified proof and triage reference,
  and hand it to `/rhdh-jira-update` under `/mutation-gate`. Any changed facts or
  action require re-evaluation. No autonomous writer is implemented here.

## Named-skill boundaries

Compose through interfaces, never another skill's files or scripts:

- `/rhdh-jira-api`: authenticated Jira reads, fields, pagination, and CLI fallbacks.
- `/rhdh-jira-authoring`: what constitutes the same bug, not merely a similar title.
- `/rhdh-forge`: forge reads and fix/commit evidence.
- `/rhdh-context`: current released product and repository/stream context.
- `/rhdh-backport`: branch/backport rules; no automatic backport recommendation.
- `/rhdh-jira-update`, `/rhdh-jira-link`: any separately approved Jira mutations.
- `/rhdh-plugin-bug-fix`: a separately requested later implementation workflow,
  not an automatic consequence of an abstention.

## Commands

From this skill directory:

```bash
python3 scripts/run_poc.py check --json
python3 scripts/run_poc.py select --input export.json --size 12 --out sample.json
python3 scripts/run_poc.py collect --input export.json --sample sample.json --out evidence
python3 scripts/run_poc.py template --sample sample.json --out assessments
python3 scripts/run_poc.py run --input export.json --sample sample.json \
  --corpus broad-export.json --assessments assessments --out new-review \
  --current-release 2.1.0
```

The release is an example, not a lifecycle lookup. Resolve the actual released
target before running. Use a fresh output directory; an existing nonempty one
is refused without overwriting or retaining stale proposals. A 14-day configurable
comment cooldown never authorizes repeating unchanged or pending advice.

## Completion

Complete when `report.md` contains only qualifying duplicate/already-fixed
recommendations with the agreed proof shape, and `packets.json`, `summary.csv`,
and `manifest.json` retain the full local audit. Only surfaced recommendations
have `proposed/KEY.md`; zero recommendations may mean no `proposed/` directory.
Every rejected finding must have `action: abstain`, empty `proposedComment` and
`recommendedStep`, and a local reason. The manifest must have `writes: []`.

Tell the user the recommendation count, the single `report.md` path, and any
closure decision awaiting approval. Say that nothing was written to Jira.
Do not paste all abstentions or ask humans to investigate the skipped backlog.
