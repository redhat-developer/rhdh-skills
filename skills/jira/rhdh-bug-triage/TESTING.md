# Verify recommendation-only triage

Python 3.9+ is required. The bundled policy/report path is stdlib-only and offline;
Jira/GitHub reads are optional collection inputs, never writes.

## Repository verification

From the repository checkout, run `uv run pytest`, `uv run ruff check .`, and
`uv run ruff format --check .`. Unit fixtures are synthetic, not proof that any
real Jira issue should close. No external service is needed for these checks.

The policy tests must include valid duplicate/fixed controls and adversarial
cases that change one gate at a time. A zero-proposal run alone is not enough
to demonstrate working positive paths.

## Offline/local dry run

From the installed skill directory, use saved complete exports and independently
reviewed assessments. See the [input schema](references/report-schema.md).

```bash
python3 scripts/run_poc.py select --input eligible-export.json --size 12 --out sample.json
python3 scripts/run_poc.py template --sample sample.json --out assessments
python3 scripts/run_poc.py run --input eligible-export.json --sample sample.json \
  --corpus broad-export.json --assessments assessments --out new-review \
  --current-release 2.1.0 --comment-cooldown-days 14
```

The example release must be replaced by the actual verified released target.
The sample export must already be enriched/version-filtered; the bundled selector
does not compare affects versions. The duplicate corpus must include closed
reports and fully enriched canonical candidates. No credentials belong in files
or command arguments.

## Required contracts

1. Only high-confidence duplicate/already-fixed findings with complete cited
   proof, appropriate target chronology/release inclusion and independent
   agreement produce closure recommendations.
2. Valid Re / verdict / Recommendation / Proof payloads are identical in
   `report.md`, `packets.json` and their `proposed/KEY.md`, including the reference.
   The recommendation is advice, not a mutation receipt. A legacy free-form draft
   cannot replace it or recommend closing a different issue.
3. Unsupported, missing, contradictory, partial, unreleased and weak findings
   have `action: abstain`, empty comment/next step and local audit reasons. There
   is no request for a human to reproduce them and no proposed handoff file.
4. Duplicate proof compares both reports' failure and trigger, explains one
   required fix, and names one canonical tracker. A newer/undated target, reverse
   link, customer target, or target that is itself a duplicate cannot pass.
5. Fixed proof matches the named merged/incorporated artifact, covers the whole
   issue, confirms shipment and verifies inclusion in the exact release being
   reviewed. An earlier stream's release is insufficient without that inclusion.
6. Re-verification must reject tampered confidence, proof, target, release,
   artifact, merge state, whole-scope and independent-review claims.
7. Complete-history and cooldown tests use synthetic comments with IDs/times.
   Test exact repeats after a year, changed advice within 14 days, pending work
   after 14 days, unrelated replies, wrong/malformed follow-up, invalid markers,
   future timestamps, unmarked owner holds and customer/Done issues. No local
   proposal may masquerade as Jira posting history. Suppression produces no
   handoff file and no notification.
8. ADF inline cards/link marks must retain hidden Jira/PR/customer references.
   Failed/rate-limited PR searches must remain distinguishable from successful
   zero matches and cache-only collection. Similar numeric key prefixes must not
   contaminate key searches.
9. Output directories must be fresh. Reusing a nonempty directory fails without
   modifying it, so an earlier close proposal cannot survive as a new result.
10. `manifest.json` always records `writes: []`; no CLI apply/post/write path exists.

## Migration check

Old policy-1 assessments without structured proof must abstain rather than
silently retaining their previous close count. Consumers must handle schema 2,
`abstain`, and absent proposal files. Do not manufacture proof or agreement to
make old examples pass. Synthetic controls must have internally consistent dates;
an explicit duplicate link must not bypass a newer canonical target.

## Evaluation and limits

```bash
python3 scripts/run_poc.py evaluate --packets new-review/packets.json \
  --truth truth.json --out new-review/evaluation.md --strict
```

Use actual known-answer labels. False closures fail strict evaluation. A high
abstention rate is allowed, but record recall and label coverage rather than
claiming 100% success from no proposals. Fixture scores are not calibrated
probabilities, live validation, or guarantees of perfect judgments.

Before any future approved writer, separately test fresh reads/customer checks,
per-issue serialization, preserved references through ADF conversion and
readback, and uncertain-delivery reconciliation. Those write-path behaviors
are not implemented or certified by this skill.
