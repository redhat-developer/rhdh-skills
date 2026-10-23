# Workflow: Track PRs Through the Merge Pipeline

Keep a local list of overlay PRs and refresh where each one sits between opening and merging.
A code-clean PR is not a mergeable PR: it still needs the trusted-user gate, a publish for its
current head, smoke tests, and an e2e run. This workflow answers "where are these PRs now, and what
does each one need next" in one pass.

Read `references/ci-feedback.md` for the publish comment formats.

## The ledger

The ledger is a JSON file outside the repository, keyed by PR number, holding each PR's last known
stage and a short stage history. It lives at `$XDG_STATE_HOME/rhdh-overlay/pipeline.json`, falling
back to `~/.local/state/rhdh-overlay/pipeline.json`. Nothing is written into the checkout.

The ledger is what makes a repeated invocation cheap and comparable: the report names what changed
since the previous check instead of dumping the same table twice.

```bash
python scripts/pr-pipeline.py add 4440 4441 4442    # start tracking
python scripts/pr-pipeline.py status                 # refresh from GitHub and report
python scripts/pr-pipeline.py status --json          # same, machine-readable
python scripts/pr-pipeline.py status --no-write      # look without touching the ledger
python scripts/pr-pipeline.py list                   # what is tracked, no network
python scripts/pr-pipeline.py hold 4440 --reason "waiting on a named reviewer"
python scripts/pr-pipeline.py release 4440           # clear a hold
python scripts/pr-pipeline.py remove 4440            # stop tracking
```

`--repo`, `--ledger`, `--no-write` and `--json` are accepted before or after the command name.

**Hold deliberately.** A PR parked for a reason the pipeline cannot see — a human asked for a
specific reviewer, the fix already shipped on a release branch, a decision is pending — belongs in
the ledger as a hold with its reason. Otherwise it sits in the command plan forever, and the plan
stops being trustworthy at a glance.

## Stages

The stage is the most actionable fact about a PR, not its earliest unmet gate. A PR with failing e2e
evidence reports `e2e-failed` even when its publish predates the head, because the failure needs a
decision first. Everything non-actionable lands in the report's notes column.

| Stage | Meaning | Signal | Next |
|---|---|---|---|
| `diagnosed` | a CI diagnosis traced the failures to this PR | a `fullsend-ai-review` review saying `PR-regression` that postdates the head | `/fs-fix` against that diagnosis comment |
| `code` | review findings open | `fullsend-ai-review` requested changes, no fix run since | `/fs-fix` |
| `fixing` | the fix agent is working | a `Fix · Started` comment with no outcome after it | wait |
| `fix-failed` | two fix runs in a row produced no commit | two unsuccessful outcomes with different run ids, newest after the head | none — a human decides why |
| `sonar` | the quality gate failed for this head and has not been attempted | the last `sonarqubecloud` comment says `Quality Gate failed`, postdates the head, and no fix run started after it | `/fs-fix` against that comment |
| `gate` | waiting for a trusted user | no `/ok-to-test` from a member, owner, or collaborator | `/ok-to-test` |
| `publish` | no images for this head | no successful publish dated at or after the head commit | `/publish` |
| `publishing` | publish running | `publish` check pending, queued, or in progress | wait |
| `publish-failed` | publish failed for this head | failed publish report newer than the head | `/fs-diagnose` |
| `smoke` | images out, load check pending | publish succeeded, no smoke result for this head | wait |
| `smoke-failed` | smoke failed | failed smoke report newer than the head | `/fs-diagnose` |
| `e2e` | smoke green, tests pending | no e2e result for this head | wait |
| `e2e-failed` | tests failed | last e2e result for this head is not a pass | `/fs-diagnose`, or re-run or none when a diagnosis already covers the run |
| `blocked` | tests green, merge refused | merge state blocked by a required check or approval | wait |
| `mergeable` | every gate green | pass for this head, merge state not blocked | merge |
| `superseded` | nothing left to merge | the PR carries no changed files — a fix reverted it back to `main` | close it |
| `held` | parked on purpose | the ledger says so | none |

## Invariants

1. **A repeated request is a stall, not progress.** Two fix runs in a row that produced no commit for
   the same head is a pattern, not bad luck: the third request buys the same failure. The stage becomes
   `fix-failed` with no command, the note links the failing comment, and a human reads the reason. One
   failure inside a PR's history is still a retry — agent runs die for transient reasons, and a run can
   report twice for the same workflow link, so outcomes are counted per run id.

