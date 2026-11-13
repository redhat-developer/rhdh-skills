---
name: rhdh-bug-triage
description: >-
  Triages aged RHDHBUGS bug reports into duplicate, already fixed, still valid,
  no longer valid, or unclear, with cited evidence, an evidence-derived
  confidence, and a recommended next step. Use for "triage aged bugs", "clean up
  old RHDHBUGS", "are these old bugs still valid", "which aged bugs can we
  close", or "bug backlog triage". Read-only: it never comments, transitions,
  links, or writes to Jira, and every close proposal stays local for a human gate.
compatibility: "acli on PATH with a Jira session, or a JSON Jira export; gh for read-only PR evidence; Python 3.9+; the offline path needs no network access."
---

# Triage aged RHDH bugs

Turn a sample of old, non-customer RHDHBUGS reports into decision-ready evidence
packets. Every disposition cites something a reviewer can check, and every close
proposal is local until a human approves it.

## Route

Load [workflows/triage-aged-bugs.md](workflows/triage-aged-bugs.md). It owns the
end-to-end pass: capability check, sample selection, evidence collection, two
independent adjudication passes, policy evaluation, and report review.

Read the rules it depends on as needed:

| Question | Reference |
|---|---|
| What does each disposition mean, and when is a close allowed? | [references/disposition-rubric.md](references/disposition-rubric.md) |
| Where can evidence come from, and what counts as direct? | [references/evidence-sources.md](references/evidence-sources.md) |
| What do the assessment and packet files contain? | [references/report-schema.md](references/report-schema.md) |

## Dry-run guarantee

This skill has no write path. It does not comment, transition, link, assign, or
edit a Jira issue, and it does not comment on, merge, or open a pull request.
Proposed comments and close actions are Markdown files under `proposed/` in the
output directory. Each file leads with the exact comment that would be posted, so
an approved proposal can travel to Jira unchanged. Posting one is a separate,
human-approved step: hand the approved proposal to `/rhdh-jira-update`, which
applies `/mutation-gate` before any external write. If a caller asks this skill to
apply or post its output, say that the skill cannot write and name that handoff
instead.

The current milestone is **recommendation comments**, not PR creation or fixing
bugs. A close is advice for a human, never an action this skill takes. Dry-run
comments must be the same useful, linked, recommendation-first text a reviewer
would approve for Jira; do not say "Closing as" or imply a reproduction ran when
the evidence is only source inspection.

## Boundary with neighbouring skills

- `/rhdh-jira-authoring` owns what counts as a duplicate and how Jira work is
  phrased. This skill applies that definition to an aged-bug sample; it does not
  restate it.
- `/rhdh-jira-api` owns `acli` flags, JQL, field IDs, and the REST/GraphQL
  fallbacks. Read it before writing a query or debugging an empty result.
- `/rhdh-forge` owns GitHub and GitLab read mechanics. Use it for PR, commit, and
  issue lookups; this skill decides what a merged change proves.
- `/rhdh-context` owns repository and target-version context, including the
  release under review.
- `/rhdh-backport` owns backport mechanics and release-branch rules. This skill
  only decides whether a fix is already released on the stream under review.
- `/rhdh-jira-update` and `/rhdh-jira-link` own every Jira write: comment,
  transition, close resolution, and issue or web link.
- `/rhdh-jira-refine` judges whether an individual issue is ready to move
  forward. Load its readiness criteria when a still-valid bug needs a field or
  hierarchy assessment; this skill owns the aged-bug disposition, not general
  backlog hygiene.
- `/rhdh-plugin-bug-fix` owns reproduction and fixing for a still-valid bug.
  Hand the packet to it after the triage report, not inside this skill.
- `/prose-editing` owns the final prose pass on any comment a human intends to
  post. Invoke it once on the chosen comment before showing it for approval.

## Method in one page

1. **Select deterministically.** Aged means at least 90 days old. Sample 12–15
   aged RHDHBUGS tickets, stratified by Team (first component when Team is
   empty), plus a small number of controls whose disposition a reviewer already
   knows. Exclude customer-linked tickets from the sample and never propose a
   close on one. Export a corpus that also contains closed bugs: selection
   filters Done, young, and customer-linked tickets, so a broad export costs
   nothing and keeps closed duplicate targets reachable.
2. **Collect evidence.** Pull the issue, comments, links, fix and affects
   versions, then look for PRs, commits, release notes, code, and a current
   reproduction. Search the ticket key and the Jira keys it links to or mentions.
   Record where each fact came from.
3. **Adjudicate twice.** Produce the disposition and evidence in one pass, then
   repeat it independently. A close requires two passes that agree.
4. **Let policy grade the evidence.** The model supplies claims and citations,
   not a confidence number. The policy computes confidence from evidence
   strength, applies the disposition thresholds, and downgrades any close that
   fails a gate.
5. **Review locally.** Read `report.md` and the per-ticket packets. Hand an
   approved action to the write skill; leave every rejected or unclear ticket
   alone.
