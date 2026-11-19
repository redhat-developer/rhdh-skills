# Policy 3 assessment and artifact contract

## Cutover from closure-only policy 2

Policy 3 restores comment-first triage: every selected, investigated issue has a
nonempty `proposedComment` and `recommendedStep`, even when uncertain or delivery
is suppressed. `comment_only` is the normal non-closing action.
`propose_close_duplicate`/`propose_close_fixed` mean advisory human-review
recommendations only; no action field executes anything. `abstain` remains a
safety state for ineligible/unsafe inputs, not a successful substitute for
investigating a selected bug. Valid selection should exclude customer/Done issues
before assessment.

Sample manifests, packets and run manifests use `schemaVersion: 3`; run manifests
record `policyVersion: 3`. Do not reuse old policy-1/2 counts or silent-abstention
reports as policy-3 results. Regenerate selection and investigate the new
validation fields. Missing assessments, invalid/blank/unknown dispositions and
malformed input block `run`; they do not create a successful "unclear" report.
An investigated assessment explicitly concluding `unclear` is supported.
Nonempty output directories are refused, so stale drafts cannot survive a rerun.

## One assessment per selected issue

Use `template` to create `assessments/KEY.json`, then fill it through agent
investigation. The filename, `key` and sampled issue must agree. Valid
`disposition`: `duplicate`, `already_fixed`, `still_valid`, `no_longer_valid`,
`needs_repro`, `unclear`. Unknown fields do not create new policy capabilities.

Each `evidence` item requires:

```json
{
  "type": "code",
  "ref": "https://github.com/example/product/blob/VERIFIED_TAG/path/to/source.ts",
  "why": "Explain what this exact released path establishes about the reported trigger.",
  "strength": "direct"
}
```

The URL is illustrative and must be replaced by an inspected artifact. Types:
`jira`, `pr`, `commit`, `release_note`, `code`, `doc`, `repro`, `comment`, `ci`
(CI/nightly job results, for example a prow build page).
References must be actual HTTPS URLs or Jira keys; bare SHAs/local pseudo-links
are not definitive citations. Strength: `direct`, `strong`, `supporting`, `limited`.
`limited` preserves a lead or access/provenance limitation with zero proof weight;
it cannot satisfy a direct-evidence gate. Do not upgrade unread artifacts to proof.
Invalid citations are retained in `invalidEvidence` and block definitive proof.
An input confidence is ignored; the policy computes its own non-probability score.

## Current-release validation

### Requirement-level investigation

The agent workflow uses `run --require-investigation`. Each assessment supplies
`investigation` with `status` (`completed` or `blocked`), exact numeric `release`,
plain-text `scope`, causal `mechanism`, and nonempty `requirements`. Each
requirement has `statement`, `observed`, `result` (`satisfied`, `violated`,
`unknown`), `method` (`code`, `runtime`, `documentation`, `dependency`, `artifact`
or `report`), and nonempty `refs` already present in `evidence`. A positive or
negative observation needs direct method-matching evidence; `report` is only
for an unknown behavioral result, not proof of current behavior. Historical
reporter validation remains separately scoped evidence, not a current test.

`completed` cannot contain unknown requirements. `blocked` requires an unknown
requirement and a specific nonempty `blocker`. Missing or `not_started` records
are rejected by the strict workflow. Older inputs without the block can still
be replayed without the flag, but their investigation is `not_recorded`, not
certified complete. These structural checks do not prove causal correctness or
version applicability; the agent must read and evaluate the evidence.

Requirement observations survive unrelated closure-review failures. Their
scoped outcome is separate from advisory disposition and delivery; it cannot
bypass the existing proof gates or manufacture release/runtime validation.

Optional `fixEvidence` records scoped progress separately from production closure
proof. Its states, dimensions and direct-citation requirements are defined in
[discovery](discovery.md). `discovery` in output packets retains local routes,
collected queries, candidate provenance and gaps; it is never proof. `sameRecord`
marks self/alias comparisons, which cannot authorize duplicate closure. Existing
policy-3 inputs without the optional block retain the existing full proof gates.

## Read-only fix plan

Optional assessment block, required by `run --require-fix-plan`:

