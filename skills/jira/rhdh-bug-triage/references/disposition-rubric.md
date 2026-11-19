# Disposition and comment rubric

Every selected bug receives an investigated disposition and an exact local
comment draft. A failed definitive gate becomes an explicit `unclear` comment,
not a false positive or a silently empty payload. Selection and customer/Done
exclusions are defined in the [workflow](../workflows/triage-aged-bugs.md).

## Dispositions

| Disposition | Required basis | Recommended next step |
|---|---|---|
| `duplicate` | Gates below; one authoritative tracker | Human review of retaining the canonical and closing this redundant report |
| `already_fixed` | Gates below; a whole-issue incorporated fix in the exact release | Human review of the cited fixed disposition |
| `still_valid` | Cited current-release validation with `result: persists` | Keep open; route the specific supported finding to the known owner/team |
| `no_longer_valid` | Cited current-release validation with `result: resolved` plus a causal scope-removal reason | Human review of the obsolete-scope conclusion; no automatic close |
| `needs_repro` | A specific validation gap and a concrete reproduction plan, no claimed result | Inspect or run that narrowly specified check in a separately authorized environment |
| `unclear` | Specific missing/conflicting evidence, including failed definitive gates | Resolve the single material gap identified by the investigation |

`unclear` is a last resort, not a resting state. Before recording it, the
investigator (or a dedicated resolver pass) attempts the named missing check
through read-only means — public CI/nightly job results, deeper source tracing
including vendored or built code, package-registry metadata, release records.
Only when that fails may the result stay `unclear`, and the draft names what
was attempted. The fail-closed proof gates never loosen to manufacture
certainty: escalation changes how hard the system looks, never what counts
as proof.

For definitive validity/obsolescence, `validation.release` must equal the verified
release under review. Its method is `code`, `runtime`, `documentation` or
`dependency`; its summary and references must causally establish the result.
For `no_longer_valid`, also supply cited `proof.scopeRemoval` explaining why the
whole reported trigger is no longer in scope. Age, silence or one failed repro
without understood cause does not establish obsolescence. Unsupported validation
or unresolved contradictory reviews downgrade either verdict to `unclear`.

An open Jira status, no PR search hit, an old affects version or an unchanged
ticket cannot establish `still_valid`. The absence of a found fix is not
positive evidence that the defect persists. "No evidence of fix found within
these searches" must remain qualified; do not translate it into "not fixed".

## Duplicate — minimum policy confidence 0.85

Require causal proof and the evidence-derived confidence threshold:

- Lexical similarity only retrieves/ranks candidates; it is not a minimum
  eligibility score. A low-similarity pair can qualify with complete direct causal
  proof and real independent agreement. An explicit Duplicate link is a lead,
  never a substitute for that proof. An inward "is duplicated by" link does not
  authorize closing the canonical.
- Cited `proof.sameFailure`, `proof.sameTrigger`, `proof.sameFix` and
  `proof.canonical`. Failure and trigger cite **both** compared reports. Explain
  why one required change resolves both; separate fixes mean related, not duplicate.
- Exactly one fully retrieved, demonstrably older authoritative target, selected
  by creation timestamps and established investigation/ownership, not key numbers
  or newest activity. A newer/undated or customer-linked target requires separate
  human selection and cannot pass this implementation's gate.
- Follow duplicate chains to the real tracker. A target itself resolved as a
  duplicate is not canonical. No recommendation may both retain and close the
  same tracker in a cluster.

## Already fixed — minimum policy confidence 0.80

Require cited `proof.fixMatches`, `proof.releaseContains` and `proof.validation`:

- Name the exact merged PR/incorporated commit and inspect its implementation.
  The direct citation must match that artifact; closed-unmerged is not fixed.
- Explain why it resolves the **whole** reported failure. A similar symptom,
  partial change or regression test for another path is insufficient.
- Verify a shipped carrying release and inclusion in the **exact target release**.
  Numeric ordering, a planned fixVersion, development branch content or an older
  stream's tag cannot establish target-release ancestry.
- Cite appropriate regression coverage, code analysis or actual runtime evidence
  for the reported trigger. Source inspection must never be described as a test run.

`merged`, `released`, `coversWholeIssue` and `containedInReviewRelease` are audited
assertions, not proof. The offline checker does not visit artifacts or establish
their truth. Missing or conflicting proof yields an `unclear` draft, including
when a likely fix is merged but not yet shown to be in the reviewed release.
No implementation, fix PR or backport follows from this finding.

## Independent review and confidence

Duplicate/fixed recommendations require two genuinely independent, agreeing
reviews in fresh contexts, each reading the sources without the other's
conclusion. Save separate rationales, citations and context provenance locally.
A copied pass count/Boolean, repeated prompt in one context or reconciliation
after seeing the first result is not independent agreement. Preserve disagreement;
it blocks a definitive recommendation even above the score threshold.

The CLI computes an evidence-derived score, not a model-supplied probability.
Direct/strong/supporting weights and corroboration affect that score; no number
overrides missing causal proof, release checks or review. Never claim 100%
accuracy, force a minimum positive count or hide uncertain cases to raise precision.

## Exact comment shape

Keep drafts concise and specific. This is a shape, not evidence about a real bug:

```text
Re: [KEY — title]
Disposition: [verdict and bounded conclusion]
Evidence: [short causal comparison with direct source links]
Validation: [exact release; method; observed result, or specific unknown]
Owner: [existing assignee/team if known; do not invent ownership]
Recommended next step: [one evidence-supported recommendation]
Triage reference: [stable generated reference]
```

Duplicate/fixed drafts retain the named causal proof and the computed confidence
with its "not a probability" qualification. Validation may be represented by a
cited proof claim; unknown cases must identify what was not established. Never
announce "Closing as", invent a runtime result, leak rejected proof as fact, or
use generic "please reproduce", stale-ticket nudges or pending-work reminders.
Legacy free-form `comment`/`recommendedStep` cannot override policy-generated text.
Apply the workflow's single prose pass without changing verified meaning.

Every investigated bug also carries a read-only `fixPlan` (see the
[assessment schema](report-schema.md)): the remediation approach, the areas a
fix would touch, and a complexity estimate. The plan is rendered in the report
beside the draft, not inside the Jira comment — comments stay concise while
the reviewer still sees exactly where a fix would land. A plan is guidance for
the separately authorized fix workflow, never a change or closure permission.

## Delivery is separate from disposition

`commentPlan.status` is `propose`, `suppress` or `review_required`; none is a write
receipt or authorization. Every exact draft remains visible in `report.md` and
`audit/packets.json`, including suppressed repeats and review-required cases. Only
non-suppressed drafts get `proposed/KEY.md`.

Identical marked advice suppresses indefinitely. Changed advice requires the
configurable cooldown (default 14 days) **and** cited completion/supersession of
the latest request. Silence, unrelated replies or passage of time do not clear
pending work. Missing/truncated history, unreliable markers/timestamps or
unmarked discussion require review for equivalent advice and owner holds; do
not claim the planner understands legacy comments. Local runs are not history.

No remote writer is called in this dry run. Any future external write needs a
separate explicitly scoped workflow and `/mutation-gate`, fresh issue/customer
and history reads, per-issue serialization and delivery reconciliation. These
writer/exactly-once behaviors are not implemented or certified here.
