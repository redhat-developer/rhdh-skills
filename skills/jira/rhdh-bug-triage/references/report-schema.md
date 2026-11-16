# Policy 2 input and artifact contract

## Breaking change from policy 1

The default output is recommendation-only, not a comment for every issue.
`still_valid`, `no_longer_valid`, `needs_repro`, `unclear`, missing assessments,
and failed close gates produce `action: abstain`, empty `proposedComment` and
`recommendedStep`. No `comment_only`, reproduction-request, obsolete-close,
or keep-open action is emitted. Legacy free-form `comment` and `recommendedStep`
inputs cannot override the generated recommendation.

Old duplicate/fixed assessments without structured proof now abstain. Add and
independently verify the required proof; do not fill flags merely to restore an
old close count. Packets and manifests use `schemaVersion: 2`, `policyVersion: 2`.
Sample manifests remain version 1. Consumers must tolerate absent `proposed/`
files/directories and must not interpret old artifacts as new recommendations.
Nonempty output directories are refused without modification.

## Assessment input

One `KEY.json` object per sampled ticket. Its `key` must match the issue under
review. Valid internal dispositions: `duplicate`, `already_fixed`, `still_valid`,
`no_longer_valid`, `needs_repro`, `unclear`. Unknown dispositions or malformed
input abort; missing assessments abstain. Customer-linked issues never close.

Every evidence item needs:

```json
{"type": "jira", "ref": "RHDHBUGS-1100", "why": "Describe what this artifact proves.", "strength": "direct"}
```

Types: `jira`, `pr`, `commit`, `release_note`, `code`, `doc`, `repro`, `comment`.
References must be actual HTTPS links or Jira keys; bare commit SHAs and local
pseudo-references are not reviewable closure citations. Strength is `direct`,
`strong`, or `supporting`. Invalid items are retained in `invalidEvidence` and
block closure. An input confidence is ignored.

`proof` is an object of named claims, each with plain-text `summary` and nonempty
`refs` listing exact references from `evidence`. Each claim needs direct evidence.
Use real artifact facts, not assertions that a score or a Boolean is high enough.

Required proof claims:

- Duplicate: `sameFailure`, `sameTrigger`, `sameFix`, `canonical`. The first two
  must directly cite both compared reports. Canonical selection directly cites
  the retained tracker. `duplicateOf` names exactly one retrieved, older tracker.
- Already fixed: `fixMatches`, `releaseContains`, `validation`. Matching proof
  directly cites the named PR/commit. Release inclusion directly cites
  `release_note` evidence (a release record or verified tag/ancestry comparison).
  Validation directly cites regression coverage/code analysis or a real result;
  a Jira fixVersion alone does not qualify.

Illustrative duplicate structure, not evidence about real issues:

```json
{
  "key": "RHDHBUGS-1234",
  "disposition": "duplicate",
  "duplicateOf": "RHDHBUGS-1100",
  "evidence": [
    {"type": "jira", "ref": "RHDHBUGS-1234", "why": "Selecting a filter drops the next search keystroke.", "strength": "direct"},
    {"type": "jira", "ref": "RHDHBUGS-1100", "why": "The older report describes the identical filter-update focus path.", "strength": "direct"}
  ],
  "proof": {
    "sameFailure": {"summary": "Both lose focus and drop the next character.", "refs": ["RHDHBUGS-1234", "RHDHBUGS-1100"]},
    "sameTrigger": {"summary": "Both start when selecting a catalog-table filter.", "refs": ["RHDHBUGS-1234", "RHDHBUGS-1100"]},
    "sameFix": {"summary": "Restoring focus after that filter update addresses both reports.", "refs": ["RHDHBUGS-1100"]},
    "canonical": {"summary": "Retain the older established implementation tracker.", "refs": ["RHDHBUGS-1100"]}
  },
  "review": {"independentPasses": 2, "agree": true}
}
```