```json
{
  "approach": "Accept the notebook file-type set in the chat upload validator and share the error copy.",
  "areas": [
    {"repository": "owner/repo", "paths": ["plugins/chat/src/utils/attachment-utils.ts"]}
  ],
  "complexity": "small",
  "refs": ["https://github.com/example/product/blob/abc123/handler.ts"]
}
```

- `approach`: the concrete remediation approach — what a fix would change and
  why that resolves the reported failure. For `duplicate`, `already_fixed` and
  `no_longer_valid` verdicts, describe the resolution action instead.
- `areas`: where a fix would land; each entry needs a `repository` and a list
  of `paths`. Omit it when no product area applies.
- `complexity`: `trivial`, `small`, `moderate`, `large`, or `none`.
  `none` is only valid for the resolution-only dispositions above.
- `refs`: evidence the assessment already cites, backing the approach.

A fix plan is read-only guidance for the separately authorized fix workflow.
It is not a change, not proof that a fix exists or works, and not closure
permission; the definitive proof gates are unchanged. The report renders it
per ticket and counts plans in the summary.

Output `verification` retains acquired source/diff/ancestry and OCI metadata from
`run --verification`. The CLI validates saved receipts and release identity; see
[acquisition](verification-acquisition.md). These observations are separate from
the investigator's acceptance judgment and do not auto-populate resolved flags.

The following is a **placeholder shape**, not a valid assessment to run unchanged:

```json
"validation": {
  "release": "VERIFIED_RELEASE",
  "method": "code",
  "result": "persists",
  "summary": "Explain why the reported conditions still reach the defective path in this release.",
  "refs": ["https://github.com/example/product/blob/VERIFIED_TAG/path/to/source.ts"]
}
```

- `release`: exact numeric product release matching `--current-release`, resolved
  by the agent through `/rhdh-context`; never use the placeholder literally.
- `method`: `code`, `runtime`, `documentation` or `dependency`.
- `result`: `persists`, `resolved` or `unknown`.
- `summary`: causal explanation tied to this bug's conditions and scope.
- `refs`: nonempty exact references in `evidence`, with direct evidence of the
  corresponding kind. Code uses `code`/`pr`/`commit`; runtime uses `repro`;
  documentation uses `doc`/`release_note`; dependency inspection uses the
  relevant released dependency/code/doc/commit record.

`still_valid` requires valid cited `persists` validation. `no_longer_valid`
requires valid cited `resolved` validation **and** `proof.scopeRemoval` explaining
the whole-issue scope change. Otherwise the verdict downgrades to `unclear` and
the draft states the limitation. `repro` can preserve an actual result and its
release/notes; `not_run` is not validation. A current-release result contradicting
the verdict must remain visible, not be ignored to salvage a conclusion.

## Structured definitive proof

`proof` maps named claims to objects with a causal plain-text `summary` and
nonempty `refs` listing exact direct references from `evidence`:

| Disposition | Claims and accompanying fields |
|---|---|
| `duplicate` | `sameFailure`, `sameTrigger`, `sameFix`, `canonical`; `duplicateOf` is the one retrieved canonical key. The first two claims cite both reports. |
| `already_fixed` | `fixMatches`, `releaseContains`, `validation`; matching proof directly cites the named incorporated artifact and release proof the target-inclusion record. |
| `no_longer_valid` | `scopeRemoval`, plus the resolved validation above. |

See the [rubric](disposition-rubric.md) for thresholds, chronology and causal
gates. An already-fixed assessment also supplies `fix`:

```json
"fix": {
  "pr": "https://github.com/example/product/pull/123",
  "commit": "",
  "merged": true,
  "coversWholeIssue": true,
  "release": "VERIFIED_CARRYING_RELEASE",
  "released": true,
  "reviewRelease": "VERIFIED_RELEASE",
  "containedInReviewRelease": true
}
```

All URLs/versions here are placeholders. `pr` or `commit` must name the inspected
linked artifact; both must be links if both are supplied. Booleans require JSON
`true`, not strings or truthy numbers. The carrying release is no newer than the
target; `reviewRelease` equals the exact target. These flags assert separately
verified facts, not evidence. Attach direct matching/release/validation claims;
the offline CLI does not independently fetch or verify them.

