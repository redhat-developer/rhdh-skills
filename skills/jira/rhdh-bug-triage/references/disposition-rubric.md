# Disposition rubric

One disposition per ticket. The label describes what the evidence proves, not
what would be convenient.

| Disposition | Meaning | Minimum evidence | Close eligible |
|---|---|---|---|
| `duplicate` | The same failure is already tracked under another key | Direct Jira citation of the target, plus a candidate score of at least 0.85 or an explicit outward Duplicate link | Yes, at confidence 0.85 |
| `already_fixed` | A merged change fixes this report and the fix is in a supported release | Direct PR or commit citation, a confirmed release, and `released: true` | Yes, at confidence 0.80 |
| `still_valid` | The behavior is still present on a supported release, or the current code path still has the defect | A direct reproduction or direct code citation | No — keep open |
| `no_longer_valid` | The feature or behavior the report targets no longer exists, or a reproduction on a supported release proves it is gone | Direct code, documentation, release-note, or reproduction citation | Yes, at confidence 0.80 |
| `needs_repro` | The report lacks the version, environment, steps, or error text needed to decide | None required; the recommended action asks for them | No |
| `unclear` | Evidence conflicts, is missing, or the passes disagree | None required | No |

## Actions

The policy maps a disposition to one action:

| Action | When |
|---|---|
| `propose_close_duplicate` | `duplicate` passed every gate |
| `propose_close_fixed` | `already_fixed` passed every gate |
| `propose_close_obsolete` | `no_longer_valid` passed every gate |
| `comment_only` | The disposition is closeable but a gate failed, or the finding is useful as a comment |
| `keep_open` | `still_valid` with cited evidence |
| `needs_repro` | `needs_repro`, or a packet with no usable evidence |
| `unclear` | No adjudication, or an unusable assessment |

A close action is a proposal only. Nothing in this skill writes to Jira.

## Close gates

Every close must pass all five:

1. **Not customer-linked.** Any customer signal disables a close permanently.
2. **Direct evidence.** At least one item with `strength: direct`.
3. **Confidence floor.** Duplicate 0.85; fixed 0.80; no-longer-valid 0.80.
4. **Two agreeing passes.** `review.independentPasses >= 2` and
   `review.agree == true`.
5. **Disposition-specific proof.**
   - duplicate: a candidate at 0.85 or an explicit outward Jira Duplicate link,
     and a direct citation of the target;
   - fixed: a direct PR or commit citation, a release, and `released: true`;
   - no-longer-valid: a direct code, documentation, reproduction, or
     release-note citation.

Jira's Duplicate link is directional. An outward link means this ticket
duplicates the target. An inward "is duplicated by" link means the other ticket
is the duplicate, so this ticket is the canonical report and must stay open.

A close that misses any gate becomes `comment_only` when confidence is at least
0.60, otherwise `needs_repro`. The verifier re-checks the packet and repeats the
downgrade, so a bug in the policy cannot leak a close.

## Confidence

Confidence is derived from the strongest citation plus a small bonus for
independent corroboration:

| Strength | Weight |
|---|---|
| `direct` | 1.00 |
| `strong` | 0.80 |
| `supporting` | 0.50 |

Each additional independent strong or direct citation adds 0.04, capped at 0.08
and at 0.98 overall. A duplicate's confidence is capped by the match evidence:
the lexical score, or 0.90 when an explicit Duplicate link exists.

The model never writes a confidence number. If an assessment includes one, the
policy ignores it.

## Strength definitions

- **direct** — the cited artifact resolves the question on its own: the duplicate
  target describes the same failure, the merged PR changes the failing code, the
  release note names the fix, or the reproduction fails on the current release.
- **strong** — the artifact makes the conclusion very likely but needs one
  inference: a related comment with the same stack trace, a PR that changes the
  same code path without a test, a release note that describes the area but not
  the exact symptom.
- **supporting** — context only: the ticket is old, a teammate recalls it being
  fixed, a component recently changed. Supporting evidence never justifies a
  close on its own.

## Customer rule

A ticket is customer-linked when any of these is true:

- it carries the `RHDH-Customer` label;
- it links to an `RHDHSUPP-*` or `ACCOUNT-*` issue;
- a customer field is populated (`Customer Name`, `Customers`, `Customer
  Impact`, `Case Link`, `Support Case Reference`, `SFDC cases`);
- the text contains an `RHDHSUPP-*` key other than the ticket's own key.

Customer-linked tickets are excluded from normal sampling. If one reaches a
packet through a control or an explicit request, it is marked close-disabled and
the recommendation never proposes a close. There is no override in this skill.

## Decision-ready and classified

- **Decision-ready** means the action is not `unclear`: a reviewer can act on the
  packet, even if the action is "ask for a reproduction".
- **Classified** means the disposition is not `unclear` or `needs_repro`: the
  evidence supports a real disposition.

Track both. The first measures whether the pass produced usable work; the second
measures how much of the sample the evidence could actually settle.

## When to abstain

Abstain when:

- the report has no reproduction steps and no current-release attempt;
- the fix is merged but not in a release, or the release is unknown;
- the only duplicate candidate is below the retrieval floor and there is no
  explicit link;
- two passes disagree about meaning rather than wording;
- the evidence points to a different failure than the one described.

An abstention with a specific request for information is more useful than a close
the team has to reverse.
