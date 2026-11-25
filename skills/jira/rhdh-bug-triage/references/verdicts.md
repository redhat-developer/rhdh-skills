# The six verdicts and the comment each one produces

Every picked bug gets one verdict and one exact draft comment. When the
rules for a firm verdict are not met, the answer is `unclear` — stated
plainly, never papered over with a guess or a silent empty comment.

| Verdict | What it requires | Suggested next step |
|---|---|---|
| `duplicate` | All the duplicate rules below; one tracker to keep | A human reviews keeping the original and closing this one |
| `already_fixed` | All the fixed rules below; the fix shipped in the release under review | A human reviews the cited fix |
| `still_valid` | Cited proof the bug still happens in the release under review (`persists`) | Keep open; hand the finding to the known owner |
| `no_longer_valid` | Cited proof it is gone (`resolved`) plus a reason the whole reported problem left the product | A human reviews the conclusion; no automatic close |
| `needs_repro` | A specific missing check and a concrete plan to run it — no claimed result | Run that one check in a separately approved environment |
| `unclear` | The specific evidence that is missing or conflicting | Resolve the one gap the investigation names |

To say firmly that a bug still exists or is gone, `validation.release` must
be exactly the release under review, and its method must be `code`,
`runtime`, `documentation` or `dependency`, with links that actually prove
the claim. For `no_longer_valid` you also need `proof.scopeRemoval`: why the
whole reported problem is out of scope now. Age, silence, or one failed
reproduction nobody understood proves nothing.

An open ticket, a search that found no fix, an old version number or an
unchanged bug never establishes `still_valid`. "We found no fix in these
searches" must stay qualified — it is not "not fixed".

## `unclear` is a last resort

Before any verdict lands on `unclear`, the investigator (or a second agent
given just that question) tries the missing check read-only: nightly test
results on the public web, deeper digging into vendored or built code,
package registries, release records. Only when that evidence genuinely does
not exist may the verdict stay `unclear`, and the draft says what was tried.
This changes how hard we look — never what counts as proof.

## Duplicate — needs evidence score at least 0.85

- Looking similar only finds and ranks candidates; it is never enough. A
  low-similarity pair can qualify with complete proof and real independent
  agreement. A "Duplicate" link in Jira is a lead, never the proof itself —
  and a link pointing *into* this bug never authorizes closing the bug it
  points from.
- Cite `proof.sameFailure`, `proof.sameTrigger`, `proof.sameFix` and
  `proof.canonical`. The first two cite **both** tickets. Explain why one
  change would fix both; if they need separate fixes, they are related, not
  duplicates.
- Exactly one fully-read target that is clearly older, chosen by creation
  dates, not issue numbers. A newer, undated or customer-linked target needs
  a human to pick it and cannot pass this gate.
- Follow duplicate chains to the real original. A target that is itself a
  duplicate is not the one to keep. Never recommend keeping and closing the
  same tracker.

## Already fixed — needs evidence score at least 0.80

Cite `proof.fixMatches`, `proof.releaseContains` and `proof.validation`:

- Name the exact merged PR or incorporated commit and read what it actually
  changed. A closed-but-unmerged PR is not a fix.
- Explain why it resolves the **whole** reported problem. A similar symptom,
  a partial change or a test for a different path is not enough.
- Prove the fix shipped in the **release under review** (or an earlier one):
  a specific tag or commit ancestry, not number ordering, planned versions
  or development branches. A fix that landed after, or only in another
  stream, stays a qualified lead.
- Cite the regression test, the code analysis or the real behaviour that
  covers the reported trigger. Reading code is not running it — say which
  one you did.

`merged`, `released`, `coversWholeIssue` and `containedInReviewRelease` are
claims the tool checks for shape, not truth. Missing or conflicting proof
means `unclear` — including when a likely fix is merged but not shown to be
in the reviewed release. No fix, PR or backport follows from this verdict.

## Independent review and the evidence score

Duplicate and fixed verdicts need two genuinely independent reviews that
agree: fresh contexts, each seeing the evidence but not the other's
conclusion. Save each review's reasoning, citations and where it ran.
Disagreement blocks the firm verdict even above the score threshold.

The tool computes the evidence score from your citations — their strength
and variety. You never supply a number. No score overrides missing proof,
missing release checks or missing review.

## The exact comment shape

Keep drafts short and specific. This is the shape, not real evidence:

```text
Re: [KEY — title]
Verdict: [the conclusion, and its limits]
Evidence: [short causal comparison with links]
Validation: [exact release; method; what was observed — or what is unknown]
Owner: [assignee/team if known; never invented]
Recommended next step: [one evidence-backed step]
rhdh-agentic-bug-triager · AI-generated. Check for accuracy.
`v1:<stable fingerprint>`
```

Duplicate and fixed drafts keep their named proof and the evidence score
with its "not a probability" note. Unknowns must say what was not
established. Never write "Closing as", invent a runtime result, present
rejected proof as fact, or send generic "please reproduce" nudges, stale
ticket pings or reminders. The `comment` and `recommendedStep` fields are
legacy inputs; they cannot override the generated text. The workflow's one
prose pass must not change verified meaning.

Every investigated bug also carries a fix plan (see the
[assessment fields](report-schema.md)): what a fix would change, where, and
how big. It is rendered in the report next to the draft, not inside the
Jira comment. A plan is guidance for separately approved fix work — never a
change or permission to close.

## Whether a comment may be posted is separate from the verdict

`commentPlan.status` is `propose`, `suppress` or `review_required`; none of
them is a receipt or authorization. Every exact draft stays visible in
`01-triage/comments/` and `01-triage/audit/packets.json`, including
suppressed and on-hold ones.

Identical advice that was already given is suppressed indefinitely. Changed
advice needs the cooldown (default 14 days) **and** cited proof that the
earlier request was completed or superseded. Silence or time passing clears
nothing. Missing or truncated comment history means a human checks first —
the tool does not pretend to understand old comments. Local runs are not
posting history.

No writer is ever called in this dry run. Any future write is separate,
explicitly approved work under `/mutation-gate`, with fresh reads of the
issue, its customer fields and its history. Those paths are not implemented
or certified here.
