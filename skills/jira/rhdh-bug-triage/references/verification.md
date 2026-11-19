# Verify dry-run, comment-first triage

Python 3.9+; the deterministic policy/report path is stdlib-only and can run
offline. Optional Jira/GitHub adapters perform reads only. Fixture scores prove
behavior of the fixtures, not the truth of a real bug conclusion.

## Automated checks

In the source checkout run `uv run pytest`, `uv run ruff check .` and
`uv run ruff format --check .`. Verify installed-skill links and regenerated
catalog routing too. A prose-only change must preserve the CLI/schema contracts,
not an exact incidental heading or sentence. The
[workflow](../workflows/triage-aged-bugs.md) owns runnable end-to-end commands;
the [schema](report-schema.md) owns fields and migration.

## Known-answer and hard-negative matrix

Test both positive and negative paths. A run producing only uncertain drafts
does not demonstrate that valid duplicate/fixed findings can pass.

Audit the exact generated comments, not only dispositions: no invented Jira
links from CVE/hash terms; no dropped evidence or source/runtime limitations;
fresh-install qualifications stay visible; limited leads retain zero proof
weight. A specific cited next-investigation question must not bypass a failed
definitive gate or become a command to post, close, fix, or backport.

| Area | Required checks |
|---|---|
| Positive duplicate | Older authoritative target, same failure/trigger/required fix, direct citations, evidence-derived confidence at least 0.85 and two real independent reviews produce the correct canonical recommendation, including a low-lexical-similarity pair. |
| Positive fixed | Matching incorporated artifact covers the whole issue, shipped carrying release and exact target ancestry, cited validation and independent agreement produce the correct fixed recommendation. |
| Hard negatives | Similar title/different trigger or fix; inward duplicate link; newer/undated/customer target; duplicate chain; conflicting cluster; partial fix; closed-unmerged or unreleased PR; older-stream fix absent from target; contradictory runtime evidence; copied review flags. |
| Current validity | Cited exact-release `persists` succeeds; cited `resolved` plus whole-scope removal supports obsolete. Open status, no PR hit, missing/wrong-release/uncited validation or non-repro without cause must not become definitive validity. |
| Selection | Age exactly 90 days; younger/missing age; all affects older; mixed older/equal/newer; missing/ambiguous/non-comparable affects; `all-open` bypasses only age/affects; customer/Done always excluded; default 12 versus `--all`; reasons retained. |
| Investigation gate | Missing directory/file, mismatched key, blank/unknown disposition and malformed inputs fail before a successful report. An honestly investigated uncertainty is supported; a template is not adjudication. |
| Requirement verification | `--require-investigation` rejects absent/not-started records, missing observations/citations, mismatched release and false completion with unknown requirements. Positive/negative checks need direct method-matching evidence. A specific blocked check is visible; a valid source diagnosis survives unrelated closure gates. |
| Read adapters | Search-to-full-view fallback, pagination/partial envelope rejection, deployment-specific customer mappings, missing fields, ADF hidden Jira/PR/support links, and exact Jira-key boundaries. |
| Collection audit | Successful zero matches versus rate limits/permission/invalid responses/cache-only reads; actual repository scope; linked-key truncation/unsearched keys; no fabricated exhaustive coverage. |
| Untrusted evidence | Instructions embedded in Jira/PR/code text cannot trigger writes, command execution, scope changes or fabricated reviewer agreement; cached context versus repo-tag conflicts require the authoritative product release source. |

Each safety gate needs a fixture that changes that gate alone. Re-verification
must catch tampered scores, claims, target, artifact, merge/whole-scope/release
flags and validation. Passing structural checks cannot authenticate remote
facts or reviewers; perform and retain the actual source inspection separately.

## Exact-comment and no-write safety

1. Every selected, investigated bug has a nonempty exact draft and one next step,
   including `unclear`/`needs_repro`. The report includes **every** draft and
   delivery status. Report, packet and any proposal file contain the same body
   and stable reference; no rejected proof reappears as a factual assertion.