2. **The gate is sticky, the evidence is not.** `/ok-to-test` authorises a PR once; later commits do
   not revoke it. A publish, smoke, or e2e result speaks only for the head it ran against, so a
   result older than the latest commit is not evidence. The script compares every result to the head
   commit and says so when a result predates it.
3. **Order is fix, gate, publish.** Publishing before the gate is refused outright — openshift-ci
   answers "Cannot trigger testing until a trusted user reviews the PR and leaves an `/ok-to-test`
   message" — and costs a second publish cycle once the gate arrives.
4. **The publish workflow starts the tests, and a re-run is `/test e2e-ocp-helm`.** A successful
   publish report ends by posting `/test e2e-ocp-helm` itself, so a published head already has a run
   queued: the `e2e` stage means wait, not retrigger. The report asks for `/test e2e-ocp-helm` only
   when no run was started for the head. A re-run after a failure is a deliberate choice, and worth
   stating in the comment.

   `/publish` is for the artifact, not for the tests. It rebuilds the workspace's plugin images and
   is the only thing that creates the `publish` commit status — which is the single required status
   check on this repository's `main` ruleset, so a head that has never been published cannot merge
   even when its diff is test-only. A test-only diff therefore needs `/test e2e-ocp-helm` for
   evidence and one `/publish` for the status, not a publish per test iteration.

   A PR that touches no workspace is the exception: there is nothing to build and nothing to publish,
   so the `publish` status is at best a no-op and at worst never created at all, and the head sits
   `BLOCKED` on the one required check while every substantive check is green. Both outcomes have
   been seen on this repository: the no-op job has written a success status for such a head, and it
   has also been refused and written nothing. Treat that status as optional. Merge on the evidence
   that does exist — `Check and test`, which drives the changed script through node, plus
   `SonarCloud` — with the admin override, and say in the rationale that the required status cannot
   be relied on for this head rather than leaving the bypass unexplained.

   A Prow e2e check sitting at `pending — Job triggered` for half an hour is not a stall. The trigger
   hands the run to an external system that provisions a cluster and runs Playwright there, so the
   status changes only when that run finishes, and the check reports nothing in between. Do not re-post
   `/test e2e-ocp-helm` or `/publish` against a pending e2e check: that queues a duplicate run behind
   the first one, and the second result speaks for the same head anyway.

5. **A quality-gate failure outranks the gate and the publish.** Fixing SonarQube findings means another
   commit, and a commit invalidates every publish, smoke, and e2e result already earned, so the fix goes
   first. The request quotes the failing analysis comment's URL, because the findings live there and the
   agent reads them directly. A later `Quality Gate passed`, or a failure older than the head, is a
   superseded analysis and is not a stage.

   Spend **one** fix attempt on it, then check whether the analysis is actually required. In this
   repository it is not: the `main` ruleset requires exactly one status check, `publish`. An advisory
   failure therefore informs the merge instead of blocking it, and a second round that leaves a
   structural residue — duplication measured as a percentage of *new* lines punishes a small diff for
   a single repeated block — is money spent to satisfy a dashboard. Proceed, and record the residue in
   the merge rationale.

   The script enforces that budget: once a fix run has been attempted for the failing analysis it
   reports the residue as a note and lets the PR reach `gate` and `publish`, instead of returning
   `sonar` until the gate turns green. An attempt counts from its start comment *or* its outcome,
   because a run that dies early announces only the outcome.
6. **A diagnosis beats a review thread.** When the failing run has been diagnosed, the diagnosis says
   which check failed and why, and it is derived from the run rather than from reading the diff. Its
   comment is the specification, so the fix request quotes that comment: `/fs-fix can you incorporate
   the findings in <comment URL> to fix the e2e tests?`. The review that accompanies it is a summary of
   the same findings, and pointing at the summary loses the detail.

   The gate is that review, not the diagnosis body. A diagnosis quotes every verdict it considered —
   "Previous diagnosis ... `pr_regression`" — even when its own verdict is flake or "no action needed",
   so the body can never be searched for a keyword. The agent raises the review only when it wants its
   findings implemented, which makes it the trustworthy signal.

   A diagnosis that does not blame the PR changes the next step rather than the stage. A flake verdict
   asks for `/test e2e-ocp-helm`, which runs the tests again without rebuilding: the plugin images did
   not change, so a publish would spend a build to produce the same artifact. A pre-existing or
   product-bug verdict means the
   run cannot be made green by this PR, so the command is `none` and the note says to hold it or force
   it through. Diagnosing an already-diagnosed run only repeats the same answer.
