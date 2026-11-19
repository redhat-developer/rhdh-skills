# Dry-run, comment-first bug triage

This is an **agent workflow**, not a CLI classifier. Follow the
[rubric](../references/disposition-rubric.md) for decisions and the
[schema](../references/report-schema.md) for assessment fields. Every selected
bug gets a disposition and an exact local draft. No remote writer is invoked.

Run commands from the installed skill directory, storing exports and outputs in
a private local working area outside the PR. In the examples, `$CURRENT_RELEASE`
is the actual release verified below, `$RELEASE_EVIDENCE_URL` its HTTPS release
record, and `$JQL` the explicitly chosen read query; they are placeholders, not
defaults, credentials or an automatic lifecycle lookup.

## 1. Verify release, repositories and read capability

Invoke `/rhdh-context` to verify the actual released product under review and
resolve its product, docs, plugin and dependency repositories/versions. Read the
authoritative product release record, not just the context skill's cached
compatibility matrix or a repository tag. A cached target and a newer tag may
disagree; neither alone proves which product release actually shipped. Resolve
that conflict against the official product release/lifecycle documentation and
inspect the matching repository/dependency state before selecting bugs. Planned
fixVersions, a development `package.json` and numeric ordering are not release
evidence. Record the verification source and date. The required
`--release-evidence` URL is recorded by the CLI; the CLI does not fetch it or
verify that the product shipped. If the released target cannot be established,
stop rather than guessing.

Invoke `/rhdh-jira-api` for authenticated read mechanics, field mappings and
pagination. Credentials remain inside its authenticated adapter. Do not repair
login or retrieve tokens here; missing capability goes to `/setup-rhdh-skills`.

```bash
python3 scripts/triage.py check --json
python3 scripts/triage.py fetch --jql "$JQL" --out export.json
```

`fetch` uses supported search fields followed by full issue views. If search
rejects `*all`, that is not permission to omit full views. Check descriptions,
comments, customer-field mappings and history completeness. If an adapter cannot
page a history, record that gap instead of claiming the history is complete.
An existing complete JSON export is also supported; offline work must state its
snapshot age. A successful search is not proof of complete customer-field coverage.
When `/rhdh-jira-api` returns tenant-resolved custom-field metadata, save its
credential-free ID-to-name mapping locally and append
`--field-names tenant-fields.json` to `fetch` (or `select --source acli`). Exports
retain `fieldNames` for offline consumers. Do not invent or hardcode custom-field
IDs, and do not treat the mapping as proof that every customer field was read.

## 2. Select scope and retain a broader corpus

An example candidate JQL is:

```jql
project = RHDHBUGS AND statusCategory != Done AND created <= -90d
AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))
ORDER BY created ASC
```

The parentheses/`IS EMPTY` preserve unlabelled reports. This query does not check
all customer signals or affected-version eligibility; local checks still apply.
Keep a separate `broad-export.json` with open **and closed** possible duplicates
and fixes. Do not reuse an aged/open-only query and call it a complete duplicate
corpus. Build it in one step with disjoint partition queries; every part's
query, level and gaps are recorded in the export's provenance:

```bash
python3 scripts/triage.py corpus --out broad-export.json \
  --search-jql 'project = RHDHBUGS AND statusCategory != Done AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))' \
  --search-jql 'project = RHDHBUGS AND statusCategory = Done AND fixVersion IS EMPTY AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))' \
  --full-jql 'project = RHDHBUGS AND statusCategory = Done AND fixVersion IS NOT EMPTY AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))'
```

Search-level parts are fast and rank leads across whole partitions; they lack
chronology, links, fix versions and comments, and the export says so. Add one
`--full-jql` part for closed fix-versioned trackers when the fix-first route
matters — that part costs full reads, so keep it to the partition that needs
them. Parts must be disjoint; overlapping keys are refused. Enrich full
candidate records and follow duplicate chains before choosing a target.

```bash
python3 scripts/triage.py select --input export.json \
  --current-release "$CURRENT_RELEASE" --scope aged --out sample.json
```

- Primary scope: open, non-customer, age **at least 90 days**, and every affects
  version known/comparable and strictly older than the verified current release.
  Exclude missing/ambiguous/unparseable, equal or newer versions with a reason;
  a list containing both older and current versions is not eligible.
- Default: a bounded stratified sample of 12, not 12 closure candidates.
  Add `--all` to select every eligible issue in this export.
- For explicit whole-backlog expansion, fetch a matching broader export and use
  `--scope all-open` for both `select` and `run`; add `--all` for all eligible
  records. This bypasses age/affects checks only, never customer or Done checks.
- Keep selection exclusions and coverage honest. `--all` cannot recover tickets
  absent from the export. Controls must have real known answers, not invented
  positives or a target closure rate.

