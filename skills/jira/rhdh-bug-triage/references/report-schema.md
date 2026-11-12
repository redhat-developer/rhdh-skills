# Report schema

The CLI reads one assessment per sampled ticket and writes a deterministic set of
artifacts. Paths are relative to the output directory unless stated otherwise.

## Assessment input

One JSON file per ticket, named `KEY.json`. The minimal shape:

```json
{
  "key": "RHDHBUGS-1234",
  "disposition": "duplicate",
  "duplicateOf": "RHDHBUGS-1100",
  "evidence": [
    {
      "type": "jira",
      "ref": "RHDHBUGS-1100",
      "why": "Both reports show the same release: not found error during the Helm post-install hook.",
      "strength": "direct"
    }
  ],
  "fix": {"pr": "", "commit": "", "release": "", "released": false},
  "repro": {"result": "not_run", "release": "", "notes": ""},
  "review": {"independentPasses": 2, "agree": true},
  "notes": "",
  "comment": ""
}
```

| Field | Required | Notes |
|---|---|---|
| `key` | yes | Must match the sampled ticket key |
| `disposition` | yes | `duplicate`, `already_fixed`, `still_valid`, `no_longer_valid`, `needs_repro`, `unclear` |
| `duplicateOf` | for duplicate | The target Jira key |
| `evidence` | for any non-abstention | Each item needs `type`, `ref`, `why`, and `strength` |
| `fix.pr` / `fix.commit` | for fixed | A URL or SHA; at least one |
| `fix.release` | for fixed | The release that carries the fix |
| `fix.released` | for fixed | `true` only when the release is confirmed |
| `repro.result` | for still/no-longer-valid | `fails`, `passes`, `not_run`, or a short phrase |
| `repro.release` | for still/no-longer-valid | The release the reproduction used |
| `review.independentPasses` | for a close | Integer; a close needs at least 2 |
| `review.agree` | for a close | `true` only when the passes agree |
| `notes` | optional | Reviewer context, including a recorded disagreement |
| `comment` | optional | A ready-to-post comment; otherwise the policy drafts one |

An unknown disposition, a missing key, or a malformed file aborts the run with a
non-zero exit code. Invalid evidence items are dropped and counted as gaps; they
do not abort the run.

Confidence is not an input. If a file contains one, it is ignored.

## Packets

`packets.json` is the structured result:

```json
{
  "schemaVersion": 1,
  "dryRun": true,
  "generatedAt": "2026-11-09T10:00:00+00:00",
  "currentRelease": "2.1.0",
  "packets": [
    {
      "key": "RHDHBUGS-1234",
      "summary": "...",
      "status": "Backlog",
      "disposition": "duplicate",
      "confidence": 0.94,
      "confidenceBasis": ["best evidence: direct", "Jira Duplicate link present"],
      "action": "propose_close_duplicate",
      "recommendedStep": "Close as duplicate of RHDHBUGS-1100.",
      "target": "RHDHBUGS-1100",
      "explicitDuplicateLink": true,
      "evidence": [],
      "duplicateCandidates": [],
      "gaps": [],
      "notes": "",
      "customerSignals": [],
      "currentRelease": "2.1.0",
      "review": {"independentPasses": 2, "agree": true},
      "proposedComment": "...",
      "verificationErrors": [],
      "invalidEvidence": [],
      "policyVersion": 1
    }
  ]
}
```

Every packet carries the ticket facts, the evidence table, the ranked duplicate
candidates, the gaps, the review state, and the proposed comment. A close that
the verifier rejected has `verificationErrors` populated and an action of
`comment_only`.

## Markdown report

`report.md` is for a human reviewer, not a machine. It leads with the decision
and answers the only question a reader has: what should happen to each ticket?

1. **Bottom line** — one sentence: how many can close, stay open, need a
   reproduction, or are unclear.
2. **Scope line** — sample size, controls, corpus size, release under review,
   how many are decision-ready, how many carry cited evidence, and the gap count.
3. **What each ticket needs** — a table with `Ticket | Verdict | Why | Do this
   next`. `Verdict` is plain language (`Duplicate of RHDHBUGS-1009`,
   `Still valid`, `Needs reproduction`); a closeable-looking disposition whose
   gate failed reads `Possible duplicate` or `Possibly already fixed`. `Why` is
   the first cited evidence line. `Do this next` is the recommended step.
4. **Close proposals to review** — one bullet per ticket that passed every gate,
   naming the proposed comment file. When none passed, it says so instead of
   leaving an empty section.
5. **Customer-linked** — present only when a customer-linked ticket reached a
   packet; states the close-disabled count.
6. **How this was decided** — the selection JQL, what selection excludes, whether
   the duplicate corpus contained closed tickets, the retrieval signals, the
   close thresholds, the confidence model, and the write boundary.
7. **Not in the sample** — the first ten exclusions with reasons, pointing to
   `manifest.json` for the rest.
8. **Limits** — what the report cannot claim.

If the corpus had no closed tickets, the method section says duplicate search
could not reach a closed canonical report and tells the reader to export a
broader corpus and rerun.

`proposed/KEY.md` is the long-form packet for one ticket. It repeats the dry-run
banner, the ticket table, the recommendation, the confidence basis, the evidence
table, the duplicate candidates, the gaps, and the proposed comment in a fenced
block. The comment is never posted, and every ticket gets one, including
`unclear` and `needs_repro`.

## CSV

`summary.csv` has one row per packet and these columns:

```
key,kind,controlLabel,stratum,status,disposition,confidence,action,target,
recommendedStep,evidenceCount,gapCount,customerLinked
```

`kind` is `aged` or `control`; `customerLinked` is `yes` or `no`. The CSV is for
sorting and filtering, not for pasting into Jira.

## Manifest

`manifest.json` records provenance and the write boundary:

```json
{
  "schemaVersion": 1,
  "dryRun": true,
  "policyVersion": 1,
  "inputs": {"export": "...", "sample": "...", "assessments": "..."},
  "jql": "...",
  "corpusSize": 250,
  "corpusHasClosed": true,
  "sampleSize": 12,
  "controlCount": 3,
  "thresholds": {"duplicate": 0.85, "fixed": 0.8, "obsolete": 0.8},
  "counts": {"packets": 15, "withEvidence": 12, "closeProposals": 3, "customerLinked": 0},
  "writes": [],
  "writePolicy": "read-only; proposed actions live under proposed/ and are never posted"
}
```

`writes` is always an empty list. If any future change adds a write, that field
and the dry-run banner must change together, and the change needs its own review.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | The command completed; `evaluate --strict` also requires no false closes and a decision-ready rate of at least 0.8 |
| `1` | `check` found no readable Jira session and `--allow-missing` was not set, or `evaluate --strict` hit a hard failure |
| `2` | Invalid input, missing sample key, malformed assessment, or adapter failure |
