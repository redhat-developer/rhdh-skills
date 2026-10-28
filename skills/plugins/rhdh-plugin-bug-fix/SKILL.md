---
name: rhdh-plugin-bug-fix
description: >-
  Reproduces, diagnoses, and fixes a defect in a Backstage plugin inside the
  rhdh-plugins or community-plugins repositories: resolve the report from a
  RHIDP, RHDHBUGS, RHDHPLAN or RHDHSUPP Jira key, a GitHub issue, or plain
  prose; locate the owning workspace; write a throwaway reproduction test that
  fails for the stated reason; record before and after Playwright video
  evidence for a UI defect; then apply the smallest fix and verify it. Use for
  "fix this plugin bug", "reproduce RHIDP-1234", a plugin that renders the
  wrong thing, or a regression that needs evidence before and after.
compatibility: "Node.js 22+, Yarn, Git, and a rhdh-plugins or community-plugins checkout; Playwright and ffmpeg for UI evidence; GitHub CLI or Jira access to read the report."
---

# RHDH Plugin Bug Fix

Own the path from a bug report to a verified fix. Reproduce before diagnosing,
diagnose before editing, and verify before reporting. The reproduction test is
diagnostic evidence and never ships.

## Start here

Follow `workflows/fix-bug.md` from the top. It resolves the issue reference,
triages the report for agent readiness, discovers the workspace, picks the
full-e2e or no-e2e branch, reproduces, fixes, verifies, and cleans up.

## Route by outcome

| Outcome | Load and follow |
|---|---|
| Reproduce, diagnose, and fix a plugin bug | `workflows/fix-bug.md` |
| Resolve a report to a plugin workspace | `references/workspace-map.md` |
| Author the temporary Playwright reproduction | `references/e2e-patterns.md` |
| Capture and convert before and after evidence | `references/video-recording.md` |

## Boundaries

- `/rhdh-forge` owns reading GitHub. Invoke it by name with the raw issue or
  pull request reference and consume the structured issue context it returns —
  key, summary, URL, repository, number, state, labels, description, and the
  candidate workspace with the strategy that resolved it. Confirm that
  workspace against the checkout before working in it, and ask the user when
  the strategy reports it unresolved. Do not parse the URL or run `gh issue
  view` here.
- `/rhdh-jira-context` owns the field meanings.
- `/grilling` is the design gate when several root causes remain plausible or
  materially different fixes carry different compatibility costs. Use the
  constraints it produces before implementing. If it is not installed, say so,
  name `/setup-rhdh-skills install` as the human's next step, and pause that branch.
- `/rhdh-test-placement` advises where a **permanent** regression test belongs.
  The reproduction test written here is throwaway and is deleted before the
  change is handed off.
- `/rhdh-plugin-authoring` owns feature work and public API design.
- `/rhdh-pr-create` owns staging, changesets, commits, pushes, pull requests,
  recording uploads, and issue updates.

Invoke a named skill and describe the handoff in the conversation. Never open
another skill's files.

## Invariants

- Reproduce the failure before editing product code. A "before" recording
  cannot be reconstructed after the fix.
- The temporary `_repro-<issue>.test.ts` is evidence, not a deliverable. Remove
  the exact file before handing the change off.
- Discover the workspace's real Playwright configuration, helpers, and
  neighbouring tests. `references/workspace-map.md` locates a likely workspace;
  it does not describe the current test infrastructure.
- Close the Playwright context so each video finalizes, and keep before and
  after recordings until publication has consumed them.
- State the root cause with observed evidence before implementing, then make
  the smallest fix consistent with the repository's conventions.
- If a test still fails, return to diagnosis. Never weaken an assertion to make
  it pass.
- Adding a label or a triage comment to an issue is an external write. Invoke
  the named skill `mutation-gate` and follow it; the operation's target is
  the exact repository and issue number. A request to fix a bug approves no
  issue write.
- Do not stage, commit, push, or open a pull request here.

## Completion

Report the resolved issue and workspace, the reproduction and what it proved,
the root cause with its evidence, the files changed and left unstaged, the
before and after recording paths, the verification commands and their results,
the test plan a reviewer should run, and the named skill to invoke next for
publication.