## 3. Collect leads, then inspect them

```bash
python3 scripts/triage.py collect --input export.json --sample sample.json \
  --corpus broad-export.json --out fresh-evidence --gh \
  --repo owner/product-repo --repo owner/docs-repo
python3 scripts/triage.py template --sample sample.json --out assessments
```

Repository names above are placeholders; pass the actual repositories resolved
by `/rhdh-context`, repeating `--repo` for relevant product/plugin/docs repos.
Omit `--gh` for cache-only/offline collection. That does **not** search GitHub.
Keep linked-key search limits, unsearched keys, cache misses, permission errors
and rate limits; none are a successful zero-result search.

Collection also runs independent local [discovery routes](../references/discovery.md).
Add `--jira-search --max-queries 4 --query-limit 20 --hydrate-limit 10` for bounded
live defect-card queries (limits apply per issue), and `--field-names` with the
tenant map for full candidate reads. Otherwise queries are planned, not executed.
Inspect `discovery.leads`, `commentSignals`, query outcomes and unexecuted work.
Follow useful leads beyond a failed/capped budget through authenticated read tools;
never call bounded retrieval exhaustive. Discovery never assigns a disposition.
Record scoped fix progress in `fixEvidence`; missing verification is not a partial fix.

Invoke `/rhdh-forge` read-only to open actual PRs/commits, inspect diffs and
regression coverage, and verify exact target-release ancestry. Search the issue
key, linked/mentioned keys, symptoms and relevant corpus candidates. Read ADF
inline-card and link-mark URLs too. A hit is a lead, not proof; no hit is not
proof of an unfixed bug. See [evidence sources](../references/evidence-sources.md).

Then write one self-contained dossier per sampled ticket, so each investigator
works from a small fresh context instead of the whole export:

```bash
python3 scripts/triage.py dossier --input export.json --sample sample.json \
  --evidence fresh-evidence --out dossiers
```

## 4. A team of investigators, one bug each

Investigation is not optional and not serial. Spawn one fresh-context
investigator agent per sampled ticket — the host's subagent capability, or
separate sessions when the host has none. Each investigator reads exactly its
dossier (`dossiers/KEY.md`) plus the artifacts it cites, and writes one
investigated `assessments/KEY.json`. Investigators must not read each other's
conclusions; independence is what makes their reviews and disagreements
meaningful.

For **every** selected bug the investigator owns the same end-to-end
understanding a bug fixer would have, stopping before implementation:

- Read the full report and discussion, reconstruct the failure, and trace the
  executed path in the actual release sources. Use current-release code,
  runtime evidence, documentation or dependency inspection as appropriate.
  Record the method, outcome, precise release and citations in `validation`;
  otherwise state exactly what remains unknown.
- Follow [bug verification](../references/bug-verification.md) for **every bug**,
  including frontend, backend, configuration, docs, dependencies and installation.
  Record `investigation` with the actual mechanism, scoped requirement checks,
  observations, methods and citations.
- Compare the bug against its duplicate/related candidates and record
  `comparisons` with citations of both reports.
- Write a `fixPlan`: the concrete read-only remediation approach — where a fix
  would land (repository and paths), what it would change, and a complexity
  estimate. For duplicate/already-fixed/obsolete verdicts the plan describes
  the resolution action instead and uses complexity `none`. A plan is guidance
  for the separately authorized fix workflow, never a change, a claim that a
  fix exists, or closure permission.

**Escalate before recording an unknown.** An honest `unclear` is a valid
result, but it must be rare, not the resting state. Before any requirement or
disposition lands on unknown/unclear, the investigator (or a second
resolver agent given just that question and the collected evidence) attempts
the specific missing check through read-only means, including: CI and nightly
job results on the public web (for example prow builds), deeper source
tracing into vendored or built artifacts, package-registry metadata, and
release records. Only record unknown when the read-only evidence genuinely
does not exist, and name in the assessment exactly what was attempted. An
open status, stale ticket, old affects version, empty fixVersion or missing
PR match still cannot justify `still_valid`. Definitive still-valid/obsolete
findings need cited exact current-release validation; unsupported claims
downgrade to `unclear`.

An available specialist such as `/rhdh-plugin-bug-fix` may assist with explicit
**inspection-only** scope; do not invoke its default fix workflow. An unavailable
specialist is not a reason to skip general diagnosis. No product-code execution,
build/deploy, cluster mutation, fix, PR or backport is authorized here.

