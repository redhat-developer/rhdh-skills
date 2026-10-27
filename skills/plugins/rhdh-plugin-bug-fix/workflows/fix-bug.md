# Workflow: Reproduce, Diagnose, and Fix a Plugin Bug

This workflow accepts a Jira key or URL, a GitHub issue URL or number, or a
plain bug report. It always verifies the fix before handing the change off. The
legacy `--no-verify` flag means "skip the human review pause"; it never skips
technical verification.

## Hard invariants

- A temporary `_repro-<issue>.test.ts` is diagnostic evidence, never a
  deliverable. Remove it before producing the artifact.
- In full-e2e mode, reproduce and record the failure before editing product
  code. A "before" recording cannot be reconstructed afterward.
- Discover current workspace infrastructure from `playwright.config.ts`,
  `e2e-tests/utils/`, translations, and neighboring tests. The mapping in
  `references/workspace-map.md` only locates a likely workspace.
- UI bug evidence requires before and after recordings. Close the Playwright
  context so each video is finalized.
- Never stage, commit, push, or publish directly from this workflow.

## 1. Resolve issue context

Parse without making a network call:

- Jira: `(RHIDP|RHDHBUGS|RHDHPLAN|RHDHSUPP)-<number>` from a key or browse URL.
- GitHub: `github.com/<owner>/<repo>/issues/<number>`; for bare `#<number>`,
  derive the repository from `git remote -v`.
- Plain report: set source to `none` and retain the user's text.

For Jira, read the issue with your Jira tool and consume the detail it
returns, without reading token files into context. For GitHub, invoke `/rhdh-forge` by name with
the raw reference; do not parse the URL or run `gh issue view` here. It returns
the key, summary, source, URL, repository, number, state, labels, description,
and a candidate workspace with the strategy that resolved it — treat the
workspace as a candidate, confirm the directory exists in the checkout, and ask
the user when the strategy reports it unresolved. If `/rhdh-forge` is not
installed, say so, name `/setup-rhdh-skills install` as the human's next step, and ask
the user for the issue detail rather than guessing at it.

Record: source, key or number, URL, title, description, labels/component,
reproduction steps, expected result, and attachments.

Run the capability checks needed by the selected branch:

| Capability | Required when | Check |
|---|---|---|
| Git checkout | Always | `git remote -v` identifies rhdh-plugins or community-plugins |
| Node and Yarn | Always | `node --version`; `yarn --version` |
| GitHub CLI | GitHub issue or auto-publication | `gh auth status` |
| Jira access | Jira issue | your authenticated Jira tool |
| ffmpeg | UI evidence conversion | `ffmpeg -version`; warn and retain WebM if absent |

Stop this branch with a precise setup requirement when a required capability is
missing. Do not ask for secret contents.

## 2. Triage for agent readiness

Require reproducible steps, expected behavior, identifiable component or
workspace, and target repository. If any field is missing:

1. Report exactly which fields are missing.
2. When issue mutation is in scope, compose the checklist comment and invoke
   `/prose-editing` once on it in the **flavored** register. Preserve field names,
   labels, issue keys, reproduction steps, and quoted errors.
3. Add `not-ready-for-agent` and the edited checklist comment through the issue's
   own tool; the transport layer must not edit it again.
4. Stop before changing code.

When triage passes, report the extracted issue, repository, and workspace.

## 3. Discover workspace and choose mode

Use `references/workspace-map.md` to locate candidates, then verify the actual
checkout. Read workspace instructions, package manifests, Playwright config,
test helpers, translation refs, and neighboring component/tests.

- **full-e2e**: a Playwright harness exists and the failure is visible in UI.
- **no-e2e**: backend, configuration, pure logic, or no usable Playwright
  harness.

If dependencies are missing or stale, run the repository's documented install
command before testing.

## 4A. Reproduce a UI bug

Load `references/e2e-patterns.md` and `references/video-recording.md`.

1. Create `e2e-tests/_repro-<issue>.test.ts` using the target repository's
   current Playwright imports and helpers.
2. Create the browser context directly with
   `recordVideo: {dir: 'test-results/', size: {width: 1280, height: 720}}`.
   Reuse discovered helpers only for navigation and mocks; do not let a helper
   replace the recording context.
