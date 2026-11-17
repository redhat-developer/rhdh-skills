# Evidence collection and validation

A source supports only the claim another reviewer can actually verify from it.
Collect cheap leads first, then open the decisive artifacts. The agent owns that
inspection; flags and the offline policy checker cannot establish external truth.

## Jira report and corpus

Invoke `/rhdh-jira-api` for field IDs, authenticated reads, search/view support
and pagination. Supported search fields followed by full issue views are the
fallback when `*all` search is unavailable. Exports may be REST issue envelopes,
bare issue lists or flattened records. Missing fields remain unknown, not empty.
Partial issue-list exports must not masquerade as complete results.

Read summary, description, full discussion, creation date, resolution/status,
affects/fix versions, assignee/team/components and link direction. Inspect ADF
inline cards and link marks, not just visible text: they can hide the only Jira,
PR or support reference. Complete comments require actual pagination or verified
totals; flattened `commentsComplete: true` is an adapter attestation, not a guess.

Customer checks include `RHDH-Customer`, RHDHSUPP/ACCOUNT links or text references,
and populated customer, case, impact or SFDC fields. Resolve deployment-specific
field names through the read adapter. A short familiar field list or absence of
a label is not proof of complete coverage. Record mappings, fields actually read
and any uncertainty. Never omit customer/Done exclusions in `all-open` scope.
The read CLI accepts adapter-resolved mapping JSON via `--field-names` on `fetch`
and live `select`; exported `fieldNames` retain that metadata. Never substitute
invented tenant IDs or infer completeness from the mapping alone.

Use a separate corpus of open **and closed** related reports. A canonical may
already be closed. Retrieve full candidates, verify chronology and follow
duplicate chains. Record query, retrieval date, counts and missing fields; do not
call the selected sample or an open-only export a complete duplicate search.
Lexical similarity ranks retrieval leads only; it is not the 0.85 confidence
threshold or an eligibility gate. Inspect low-similarity linked/semantic candidates
too. An explicit Duplicate link never replaces same-failure/trigger/fix proof.

## Forge leads and incorporated fixes

Invoke `/rhdh-forge` read-only to inspect product, docs, plugin and dependency
repositories resolved by `/rhdh-context`. Search issue keys, linked/mentioned keys,
failure signatures and code paths; fixes may land under another issue's key.
Inspect linked PRs even if key search returns nothing. Record which query found
each artifact, actual merge state/date/commit, base branch, matching diff and tests.
A closed-unmerged PR is not a fix, and a merged main-branch change is not a release.

`collect --gh` permits read-only `gh` searches/views. `--repo owner/repo` is
repeatable; include relevant repositories rather than assuming a single product
repo covers every plugin/doc issue. Without `--gh`, collection is cache-only.
Preserve per-query failures, rate limits, permission errors, cache misses and
`unsearchedLinkedKeys` separately from successful zero matches. The bounded
collector searches at most five linked keys; investigate omitted leads when
material. Neither an empty result nor an incomplete search proves no fix exists.

## Actual release and exact ancestry

Invoke `/rhdh-context` to resolve the actual released product, its release source,
repository tags and stream context. Its cached compatibility matrix is a lead,
not an authoritative current-release lookup. If it conflicts with a newer repo
tag, resolve the actual shipped release against official product release/lifecycle
documentation; a tag alone does not prove product shipment. Inspect the matching
product docs and repository/dependency state. Read the authoritative HTTPS
release record before setting `--current-release` and `--release-evidence`.
Record verification date/source; the CLI only records the supplied URL and cannot
magically verify its contents. Do not hardcode a "current" product release in an
assessment or command default.

For an already-fixed claim, identify the carrying release and prove the exact
reviewed release contains the matching change, using a specific tag/commit
ancestry or equivalent release artifact and its dependency mapping. A lower
version number does not establish ancestry across streams. Planned versions,
development package versions, a merged but unreleased PR and fixVersions alone
are insufficient. A later/other-stream fix stays a qualified lead, not a close
recommendation. This workflow does not propose or create backports.

## Current-release validity

Choose an appropriate `validation.method` and bind its citations to the exact
reviewed release, not to moving `main` or an old ticket snapshot:

| Method | Useful evidence | Limit |
|---|---|---|
| `code` | Tagged code path, symbol/lines, conditions causing or removing this failure | Unchanged-looking code alone may miss changed configuration/dependencies |
| `runtime` | Actual result with exact product/platform/install versions, steps and error/output | A reproduction plan is not a result; one non-repro without cause is not resolution |
| `documentation` | Version-specific product contract/configuration proving the behavior remains required or is removed | A search miss or generic latest page is not current-release validation |
| `dependency` | Released product's pinned dependency and its relevant implementation/compatibility change | An upstream fix alone does not prove the product incorporates it |

Use `/rhdh-plugin-bug-fix` in read-only diagnosis/reproduction-planning mode for
the relevant path and exact check. Do not follow its implementation/PR path or
run builds, deploys or cluster mutations. Inspect existing runtime artifacts
honestly, naming who ran them when known; never claim a run not performed.
If the required environment/evidence is unavailable, specify the missing check
and return `unclear`/`needs_repro` with no generic request or invented result.

Definitive `still_valid` needs cited `persists` validation. Definitive
`no_longer_valid` needs cited `resolved` validation and the whole-issue
scope-removal reason. Open status, age, silence, old affects versions, empty
fixVersions and no PR match support neither conclusion. Distinguish "not found
in the searched corpus" from "does not exist". See the
[rubric](disposition-rubric.md) for decision gates.

## Citation quality and conflicts

Each evidence item has `type`, `ref`, `why` and `strength`, as defined in the
[schema](report-schema.md). References are real HTTPS URLs or Jira keys; bare
SHAs and local pseudo-links cannot carry definitive proof. Cite immutable
release-specific file/commit URLs where available, and explain the inference
in `why`. A link count is not causal validation.

Retain invalid citations, source limitations and contradictions in the audit.
Prefer evidence specific to the actual reported trigger and exact reviewed
release over older commentary; inspect the diff over relying on a PR title.
Multiple copied assertions are not independent corroboration. If a conflict
cannot be resolved, preserve it and draft the uncertainty instead of selectively
discarding evidence to obtain a positive conclusion.