`review: {"independentPasses": 2, "agree": true}` summarizes two actually
independent, agreeing fresh-context reviews for duplicate/fixed recommendations.
Save their rationales/citations/context provenance locally and identify them in
`notes`. No Boolean proves independence. Preserve disagreement in `notes` and
use `agree: false`; never fabricate agreement from reconciliation. Assessment
`comment` and `recommendedStep` are legacy inputs, not overrides of generated
payloads or a way around failed proof.

An uncertain assessment may supply `nextCheck` with `method`
(`code`, `runtime`, `documentation`, `dependency`, or `artifact`), a single
bounded `question` ending in `?` (up to 400 characters, no newlines), and `refs`
listing exact evidence references. The composer renders an investigation
question, never an executable command or a closure action. Failed definitive
proof gates cannot use it to override the safe fallback. The investigator owns
the question's factual relevance; structural validation cannot establish that.

Preserve validation limits in outward uncertainty, including source-to-image
binding, post-release mappings, fresh-install scope and unrun benchmarks. When
validation lacks direct proof, label its account unaccepted and the outcome
unknown rather than dropping its limitations or certifying persistence.
Auto-link only recognized RHDH Jira references in prose, not key-shaped CVE or
hash terminology. Explicit citations still need the investigator's verification.

## Delivery metadata

`commentPlan` contains `status` (`propose`, `suppress`, `review_required`),
`reason`, stable `reference`, `cooldownDays` and applicable prior-comment metadata.
The exact generated body and `Triage reference` footer remain in packets and the
report for every selected finding, independent of status. Complete Jira comments,
not `updated` or local review folders, are the posting history.

Where changed advice follows an earlier marked request, `followUp` names
`priorCommentId`, a `state` of completion/supersession and cited `evidence` of the
actual result. The agent verifies its truth; the planner only checks structure.
The [rubric](disposition-rubric.md) owns cooldown, repeat suppression and history
gates. A `review_required` preview is not authorization to post.

Known but unread customer fields block closure advice and delivery. A supported
private code/documentation/dependency finding may still be classified while its
comment remains `review_required`; this does not certify non-customer status.
Resolve field applicability through the authenticated adapter rather than
silently treating an absent global field as empty.

## Outputs and provenance

The run directory has one human-facing surface: `report.md` (plus `proposed/`
draft files). Every machine artifact lives under `audit/` so a reviewer opens
exactly one file.

- `report.md`: one reviewer-facing file with **all exact drafts** and their
  disposition, proof/validation or uncertainty, fix plan, owner when known,
  next step and delivery reason. Suppressed/review-required drafts are clearly
  restricted.
- `proposed/KEY.md`: same exact draft/reference plus local details, only for
  non-suppressed findings. Review-required files remain blocked from delivery;
  all-suppressed results may have no `proposed/` directory.
- `audit/packets.json`: all findings, original/rejected claims, evidence, validation,
  proof, fix plan, candidate/canonical facts, fix metadata, review/disagreement, gaps,
  verifier failures, `proposedComment`, `recommendedStep` and `commentPlan`.
- `audit/summary.csv`: one row per packet. An advisory close action is not an executed
  transition; disposition and delivery remain separate.
- `audit/sample.json`: selection scope, selected/control entries, eligibility counts
  and exclusions with reasons; retained input selection is part of the audit.
- `audit/manifest.json`: target release and `releaseEvidence` URL, input paths/SHA-256
  hashes, bundled module hashes, policy/thresholds, counts, delivery policy, collection coverage/failures
  and `writes: []`. `coverage.selectionComplete` only refers to eligible records
  in the supplied export. `corpusHasClosed` is not exhaustive corpus coverage.

`--evidence` attaches actual collection results and errors; its absence cannot
be called a complete forge search. Record corpus query/snapshot provenance and
review context references in the local inputs/notes where not supplied by the
collector. The CLI records evidence; it does not certify the release URL, field
coverage, independent reviewers or factual accuracy. Keep private exports and
live reports out of the PR.

## Evaluation contract

`labels.json` maps keys to `{"disposition": "…", "duplicateOf": "…"}`; the
canonical is required for a duplicate label. Use real, independent known answers.
Report label-to-packet and packet-to-label gaps, disposition mismatches and
precision/recall, not just a closure count. Strict evaluation fails on missing
coverage, false definitive conclusions (including false `still_valid`) or false
close proposals/wrong canonical targets. Uncertain results can reduce recall;
they do not count as proof of universal correctness. See
[verification](verification.md) for acceptance scenarios.