For duplicate/fixed recommendations, obtain two genuinely independent reviews in
fresh contexts that receive the source evidence but **not** the other review's
conclusion. The per-ticket investigator team satisfies this naturally when the
reviewer is a separate agent from the investigator; use the host's fresh-review
capability when authorized; otherwise request a separate reviewer/session and
keep the recommendation unconfirmed. Save each review's rationale, citations and
context/session provenance locally. `independentPasses: 2` and `agree: true` only
summarize work actually done; copied booleans or a second pass in the same
context are not independent review. Save disagreement and keep it uncertain; do
not erase it during reconciliation.

## 5. Apply policy locally, then preview exact drafts

```bash
python3 scripts/triage.py run --input export.json --sample sample.json \
  --assessments assessments --corpus broad-export.json --evidence fresh-evidence \
  --out fresh-review --current-release "$CURRENT_RELEASE" \
  --release-evidence "$RELEASE_EVIDENCE_URL" --require-investigation --require-fix-plan
```

For source/provenance acquisition, first author an explicit per-issue read plan
using the [verification-acquisition contract](../references/verification-acquisition.md).
Run `python3 scripts/triage.py verify --plan verification-plan.json --out fresh-verification`,
inspect the returned exact source, actual diffs, ancestry and artifact metadata,
then add `--verification fresh-verification` to `run`. This command makes network
reads; it is not an offline classifier. It does not run product code/tests or
declare acceptance covered. The run validates receipt hashes and release identity
before attaching evidence; missing/failed provenance remains visible.

Add `--scope all-open` only when that was the explicit selection scope. Use a
fresh output directory: a nonempty one is refused without retaining stale drafts.
Missing assessment files, untouched/unknown dispositions or invalid input block
the run; do not manufacture an "unclear" assessment just to obtain exit code 0.
An investigated inconclusive finding is a useful draft, not silent abstention.
`--require-investigation` rejects absent/untouched or structurally invalid
requirement checks. `--require-fix-plan` rejects assessments without concrete
read-only fix guidance, so every investigated bug leaves the run with a named
remediation approach. `blocked` is allowed only with an unknown requirement and a
specific missing check, and remains visibly blocked, not a completed diagnosis.
Structural acceptance cannot establish whether the source analysis is correct.

The agent, as final composer, invokes `/prose-editing` **exactly once for the
batch of exact Jira drafts**, in the flavored register, before reviewer preview.
Use a no-change audit to preserve the generated bodies and delivery checks. If
the pass finds a defect, correct the source summaries and rerun policy in a new
directory; do not hand-edit a body into something the policy did not verify.
Unresolved prose or evidence defects block completion. Do not run a prose pass
per transport call or invoke a remote writer after the pass.

Review `report.md`: **all** exact comments, dispositions, validation/unknowns,
known owner/team, next step, fix plans and delivery reasons. `suppress` and
`review_required` are preview statuses, not missing findings or permission to
post. `proposed/KEY.md` exists only for non-suppressed drafts; a
`review_required` file remains restricted. The audit retains evidence, rejected
claims, disagreement, selection exclusions, input hashes, search failures,
corpus limits and `writes: []`. Local drafts are not Jira posting history.

**One run directory, one file to read.** Keep the whole triage pass inside a
single private run directory with this shape:

```text
<run>/
  report.md            ← the only file a human reads
  proposed/            ← per-ticket comment drafts (written by run)
  dossiers/            ← per-ticket investigator files
  assessments/         ← one investigated KEY.json per selected bug
  fresh-evidence/      ← collected forge/discovery evidence
  fresh-verification/  ← receipt-hashed source reads
  export.json, broad-export.json, tenant-fields.json, sample.json
  fresh-review/        ← run output: report.md + proposed/ + audit/
```

`run` writes `report.md` and `proposed/` at its output root and every machine
artifact (packets, manifest, summary, sample copy) under `audit/`, so nothing
else competes for attention. Intermediates stay where earlier commands wrote
them; superseded run attempts get a new `fresh-review-N` directory rather than
overwriting. Keep local reports and private Jira exports outside the PR.

## 6. Finish the dry run, not an external handoff

Return the report path, selected/disposition/delivery counts and material gaps.
State that nothing was posted, no bugs were closed, and no fixes, PRs or
backports were created. Zero closure recommendations is valid; zero investigated
drafts for a nonempty sample is not. Never invoke `/rhdh-jira-update`,
`/rhdh-jira-link` or another remote writer during this run, even if the user likes
the preview. Posting/closing would be a separate, explicitly scoped workflow
under `/mutation-gate`, not a hidden next command here.

## Evaluate with real labels

```bash
python3 scripts/triage.py evaluate --packets fresh-review/audit/packets.json \
  --truth labels.json --strict
```

Use independently established known answers and the
[verification criteria](../references/verification.md). Report label gaps and
false still-valid findings as well as false closure recommendations. A live
shadow report or fixture pass does not certify universal accuracy, autonomous
posting, closing or the future fix/backport loop.
