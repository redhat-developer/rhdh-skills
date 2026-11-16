# Closure recommendation rubric

## Supported outward results

Only **duplicate** and **already fixed** may produce recommendations. Other
internal dispositions and failed close gates become `action: abstain`. Leave
Jira unchanged: no draft comment, handoff file, reproduction request, reminder,
or notification. Local evidence gaps are not tasks automatically assigned to
humans. Do not claim that abstention proves an issue is unique or unfixed.

## Shared close gates

Every recommendation needs all of these:

1. The issue under review is open and has no customer signals. Exclude
   `RHDH-Customer`, RHDHSUPP/ACCOUNT links or text references, populated customer,
   case, impact, or SFDC fields. Missing fields require enrichment, not guessing.
2. Two genuinely independent reviews agree. A second pass must not read or copy
   the first pass's conclusion. Disagreement blocks the close even if the score
   is high. Never invent agreement.
3. Valid, directly cited evidence supports every required proof claim. A
   confidence number, title match, Jira status, fixVersion, or reviewer boolean
   alone is insufficient. Reviewers must open and read the artifacts.
4. The computed confidence clears the disposition's floor. The model supplies
   evidence strength, not confidence. Invalid evidence must be reconciled before
   recommending closure; it is not silently ignored to salvage a close.
5. The recommendation covers this issue's entire reported failure. Split
   symptoms, partial fixes, incompatible release streams, and unresolved
   contradictions block a whole-ticket closure.

## Duplicate — minimum confidence 0.85

Supply cited proof of **same failure**, **same trigger**, **same required fix**,
and **canonical tracker selection**. Both compared Jira reports must be directly
cited for failure and trigger. A pair needing separate changes is related,
not duplicate. A lexical candidate score of at least 0.85 or a verified outward
Duplicate link is an additional gate, never a substitute for semantic proof.

Choose exactly one canonical tracker, normally the older established report
holding investigation, ownership, and fix tracking. Compare creation timestamps,
not issue numbers. This implementation requires a demonstrably older retrieved
target, no customer signals on that target, and a direct canonical citation.
Newer or undated canonical targets are withheld for separate human selection;
the skill does not implement an override. Never prefer a report merely because
it is the latest. An inward "is duplicated by" relationship cannot authorize
closing the canonical report.

Do not choose a canonical issue that is itself resolved/linked as a duplicate.
Follow it to the authoritative tracker and re-check the pair. For a cluster,
evaluate each redundant issue separately against that one tracker. Do not emit
conflicting recommendations that both retain and close the same tracker.

## Already fixed — minimum confidence 0.80

Supply cited proof of **matching implementation**, **released inclusion**, and
**validation** of the reported trigger/failure through regression coverage,
direct code analysis, or a real reproduction. Label source inspection honestly;
it is not a claim that a runtime test was performed.

- Name the exact merged PR or incorporated commit as a link. Closed-unmerged
  changes are not fixes. Its direct citation must match the named artifact,
  rather than an unrelated PR used to inflate confidence.
- Prove the change resolves the whole failure, not just a similar symptom or one
  phase of a composite issue. `coversWholeIssue` is a claim reviewers verify,
  not a way to bypass missing proof.
- Name a confirmed released version containing the fix, no newer than the
  release under review, with direct release/ancestry evidence.
- Also prove inclusion in the **exact release under review**. An older stream's
  fix does not establish ancestry into a newer stream merely because its version
  sorts lower. Record `reviewRelease` and `containedInReviewRelease` only after
  checking that inclusion.
- Planned versions, development package versions, source branch content, or a
  merged-but-unreleased PR do not prove a shipped fix.

Recommend closing the issue being reviewed as fixed in the named release.
This is not a recommendation to close some other issue because it is older.
No backport or PR creation follows automatically. Future new fixes normally
target the next y-stream; only separately requested critical customer cases
justify assessing a supported-stream backport through `/rhdh-backport`.

## Output contract

The following is a shape, not evidence about real tickets. Substitute real
links and specific comparisons; the renderer fills confidence from policy.

```text
Re: [Jira issue] — [Title]

Duplicate: This issue duplicates [canonical issue].

Recommendation: keep [canonical issue] as the canonical tracker and close
[issue under review] as its duplicate, subject to human approval.

Proof:
- Same failure: [concrete comparison] [links to both reports]
- Same trigger: [matching steps/configuration/code path] [links to both reports]
- Same required fix: [why one change resolves both] [evidence links]
- Canonical tracker: [why this report is authoritative] [tracker link]

Confidence: [computed score; not a probability].
```

```text
Re: [Jira issue] — [Title]

Already Fixed: The reported failure is resolved by [merged PR/commit],
included in release [version].

Recommendation: close [issue under review] as fixed in [version],
subject to human approval.

Proof:
- Matching implementation: [how the diff resolves this failure] [PR/commit]
- Released inclusion: [carrying release and target-release inclusion] [links]
- Validation: [regression coverage/source analysis/actual result] [links]

Confidence: [computed score; not a probability].
```

Never announce "Closing as". Free-form legacy `comment` and `recommendedStep`
inputs cannot override policy or replace the verified generated payload. Every
surfaced draft retains its stable `Triage reference` footer.

## Confidence and delivery are different gates

Confidence uses the strongest evidence weight (direct 1.00, strong 0.80,
supporting 0.50), plus up to 0.08 for additional strong/direct artifact references,
capped at 0.98. Different line ranges in the same artifact do not add a bonus.
Duplicate confidence is also capped by match/link support. This is an auditable
policy score, **not a calibrated probability or guarantee of factual accuracy**.
All other proof gates still apply, regardless of score.

Comment delivery is separate: the same posted recommendation is suppressed
indefinitely. Changed advice waits the configurable 14-day cooldown and direct
evidence that the latest marked request was completed or superseded. Silence,
unrelated replies, new releases, or label changes do not clear pending work.
Incomplete/unreliable history requires review; unmarked discussion also requires
human review for equivalent advice and outstanding owner actions. The planner
does not claim to understand legacy comments automatically. A suppressed draft
stays audit-only and gets no new handoff file or notification.

Before any future approved external handoff, freshly read the issue, customer
fields and complete comments, re-evaluate proof and delivery, serialize per issue,
preserve the approved reference/body, and read back the created comment ID. On
uncertain delivery, reconcile history before retrying. This skill implements
neither an external writer nor exactly-once delivery.
