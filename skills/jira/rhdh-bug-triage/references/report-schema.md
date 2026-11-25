# What an investigator fills in, and what comes out

## One file per bug

`template` creates `assessments/KEY.json`; the investigator fills it in. The
filename, the `key` and the picked bug must agree. Valid `verdict`:
`duplicate`, `already_fixed`, `still_valid`, `no_longer_valid`,
`needs_repro`, `unclear`. Unknown fields create no new powers.

Missing assessments, unfilled or unknown verdicts and malformed input stop
the run — they do not produce a quiet "unclear". An investigated `unclear`
is supported. Output directories must be empty, so stale drafts cannot
survive a rerun.

## Evidence

Each item needs all four parts:

```json
{
  "type": "code",
  "ref": "https://github.com/example/product/blob/VERIFIED_TAG/path/to/source.ts",
  "why": "One sentence: what this exact released file proves about the reported problem.",
  "strength": "direct"
}
```

Types: `jira`, `pr`, `commit`, `release_note`, `code`, `doc`, `repro`,
`comment`, `ci` (a CI or nightly job result, for example a prow build
page). Strengths: `direct`, `strong`, `supporting`, `limited`. `limited`
keeps a lead or an access limitation on record with zero proof weight — it
can never satisfy a rule that needs direct evidence. Invalid citations are
kept in `invalidEvidence` and block firm verdicts. Never upgrade something
you did not read to proof. Ignore the input confidence if one is present;
the tool computes its own score.

## The checks (`investigation`)

Required by `run --require-investigation`. Fill in `status` (`completed` or
`blocked`), the exact numeric `release`, a plain `scope` (what you actually
looked at), the causal `mechanism` (what goes wrong and why), and the
`requirements` — one per promise the bug makes. Each requirement has:

- `statement` — the promise, in your words;
- `observed` — what you saw;
- `result` — `satisfied`, `violated` or `unknown`;
- `method` — `code`, `runtime`, `documentation`, `dependency`, `artifact`
  or `report`;
- `refs` — links from your evidence list that prove it.

A passed or failed requirement needs direct evidence matching its method;
`report` is only for an unknown behavioural result, never proof. A finished
investigation has no unknown requirements. A blocked one needs exactly one
unknown and a `blocker` naming the missing check. These structural checks
prove the work was done, not that it was done right — a human still reads
the citations.

## Does it still happen? (`validation`)

```json
"validation": {
  "release": "VERIFIED_RELEASE",
  "method": "code",
  "result": "persists",
  "summary": "Why the reported steps still reach the broken code in this release.",
  "refs": ["https://github.com/example/product/blob/VERIFIED_TAG/path/to/source.ts"]
}
```

- `release`: the exact version you verified, matching `--current-release`.
  Never leave the placeholder in.
- `method`: `code`, `runtime`, `documentation` or `dependency`.
- `result`: `persists`, `resolved` or `unknown`.
- `refs`: cited evidence of the matching kind — code uses `code`/`pr`/
  `commit`; runtime uses `repro`; documentation uses `doc`/`release_note`;
  dependency inspection uses the relevant released record. All must be
  `direct`.

`still_valid` needs a cited `persists`. `no_longer_valid` needs a cited
`resolved` **plus** `proof.scopeRemoval`. Anything less downgrades to
`unclear`, and the draft says the limit. A result that contradicts the
verdict stays visible; it is never ignored to save a conclusion.

## Firm proof (`proof`)

Maps claim names to `{summary, refs}` — plain reasoning plus direct links
from the evidence list:

| Verdict | Claims |
|---|---|
| `duplicate` | `sameFailure`, `sameTrigger`, `sameFix`, `canonical` (the first two cite both tickets) |
| `already_fixed` | `fixMatches`, `releaseContains`, `validation` |
| `no_longer_valid` | `scopeRemoval` |

An already-fixed assessment also fills in `fix`:

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

Supply `pr` or `commit` (both if you have both). The booleans must be JSON
`true` and assert facts you actually verified — the tool checks their shape,
not their truth. The carrying release must be the same age as or older than
the one under review.

`review: {"independentPasses": 2, "agree": true}` summarizes two real,
agreeing, independent reviews (duplicate and fixed verdicts only). Save
their reasoning and say in `notes` where they ran. Disagreement: `agree:
false`, and the verdict stays uncertain — never manufacture agreement.

