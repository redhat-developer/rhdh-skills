# Discovery and scoped fix evidence

Discovery produces **leads**, not dispositions, evidence confidence or closure
permission. Run every route even when another found an apparently strong match:

| Route | Evidence to investigate |
|---|---|
| Link graph | Direct links in both directions and duplicate chains up to three edges; retain unresolved keys, reversed pointers, creation-time conflicts and closed copies with fix evidence. Links can be wrong. |
| Burst | Reports within one hour with overlapping content; preserve both attachments. A burst is not duplicate proof. |
| Open/closed corpus | Rank the two partitions separately; some closed tickets do not establish exhaustive history. |
| Comments | Seed and graph-partner comments: pointers, fix claims, uncertainty and contradictory follow-ups. Do not expand every weak lexical neighbour's comment graph. |
| Defect searches | Separately search keys/verified aliases, specific identifiers and multiword phrases. Scoring tokens such as “each” or bare HTTP numbers are not live queries. |
| Fix-first | Closed, versioned trackers with PRs and overlapping reports/links. Merge, released inclusion and coverage remain unverified. |

`collect --corpus broad-export.json` records routes in each evidence file's
`discovery`. Add `--jira-search` for live reads; `--max-queries`, `--query-limit`
and `--hydrate-limit` bound work **per seed**. Otherwise queries are only planned.
`run` performs local routes, retains collected query provenance, incorporates
hydrated candidate records and exposes nonlexical candidates for adjudication.
It never writes assessments or assigns verdicts from discovery scores.

Query outcomes: `returned`, `empty`, `capped`, `failed`, `not_run`. Reaching the
requested row limit is conservatively capped; no exact server total is claimed.
Keep unexecuted queries, read failures and unavailable candidates. Hydration
failure does not erase a search hit. Failed/capped/unrun queries are not empty.
A full-phrase query can miss a paraphrase; manually follow alternate mechanism
and trigger terms when bounded discovery is weak or contradictory.

Retrieval routes are not independent evidence or independent review. One proved
lead can be sound; seven routes can repeat the same mistake. Do not require an
arbitrary number of retrieval passes to establish semantic identity.

Former keys come only from actual metadata/key history, not arbitrary mentioned
keys. Search aliases individually. If history is unavailable, inspect migration
history/redirects through the authenticated adapter and record the gap. Do not
manufacture an alias. Former/current identifiers denote the same tracker, not a
duplicate; packets/candidates mark same-record identity and reject its closure.

## Relationship vocabulary for investigation

These labels explain comparisons; they are not additional dispositions:

Optional assessment `comparisons` is a list of objects with candidate `key`,
`relationship`, causal/missing-fact `summary` and cited `refs`. Positive
different/related/duplicate comparisons require direct Jira evidence for both
reports; same-record claims must match actual self/alias identity. Invalid claims
are retained as rejected relationships and downgraded to insufficient evidence.
These are agent comparisons, never independent review or closure permission.

- `same_record`: two identifiers for one tracker; not a duplicate action.
- `duplicate_supported`: evidence establishes the same failure, trigger and
  required correction; canonical selection and closure are separate gates.
- `different`: positive evidence establishes distinct defects.
- `related_only`: shared area/symptom established, equivalence not established.
- `insufficient_evidence`: relationship cannot be determined; name the missing fact.

Compare acceptance requirements, configuration, environment, versions and contrary
evidence. Same file does not prove one defect; different files do not disprove it.
Do not turn “not every migration error” into “no migration error”.

## Scoped fix evidence: independent dimensions, not a numerical ladder

Optional assessment block:

```json
{
  "state": "not_established",
  "scenario": "Exact trigger, default/configured path and build",
  "covered": [],
  "unverified": ["Acceptance requirements lacking positive evidence"],
  "incorporation": {},
  "validation": {}
}
```

- `not_assessed`: coverage not investigated. Not for examined candidates with
  missing proof.
- `not_established`: investigation performed, resolution not established.
- `partial_fix_supported`: **positive evidence** demonstrates a functioning
  subset/mitigation. Each `covered` object needs `summary` and direct cited `refs`.
  A promising merged PR without coverage proof is not a partial fix.
- `verified_for_stated_scope`: positive coverage, incorporation and validation;
  both latter objects need `summary` and direct cited `refs`. No requirements
  within the declared scope may remain unverified. Historical tested-build
  confirmation is not automatically GA membership or whole-report completion.

Structural checks reject unsupported positive states; humans must still read
the artifacts. These fields never replace whole-report coverage, exact reviewed
release incorporation, customer screening or two independent closure reviews.
See the [assessment schema](report-schema.md) for production proof fields.

## Read-only repository diagnosis

Resolve repositories/release using `/rhdh-context`; inspect changes/ancestry with
`/rhdh-forge`, and use `/rhdh-plugin-bug-fix` only with its explicit `inspection-only`
branch when supported by the installed version. Never invoke its default fix
workflow as a substitute for a missing read-only capability.
Trace callers, supported paths, configuration and dependencies, not one isolated
function. Record immutable revisions and exactly which requirements they support.
Existing QE/runtime confirmation can be read without posting a retest request.
Do not build, deploy or mutate a cluster during triage.

Unchanged local code proves neither persistence nor resolution: dependencies,
configuration, deployment, data and environment may change. A changed path alone
does not prove resolution either. Opt-in filtering alone proves neither a
default-behavior fix nor the absence of other possible fixes.

Run artifacts retain evidence and query outcomes. Treat prior findings as cached
evidence, not durable truth. Recheck on release, source/artifact, dependency,
configuration, linked evidence, policy or corpus changes. There is no automatic
verdict reuse or private backlog ledger in the implementation repository.

Use [verification acquisition](verification-acquisition.md) to make actual source,
diff, ancestry and exact release-artifact metadata reads part of the runnable
workflow, not an unrecorded manual exercise. Acquisition still needs semantic
inspection; source identity is not acceptance coverage.