3. Encode the issue's steps and assert the expected behavior.
4. Discover the dev-server port. If another process owns it, show the process
   and obtain confirmation before terminating it.
5. On Unix, raise the file descriptor limit for the test process when needed.
   Run the reproduction in the workspace's legacy or configured mode.
6. The test must fail for the described reason. Refine at most twice; if the
   issue still cannot be reproduced, return the evidence and ask for guidance.
7. Preserve the finalized video as
   `e2e-tests/_repro-artifacts/before-fix.webm`.

Capture a screenshot, target DOM snapshot, and relevant computed styles before
editing code. These are diagnostic evidence, not PR files.

## 4B. Reproduce a non-UI bug

1. Run the narrowest existing test that should expose the failure.
2. If none does, create a temporary `_repro-<issue>.test.ts` beside the relevant
   tests, mirroring current imports and setup.
3. Confirm it fails for the described reason. Diagnose from source, stack
   traces, logs, and test output.

## 5. Diagnose and fix

Trace failing behavior to the rendering component, backend service, API client,
or configuration boundary. State the root cause with observed evidence before
editing. Then implement the smallest fix consistent with repository conventions.

Pause for user choice when multiple root causes remain plausible, the fix
changes a public API, or materially different fixes have different compatibility
costs. For an under-specified architectural choice, invoke `/grilling` and use
its resulting constraints before implementation. If it is not installed, say so,
name `/setup-rhdh-skills install` as the human's next step, and pause that branch.

Run type checks and the target repository's narrow tests after each meaningful
change.

## 6. Verify

### Full-e2e

1. Re-run the same reproduction test; it must pass.
2. Preserve the finalized recording as
   `e2e-tests/_repro-artifacts/after-fix.webm`.
3. Run the relevant unit/component suite and TypeScript check.
4. Run the NFS variant when the workspace supports both systems and the change
   could affect both.
5. Convert WebM files to GIF with the commands in
   `references/video-recording.md` when ffmpeg is available; otherwise retain
   WebM and record the limitation.

### No-e2e

Run the repository's TypeScript check and relevant unit/integration suite. The
existing or temporary reproduction must now pass.

If a test still fails, return to diagnosis rather than weakening the assertion.

## 7. Clean diagnostic files and assemble the handoff

Verify both UI recordings exist before cleaning. Remove only the exact temporary
reproduction test and `test-results/`; retain `_repro-artifacts/` until any
requested PR publication has consumed it. In no-e2e mode, remove the exact
temporary unit test if one was created.

Assemble the handoff in prose:

- A concise, user-visible summary of the fix.
- The changed files. Verify them against `git status`; do not stage.
- The verification commands run and whether each passed.
- The repository and workspace.
- The issue: its source (Jira, GitHub, or none), key or number, URL, and title.
- The root cause, stated with the evidence that supports it.
- The before and after recording paths, or explicitly none.
- A test plan, derived from the positive reproduction steps, the expected
  behavior, and one regression check.

Omit nothing silently and invent no evidence. Say "none" where there is none.

## 8. Verification pause or named handoff

- Default: present modified files, root cause, evidence, recording paths, and
  test plan. Stop for local user verification.
- With explicit auto-publication or legacy `--no-verify`: after technical
  verification, invoke `/rhdh-pr-create` by name with that handoff and skip only
  this local verification pause. There is no auto-approve mode: that skill still
  requires the user's approval of each external write. It owns staging — the
  unstaged changed files included — through issue updates.
- If `/rhdh-pr-create` is not installed, say so, name `/setup-rhdh-skills install` as
  the human's next step, and retain the evidence paths.

Once publication reports the recordings uploaded, remove the exact
`e2e-tests/_repro-artifacts/` directory and report the cleanup. Never remove it
before the upload has succeeded or been handed back for manual action.

## References

| Reference | Load when |
|---|---|
| `references/workspace-map.md` | Resolving an issue to a plugin workspace |
| `references/e2e-patterns.md` | Authoring the temporary UI reproduction |
| `references/video-recording.md` | Capturing and converting before/after evidence |