6. **Plan delivery, not reminders.** Read complete Jira comment history. Use a
   14-day configurable cooldown, but never repeat an unchanged recommendation or
   chase an outstanding request merely because time elapsed. The report includes
   `propose`, `suppress`, or `review_required` for each comment. Dry runs do not
   count as posted history. See the workflow's comment-delivery rules.

## Non-negotiable rules

- A ticket with any customer signal — `RHDH-Customer` label, RHDHSUPP or
  ACCOUNT link, customer field, or a support key in the text — is excluded from
  sampling and can never receive a close proposal.
- Duplicate retrieval must search open **and recently closed** tickets. The
  canonical report is often already Done, so an open-only export cannot find it.
  If the corpus has no closed tickets, the report says so; do not read a missing
  duplicate as proof that the bug is unique.
- A duplicate target is the older report. A candidate newer than the ticket
  under review is a hint only and is capped below the close floor.
- A duplicate close needs a lexical candidate score of at least 0.85 or an
  explicit *outward* Jira Duplicate link (this ticket duplicates the target),
  plus a direct citation, confidence of at least 0.85, and two agreeing
  independent passes. An inward "is duplicated by" link means the other ticket
  is the duplicate; it never justifies closing this one.
- A fix can land under another bug or PR. Search the ticket key and the Jira
  keys it links to or mentions before concluding a bug is unfixed.
- An already-fixed close needs a merged PR or commit, a confirmed release that
  carries the fix, direct evidence, confidence of at least 0.80, and two
  agreeing independent passes. The fix release must be no newer than the
  release under review: a fix that first ships later cannot close this ticket
  yet.
- A no-longer-valid close needs direct code, documentation, reproduction, or
  release-note evidence, confidence of at least 0.80, and two agreeing passes.
  Age alone is never evidence; without it the disposition is `needs_repro`.
- A missing affects or fix version is an evidence gap, not proof that the bug is
  old or fixed. Say so in the packet.
- Every ticket gets a proposed comment, including `unclear` and `needs_repro`,
  stating the disposition, the evidence, and one recommended next step. Jira keys
  and URLs in that comment are Markdown links. The comment is always a local
  proposal; nothing here posts it.
- Make the next step specific to the actual gap. Reuse existing reproduction
  steps rather than asking for them again. A missing publication link needs a
  Documentation check, not a product reproduction. Name the owning team when
  known; do not invent an owner or assign anyone.
- The definition of the same bug belongs to `/rhdh-jira-authoring`; this skill
  applies it and adds the close gates below. A candidate that would need a
  different fix is related, not duplicate.
- When the evidence is thin, the correct answer is `needs_repro` or `unclear`,
  not a guess. An abstention is a valid triage outcome.

## Commands

Run the bundled CLI from the skill directory. Every command is read-only.

```bash
python3 scripts/run_poc.py check --json
python3 scripts/run_poc.py select --input export.json --size 12 --out sample.json
python3 scripts/run_poc.py collect --input export.json --sample sample.json --out evidence
python3 scripts/run_poc.py template --sample sample.json --out assessments
python3 scripts/run_poc.py run --input export.json --sample sample.json \
  --assessments assessments --out report --current-release 2.1.0
python3 scripts/run_poc.py evaluate --packets report/packets.json --truth truth.json \
  --out report/evaluation.md --strict
```

`run --comment-cooldown-days 14` sets the minimum interval between proposed
follow-up comments. Even `0` does not bypass unchanged or pending-action checks.
`propose` is not write authorization. No autonomous posting mode exists here.

`--source acli` works for `select` when a Jira session is available. `collect`
uses cached PR state by default; `--gh` opts into read-only `gh` lookups. The full
walkthrough, fixture data, and expected numbers are in
[TESTING.md](TESTING.md).

## Completion

Complete when the run directory contains `report.md`, `packets.json`,
`summary.csv`, `manifest.json`, and one `proposed/KEY.md` per sampled ticket;
`report.md` is the one file a reviewer opens: the numbers, then one section per
ticket (no tables), each with the verdict, the evidence, the next step, and the
exact comment that would be posted;
every `proposed/KEY.md` leads with the exact comment that would be posted, with
Jira keys and evidence as links, followed by compact review details; every close
proposal has passed the policy gate and the verifier; every customer-linked
ticket is absent from the sample or explicitly marked close-disabled; and the
report states the decision-ready rate, the close-proposal count, and the evidence
gaps. Say out loud that nothing was written to Jira, and name the approved
handoff path for any proposal the human accepts.

## Talking to the human

Do not narrate data preparation, capability checks, pass counts, or provisional
runs. The human wants the result, not the pipeline.

When the run finishes, answer with three things and nothing else:

1. the bottom line in one sentence;
2. the path to `report.md`, said to be the one file that holds everything;
3. any decision the human must make now — a close to approve, or an unclear
   ticket that needs an owner.

Do not paste JSON, do not paste a per-ticket table (the report has no tables),
and do not offer intermediate artifacts as the answer. If the human asks where
the output is, give the single file path first; the machine files are a
footnote.