The actual corpus must substantiate chronology and target facts, and the lexical
or verified outward-link gate still applies. Canonical issue numbers do not
prove chronology. An explicit link does not bypass a newer/undated target.

For already fixed, also supply this `fix` object using verified values:

```json
{
  "pr": "https://github.com/example/repository/pull/123",
  "commit": "",
  "merged": true,
  "coversWholeIssue": true,
  "release": "2.1.0",
  "released": true,
  "reviewRelease": "2.1.0",
  "containedInReviewRelease": true
}
```

The URL is illustrative. `pr` or `commit` must name a directly cited linked
artifact; if both are supplied both must be links. Boolean fields require JSON
`true`, not strings or truthy numbers. `release` must be numerically comparable
and no newer than the review target. `reviewRelease` must equal that target and
`containedInReviewRelease` attests separately verified target inclusion. These
are audited reviewer claims; the offline CLI does not independently query their
truth. Attach direct release-inclusion evidence in `proof.releaseContains`.

Two independent agreeing reviews are mandatory:

```json
"review": {"independentPasses": 2, "agree": true}
```

Optional `notes` retain conflicts and provenance. Retain disagreements honestly;
do not set agreement to true just because one pass later adopted another result.

## Delivery and follow-up

Complete Jira comments are the posting history, not local runs or `updated`.
Flattened adapters must attest `commentsComplete: true` only after actual full
pagination. Missing/truncated history, malformed markers/timestamps and unmarked
discussion yield `review_required`. Equivalent legacy advice and owner holds need
human review; the planner does not infer their meaning.

`commentPlan` has `status` (`propose`, `suppress`, `review_required`), `reason`,
`reference`, `cooldownDays`, and applicable prior-comment metadata. Abstentions
always suppress and have no comment/footer. Identical posted advice suppresses
indefinitely, even after completion. Changed advice needs cooldown expiry plus:

```json
"followUp": {
  "priorCommentId": "12345",
  "state": "superseded",
  "evidence": [{"type": "comment", "ref": "https://redhat.atlassian.net/browse/RHDHBUGS-1234?focusedCommentId=12346", "why": "Describe the actual result/supersession.", "strength": "direct"}]
}
```

Check the follow-up's truth independently. The planner checks structure, not
external truth. Preserve the stable `Triage reference` footer through any approved
handoff/ADF conversion/readback. Prose/evidence ordering alone does not create a
new identity. A plan is not authorization, a write lock, or a posting receipt.

## Artifacts and metrics

- `report.md` is the single reviewer-facing file. It surfaces only qualifying
  duplicate/fixed recommendations and full Re / verdict / Recommendation / Proof
  / Confidence payloads, plus ownership when known and delivery restrictions.
  No per-ticket abstention comments or investigation queue is presented.
- `proposed/KEY.md` starts with the exact same payload/reference, followed by
  local review details. Only surfaced recommendations get a file. Suppressed
  repeats and abstentions do not; there may be no `proposed/` directory at all.
- `packets.json` retains every sampled issue, internal disposition, proof,
  evidence, canonical candidates and creation dates/customer signals/resolution,
  fix metadata, review state, gaps, verifier failures and delivery plan. This is
  audit data, not a list of commands or permissions to act.
- `summary.csv` has one audit row per packet; `action` is the authoritative
  decision, not the internal disposition or raw score.
- `manifest.json` records inputs, target/corpus, thresholds, counts, delivery
  policy and `writes: []`. `closeProposals` counts proof-qualified findings;
  `surfacedRecommendations` excludes suppressed delivery. `abstained` is explicit.

Evaluation counts predictions from proposed actions, not unqualified internal
guesses. A wrong canonical target is a false duplicate close. `--strict` fails
on false closures, not on abstention rate. Coverage/recall remain visible: a
run that abstains on everything has not proved backlog cleanup or accuracy.

Exit codes: 0 completed; 1 failed capability check or strict false-close failure;
2 invalid input, missing sample key, occupied output directory or adapter failure.