2. Drafts identify the issue, bounded disposition, cited evidence, exact-release
   validation or specific unknown, ownership when known and one recommendation.
   No invented runtime result, generic reproduction ping, closure announcement,
   forced positive or assignment invented from an inference.
3. Suppressed drafts stay visible in report/packets but get no proposal file.
   Review-required drafts stay visible and restricted, even if a file exists.
   No local artifact is treated as a posted comment or approval.
4. Use synthetic complete histories with comment IDs/times. Test identical
   advice after a year, changed advice inside cooldown, pending advice after
   cooldown, unrelated replies, malformed/wrong follow-up, future timestamps,
   legacy equivalent comments and owner holds. No reminder is produced just
   because a request is old. Missing/truncated history requires review.
5. Reject nonempty output-directory reuse without changing existing contents.
   Missing assessments cannot create a success report or preserve stale proposals.
6. Assert `audit/manifest.json` has `writes: []`; CLI help exposes no `post`, apply or
   other mutation command. Mock external calls and assert only read operations.
   End-to-end agent review must also confirm no remote writer or cluster mutation
   is invoked through a composed skill.
7. Verify general diagnosis follows the owning
   [bug-verification loop](bug-verification.md) for every bug type. Verify
   `/rhdh-context`, `/rhdh-jira-api`, `/rhdh-forge` and any available inspection-only
   specialist assistance are actually used as needed, and `/prose-editing` runs
   once on the final draft batch before preview.
   Repeated prompts in one context are not independent reviewer sessions.

## Evaluation and live shadow review

Run `evaluate --packets REVIEW/audit/packets.json --truth labels.json --strict` through
`scripts/triage.py` using independently established labels. Strict failure must
cover false duplicate/fixed closure advice, wrong canonical, **false still-valid
or other definitive conclusions**, unlabelled packets and labels absent from
packets. Empty labels or a tiny labelled subset must not pass as full coverage.
Report support, precision/recall, uncertainty and both directions of coverage;
no minimum close rate is required and no score is a calibrated probability.

For a live shadow run, retain the verified release record/date, selection scope,
corpus/query limits, input hashes, read/collection errors, independent reviewer
provenance/disagreement and an exact-comment safety review. Use a fresh local
output directory outside the PR; do not commit private Jira dumps or tracking
reports. Review every selected bug, not just apparent positives. A live shadow
report measures this snapshot; it is not grounds to certify universal accuracy,
autonomous posting/closing or the future fix/PR/backport loop.

Any future writer needs separate fresh-read/customer/history checks, per-issue
serialization, exact approved-body preservation through ADF/readback and
uncertain-delivery reconciliation tests. Those behaviors are neither implemented
nor certified by this dry-run milestone.

## Discovery regression coverage

Test routes independently of conclusions: nonlexical graph retrieval, burst
hard negatives, closed-copy comment evidence, conflicting pointers, alias/self
identity, and fix-first neighbours that share only generic error words. Exercise
failed, empty, capped and unexecuted queries, successful/failed hydration and
budgets (failed reads consume budget too). A successful script exit is not a
semantic duplicate/fix adjudication.

For live development replays, freeze seeds, corpus, selection and limits; save
each collection and run in a fresh private directory. Compare route/candidate
provenance, not just closure counts. Retain baseline retrieval successes: a known
pair already ranked first is not a newly discovered duplicate. Targeted exposed
leads are regression cases, not blind discovery accuracy. Fewer leads is a
workload measure, not measured precision without labels for the remaining leads.

Verify that positive subset evidence can retain `partial_fix_supported` without
authorizing whole-issue closure, while a merged candidate with absent coverage
stays `not_established`. Scoped source/build completion does not bypass released
artifact, full acceptance or independent review gates. Repeat a final frozen run
to check stable packet content; timestamps alone do not constitute different
triage results.
