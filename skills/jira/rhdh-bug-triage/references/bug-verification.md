# Verify a bug as a bug fixer would

Triage owns this investigation for every bug type. Searching issue keys and
checking PR status is discovery, not verification. A frontend or installation
bug does not need to be called a plugin bug to receive source-level diagnosis.

## Investigation loop

1. **Reconstruct the failure.** Read the full report, discussion and available
   attachments. State the actual environment, trigger, expected/actual behavior
   and every acceptance requirement. Preserve disagreements and distinguish
   the original defect from later requests or adjacent failures.
2. **Find the executed path.** Resolve the route/handler, permission guard,
   component and layout, backend/dependency, deployment/configuration or
   published-document cross-reference. Trace calls and conditions, not just
   matching names. Resolve the exact reviewed version; a default-branch search
   hit is a lead until its applicable source/package/release is established.
3. **Understand the mechanism.** Explain causally how the reported inputs reach
   the failure. If the environment or attachment is missing, inspect what can
   be established and name that specific remaining gap. Do not request a new
   reproduction merely because no linked PR was found.
4. **Inspect correction candidates.** Read actual diffs, final target source,
   relevant configuration and dependencies, regression-test bodies and
   contradictory paths. A merged PR is insufficient; an unmerged one cannot
   establish incorporation. A workaround or clearer error message is not the
   original behavior being repaired. No candidate is required to establish a
   positive counterexample in the exact reviewed code.
5. **Check each requirement.** Record `satisfied`, `violated` or `unknown`, with
   the actual observation, method and direct evidence. Code may settle an
   explicit sequential loop; a source file alone generally cannot settle a
   visual layout, intermittent service failure or memory bound. Read relevant
   tests, but do not represent reading them as executing them. For published
   docs, inspect the exact link and destination content, not HTTP status alone.
6. **Separate the conclusions.** State what works or remains broken in the
   inspected scope. Separately record whether this is the exact distributed
   artifact and whether closure/history/customer/reviewer gates passed. Missing
   closure approval must not erase a supported source diagnosis. Conversely,
   source inspection is not proof of downstream artifact bytes or runtime.

## Read-only execution boundary

Read source, diffs, package/registry data and existing test/CI/runtime results as
data. Do not install dependencies, run product code/tests, build, deploy, change
cluster state, unlock databases or create fixes/PRs/backports during this dry
run. If behavior cannot be established from these reads, specify the minimum
reproduction with inputs, permissions, environment and pass/fail observations
for a separately authorized environment. A planned experiment is not a result.

## Completion and regression traps

An investigation is `completed` only for its explicitly stated scope with no
unknown requirement. It is `blocked` when a requirement remains unknown, with
the exact missing check in `blocker`. Do not narrow the scope to conceal an
unverified original requirement. A violated requirement can establish that a
complete fix is absent even while other checks remain blocked; it does not
establish all runtime consequences. The schema records these checks separately
from advisory disposition and delivery.

Keep these corrections in future investigations: a configuration switch does
not prove response/error propagation; opt-in caching does not prove safe default
memory behavior; retaining an explicit loop is not parallel processing; and a
working replacement documentation link can resolve the reported click-through
even when the unused old URL still returns 404. Whole-fix closure still needs
the rubric's incorporation, release and independent-review evidence.