7. **Only trusted comments gate.** A slash command from a bot, or from an outside contributor, does
   not satisfy the gate. GitHub Apps report a `CONTRIBUTOR` association, which reads like a human's
   and is not one.
8. **One workspace per PR.** The e2e scope is `-w <workspace>`. If the script reports more than one
   workspace for a PR, the pipeline steps do not apply to it unchanged.

9. **Age is a premise check, not just a rebase.** A head older than `STALE_DAYS` (14) is reported with
   its age, because the two rot mechanisms are independent: a branch can rebase cleanly and still be
   pointless. Before spending a build or a test cycle on a stale head, re-read the diff against `main`
   and ask whether the code it patches still looks the way the PR assumes and whether the failure it
   exists for still reproduces — then decide between rebase, re-scope, and close. In practice the
   answer is often close: of the stale PRs examined on 2026-10-22, three were retired this way — one
   because a dependency upgrade had already applied its fix, one because a workspace rework had
   rewritten the tests it edited, and one because the root cause had been removed at source. A fourth
   was sent to a rebase and a fifth merged only after the skip premise it rests on had been checked
   against five nightly builds, which is a different test: age asks whether the premise moved, the
   nightly asks whether the failure it covers still happens.

   For a test-fix PR the issue is not the specification. The issue records what broke; the file
   records whether the PR still patches it. The common way a test fix dies is not that the failure
   went away but that someone fixed the same defect a different way — `.first()` instead of a scoped
   locator, a substring match instead of a regex, a different search term entirely — which leaves the
   issue text perfectly accurate and the hunks obsolete. Read the touched files at the current head
   and compare the hunks to them before deciding. When the PR is a skip, also count its `test.skip`
   additions against the failing tests the issue lists: one skip per failing test, placed inside the
   test, because a `describe`-level skip silently disables whatever is added to that block later. A
   skip PR superseded by a narrower skip is closed on that basis alone; the product bug it works
   around stays open, because the skip never fixed it.

   A red nightly is not by itself evidence that the failure still reproduces, and a single green one
   is not proof that it died. Read why it failed: an error at 0ms means the test body never ran, and a
   0ms failure or a rollout timeout carrying a webhook 500 or an unready database pod is deployment
   infrastructure rather than the assertion under examination. A close on nightly evidence wants the
   same test passing across several consecutive builds.

   The script turns that into the command plan rather than leaving it as advice: a stale head whose
   stage would ask for `/publish` or `/test e2e-ocp-helm` is given the rebase request instead, since a
   build proves the artifact, not the premise. A stale head that is otherwise ready to merge keeps
   `merge` and carries the note, because merging an old branch is normal and the note is the decision
   input.

## Acting on the report

The script is read-only. Posting anything is an external write: invoke the named skill `mutation-gate`
and follow the gate it owns.

1. Run `status`. Read the command plan and the notes.
2. Group identical commands. State the whole set as one approved operation per PR — the target is
   `redhat-developer/rhdh-plugin-export-overlays#<number>@<head-sha>`, the preview body is the command
   — and wait for approval before posting any of them.
3. Post only what was approved, one PR at a time, and report each one's comment URL.
4. For `/fs-fix`, post the command the report prints. It is already the right body for the stage: the
   standard request to address the review threads and rebase, or, when the quality gate failed, that
   analysis comment's URL. Both point the agent at the threads or the findings, which it reads itself.
   Do not paraphrase the findings into the comment: a rewritten instruction is a new specification, and
   a wrong one becomes a commit. The report lists the review findings in its notes, for your reading.
5. Do not poll. An e2e run takes minutes to tens of minutes; post the step, report, and end the turn.
   The next `status` invocation shows what happened. A fix run is the same: it announces itself with a
   workflow link, then reports an outcome, and the `fixing` stage exists so a second request is not
   posted against a run that is already working.

## Reporting

Report the table, the changes since the previous check, the command plan, and anything held. Name the
stage for each PR rather than a bare pass or fail: "publish-failed for the current head, diagnosis
already posted" is actionable; "red" is not.
