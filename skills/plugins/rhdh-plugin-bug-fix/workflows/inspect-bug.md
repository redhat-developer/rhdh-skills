# Inspection-only plugin investigation

This branch runs only when the caller explicitly selects `inspection-only`.
It does not inherit authorization for the reproduction/fix workflow. Do not
install dependencies, create a temporary test, start the application, build,
deploy, edit product code, mutate a cluster or write to a forge/Jira issue.
Do not transition to `fix-bug.md` without a separate user request.

## Inputs and ownership

The caller supplies the report/acceptance requirements and reviewed release
context, plus any existing source/artifact receipts or reproduction evidence.
Missing evidence remains missing, not an invitation to run a product test.

- Resolve report/workspace context through `/rhdh-forge` or `/rhdh-jira-api` by
  name, as appropriate; do not call GitHub/Jira directly or read their internals.
- Confirm the candidate workspace against the provided checkout or immutable
  source evidence. If unresolved, return the ambiguity; do not guess a workspace.
- The caller owns product lifecycle and closure policy. Inspect its supplied
  provenance without substituting a repository tag for an unproved product build.
- If competing causes cannot be distinguished from existing evidence, return
  them as hypotheses. Do not enter a design/implementation branch to force a result.

## Inspection

Read the reported trigger and each acceptance requirement. Follow the owning
implementation, relevant callers, supported configuration and pinned dependencies
at the exact supplied revision. Inspect candidate corrective diffs and final
source, not only change titles or a shared filename. Inspect existing regression
tests and recorded reproduction results; distinguish assertions from executed
results and name their original executor when known.

For every requirement, state what source/test evidence supports it, what conflicts,
and what remains unestablished. A passing neighbouring test or an unexecuted test
body is not proof for an uncovered requirement. Unchanged code alone is not
persistence evidence because deployment, configuration and dependencies may differ.

## Return to the caller

Return in the conversation:

- Confirmed repository/workspace and exact inspected revision, with source refs.
- Trigger and requirement-by-requirement inspection findings.
- Candidate mechanisms/corrective changes, with positive and contrary evidence.
- Existing validation: what actually ran, where, when and on which build; otherwise
  explicitly state **not run during this investigation**.
- Source-versus-product-artifact binding and the exact remaining provenance gap.
- Smallest discriminating next check if evidence is insufficient. Describe it;
  do not execute it or create a generic retest request.

Do not declare a bug fixed just because code changed, declare it persistent just
because code did not change, or promote incomplete verification to a partial fix.
The caller decides the triage disposition and any independent-review requirement.
