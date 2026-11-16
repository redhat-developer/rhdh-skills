# Triage aged bugs for closure opportunities

One entry point, two outward results: duplicate or already fixed. Follow the
[rubric](../references/disposition-rubric.md) for proof, confidence, canonical
selection and delivery gates. Insufficient proof means silent abstention, not a
new Jira investigation request. This workflow and its CLI never mutate Jira.

## 1. Resolve scope and capability

Invoke `/rhdh-context` to resolve the actual released product under review.
Development `package.json`, planned fixVersions, or a CLI default are not release
evidence. Invoke `/rhdh-jira-api` for authenticated read mechanics and field IDs.

```bash
python3 scripts/run_poc.py check --json
```

Use an authenticated host export if acli cannot read. Do not retrieve credentials,
repair login here, or invent missing fields. Search and view support different
field sets in some acli versions: if search rejects `*all`, use supported search
fields followed by complete issue views through `/rhdh-jira-api`. Do not silently
proceed with missing customer fields, descriptions or truncated comment history.

## 2. Select and retain the broad duplicate corpus

Select 12–15 open, non-customer reports at least 90 days old, stratified by team
or component. Require comparable affects versions older than the release under
review; the age-only selector does not enforce version comparison. Enrich and
filter first, recording all exclusions. Unknown versions do not prove eligibility.
Any previous-local-review coverage exclusion is run-local bookkeeping, never
evidence that a Jira comment was posted.

Keep a separate corpus containing open **and closed** reports; a canonical issue
can be closed. Record retrieval coverage and missing fields. Fetch full candidate
records before choosing a tracker, including creation date, resolution, customer
signals, links, description and discussion. Resolve duplicate chains.

```bash
python3 scripts/run_poc.py select --input eligible-export.json --size 12 --out sample.json
```

Optional controls must have genuine known answers. Do not invent controls or
ground truth to claim accuracy. No minimum close/recommendation rate is required.

## 3. Search for duplicate and existing-fix evidence

```bash
python3 scripts/run_poc.py collect --input eligible-export.json --sample sample.json \
  --out evidence --forge-cache forge-cache.json
```

Follow [evidence sources](../references/evidence-sources.md). Read ADF inline cards
and link marks as well as visible text; hidden Jira references often lead to the
actual fix. Inspect candidate meaning, not just titles. Search the sampled key,
linked/mentioned keys and relevant corpus candidates. The collector searches at
most five linked keys; investigate its recorded `unsearchedLinkedKeys` when
needed rather than claiming complete coverage.

Use `/rhdh-forge` for exact PR/commit state, diff, regression coverage and tag
ancestry. Read linked PRs even if key search fails. Record failed/rate-limited
searches separately from successful zero-match results. Cache-only collection
does not search GitHub. Neither case proves that no fix exists.

For fixed candidates, verify the matching change is incorporated, the fix shipped,
and the exact target release contains it. For duplicate candidates, compare the
same failure/trigger/fix and select one authoritative tracker. If source or
history contradicts the hypothesis, abstain rather than stretching the evidence.

## 4. Adjudicate independently twice and write cited proof

```bash
python3 scripts/run_poc.py template --sample sample.json --out assessments
```

Fill [structured assessments](../references/report-schema.md). Run the second
review in a fresh context without the first conclusion. Record real agreement
or disagreement; never turn reconciliation into invented independent agreement.
Evidence strengths are inputs; confidence is computed. Proof summaries must
explain the causal comparison, not merely say "same bug" or "fixed".

Do not create outward `unclear`, `still_valid`, obsolete or reproduction comments.
Those may be internal evidence states only. No fix implementation, build/cluster
operation, backport, reassignment, or PR creation is authorized by this workflow.

## 5. Run policy in a fresh output directory

```bash
python3 scripts/run_poc.py run --input eligible-export.json --sample sample.json \
  --corpus broad-export.json --assessments assessments --out new-review \
  --current-release 2.1.0 --comment-cooldown-days 14
```

Replace the example release with the verified target. The policy and verifier
both fail closed. Any unsupported finding or failed gate becomes `abstain` with
no draft or reproduction request. Output directories must be fresh so a rerun
cannot leave an old close proposal masquerading as a new recommendation.

- `report.md`: the one reviewer-facing file, only qualifying recommendations,
  proof, confidence, ownership when known and approval/delivery status.
- `proposed/KEY.md`: exact surfaced payload plus local review details; no files
  for abstentions or suppressed repeats. Zero recommendations can produce no
  `proposed/` directory.
- `packets.json`, `summary.csv`, `manifest.json`: full local audit, including
  reasons for abstention, rejected claims, search/selection provenance where
  supplied, and `writes: []`. A local run is not posted-comment history.

## 6. Review and hand off only approved recommendations

Review the exact Re / verdict / Recommendation / Proof body in `report.md`.
Reject any recommendation stronger than its citations. A `review_required`
delivery state is not permission to post; resolve history/legacy-comment concerns
first. Suppression is a successful no-op, not a trigger to remind anyone.

If the human approves an external action, invoke `/prose-editing` once for Jira
prose and hand the exact preserved recommendation and intended operations to
`/rhdh-jira-update` under `/mutation-gate`. Approval to post a rationale is not
approval to close; closure needs its own stated approved operation. No mutation
is performed by this skill. Report nothing awaiting approval when the result
contains no recommendations.

## Optional evaluation

```bash
python3 scripts/run_poc.py evaluate --packets new-review/packets.json \
  --truth truth.json --out new-review/evaluation.md --strict
```

Use actual reviewer ground truth. False closures fail strict evaluation; a high
abstention rate does not. Coverage, precision and recall remain visible so silent
abstention cannot masquerade as a successful comprehensive backlog cleanup.