An uncertain assessment may add `nextCheck`: a `method`, one bounded
`question` ending in `?` (up to 400 characters), and `refs`. It renders as
a question for a human, never a command or a close action.

## The fix plan (`fixPlan`) — every bug gets one

```json
"fixPlan": {
  "approach": "Accept the notebook file-type set in the chat upload validator and share the error copy.",
  "areas": [{"repository": "owner/repo", "paths": ["plugins/chat/src/utils/attachment-utils.ts"]}],
  "complexity": "small",
  "refs": ["https://github.com/example/product/blob/abc123/handler.ts"]
}
```

- `approach`: what a fix would change and why that resolves the reported
  problem. For `duplicate`, `already_fixed` and `no_longer_valid`, describe
  the resolution action instead.
- `areas`: where the fix would land. Omit when no product area applies.
- `complexity`: `trivial`, `small`, `moderate`, `large`, or `none`
  (resolution-only verdicts).
- `refs`: evidence the assessment already cites, backing the approach.

Required by `run --require-fix-plan`. Rendered in the report next to the
draft. Guidance for separately approved fix work — never a change, proof of
a fix, or permission to close.

## Optional: how much of a fix is proven (`fixEvidence`)

Records scoped progress separately from close recommendations. States:
`not_assessed`, `not_established`, `partial_fix_supported` (positive
evidence of a working subset), `verified_for_stated_scope`. The positive
states need directly-cited claims; a promising merged PR without coverage
proof is not a partial fix. See [discovery](discovery.md). Existing inputs
without this block keep the full proof rules above.

## Delivery metadata (`commentPlan`)

Generated, not filled in: `status` (`propose`, `suppress`,
`review_required`), `reason`, a stable `reference`, `cooldownDays`, and
prior-comment data when relevant. Where changed advice follows an earlier
marked request, `followUp` names the prior comment, its completed or
superseded state, and cited proof. Complete Jira comments — not `updated`
timestamps or local folders — are the posting history. Known but unread
customer fields block closure advice; the comment stays `review_required`.

## What a run writes

Two phases under the run root:

- `01-triage/START-HERE.md` — the decision page: metrics, one row per bug,
  the reading order, and the limits.
- `01-triage/comments/KEY.md` — one exact draft per bug, with its posting
  status above a separator. On-hold and suppressed drafts included.
- `01-triage/audit/` — `METHOD.md`, `RUN.md`, `release.md`, `selection.json`,
  `manifest.json`, `packets.json`, `assessments/KEY.json` and
  `bugs/KEY.md` (proof, validation, fix plan, owner, next step, limits).
- `02-fixes/` — `README.md`, `INTAKE.md`, `AUDIT.md`, and one case per bug
  under `pull-requests/`, `docs/`, `new-bugs/`, `resolution/` or `blocked/`.
  Each triage case contains CASE.md and PLAN.md. A subsequent fix request produces PROPOSAL.md, change.patch, VERIFY.md and a receipt, with separate patch and verification files for each proposed backport.

`packets.json` carries the findings for the system plus a `meta` block:
release and its evidence link, input paths and SHA-256 hashes, module
hashes, thresholds, counts, delivery policy, collection coverage and
`writes: []`.

## Optional handoff

An assessment may name its primary fix outcome:

```json
"handoff": {
  "outcome": "pull_request",
  "reason": "The fix needs a code change in the product repository."
}
```

Valid outcomes are `pull_request`, `docs`, `new_bug`, `resolution` and
`blocked`. Without it, the tool infers: duplicate/already-fixed/no-longer-valid
and complexity `none` route to `resolution`; `unclear` or a blocked
investigation routes to `blocked`; all-documentation areas route to `docs`;
everything else routes to `pull-requests`. One primary outcome per bug; a
secondary action belongs in `CASE.md`.

Keep private exports and live reports out of the PR. `--evidence` attaches
the collection results and their failures; without it, do not call the
GitHub search complete. The tool records evidence; it never certifies the
release link, the field coverage, the reviewers or the facts.

## Scoring (`evaluate`)

`labels.json` maps keys to `{"verdict": "...", "duplicateOf": "..."}` (the
kept tracker is required for a duplicate label). Use answers established
independently of this run. Strict mode fails on missing coverage, wrong
firm conclusions (including wrong `still_valid`) or wrong close
recommendations. See [verification](verification.md).
