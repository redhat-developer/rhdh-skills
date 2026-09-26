---
name: rhdh-overlay
description: >-
  Manages the rhdh-plugin-export-overlays repository and Extensions Catalog:
  onboard plugins, update upstream versions, repair export or publish failures,
  inspect workspace health, triage the overlay PR backlog by label, staleness
  and merge readiness, and trigger /publish. Use for source.json,
  plugins-list.yaml, backstage.json, catalog metadata, overlay CI, plugin
  import, overlay PRs, or testing exact PR artifacts before merge. For
  read-only package or catalog plugin inventory, support levels, release diffs,
  or plugin vs package support alignment, use /rhdh-product-catalog. For
  code-level review of a pull request, use /rhdh-pr-review. To promote an
  rhdh-plugins release through overlays into rhdh-plugin-catalog, use
  /rhdh-plugin-midstream-propagate.
compatibility: "Git, GitHub CLI, Python 3, and a checkout of rhdh-plugin-export-overlays."
---

# RHDH Overlay

Own catalog packaging and overlay-repository operations. Work from a checkout
whose remote identifies `redhat-developer/rhdh-plugin-export-overlays`; do not
depend on another installed skill's files or CLI.

## Start here

1. Read repository instructions and run `gh auth status`.
2. Confirm the checkout and remote with `git remote -v`.
3. Inspect the target workspace, a similar workspace, and the relevant PR or CI
   logs before changing metadata.
4. For environment problems, follow `workflows/doctor.md`.

## Route by outcome

| Outcome | Load and follow |
|---|---|
| Onboard a plugin | `workflows/onboard-plugin.md` |
| Update source version or commit | `workflows/update-plugin.md` |
| Diagnose an export or publish failure | `workflows/fix-build.md` |
| Check workspace status | `references/overlay-repo.md`, then inspect workspace files and recent `gh` runs |
| Triage the open PR backlog | `workflows/triage-prs.md`; use `scripts/triage-prs.py` for deterministic classification |
| Analyze one overlay PR | `workflows/analyze-pr.md`; use `scripts/analyze-pr.py` |
| Draft stale-PR notifications | `workflows/draft-notification.md` |
| Trigger publish | Run the guarded publish procedure below |

Infer a clear route. Ask only for a missing plugin, workspace, source ref, or PR
number that cannot be discovered from the checkout.

## Invariants

- Every export is configured in the overlay repository; CI performs the export.
- `source.json` `repo-backstage-version` is the upstream source's actual
  Backstage version. `backstage.json` `version` is the RHDH compatibility
  override. Never substitute one for the other.
- Derive packages and refs from upstream and generated metadata; never invent an
  OCI URL.
- Copy the structure of a current, similar workspace when repository conventions
  differ from this skill's examples.
- Before merge, test the exact PR artifact. Authentication errors from an
  otherwise loaded plugin may be acceptable; installation or boot errors are
  not.

## Guarded publish

Before posting `/publish`, verify the PR is open, lacks `do-not-merge`, and has
no successful publish check for the current head. Posting the comment is an
external write: invoke the named skill `mutation-gate` and follow the gate
it owns rather than restating it here.

State one operation. Its target is
`redhat-developer/rhdh-plugin-export-overlays#<number>@<head-sha>`, its preview
body is `/publish`, its preconditions are those three checks, and on failure it
reports the comment for manual removal if the trigger was wrong. Only after the
user approves that stated operation, run:

```bash
gh pr comment <number> --repo redhat-developer/rhdh-plugin-export-overlays --body "/publish"
```

Report the comment and publish-check URLs, or the failure and what recovery it
needs. A request to trigger publication is intent to read the PR, not approval
of this write.

## Other external writes

The same gate covers every push, PR creation, notification, or other external
write a workflow reaches. State operations only once targets and payloads are
exact, run nothing absent from the approved set, and report an outcome for every
operation including the ones that were skipped. Read-only triage and analysis
need no gate.

## What a caller supplies

A caller invokes this skill by name and states the source repository, the source
ref (commit or tag), the packages, the upstream Backstage version, and the target
RHDH version.

## What this skill reports

- the workspace, and what changed in it: source ref, packages, metadata files
- CI and local verification evidence, with skipped checks and their reasons
- the pull request URL, or that none was opened
- publish status: not requested, pending, passed, or failed
- the outcome of every approved external write
- remaining compatibility risks

For local verification, invoke `/rhdh-local` by name and give it the exact
artifact references, plugin config, named environment variables, and checks to
run. Do not load the local skill's files.

## Completion

Complete when the report covers workspace and metadata changes, commands and
scripts run, CI and local verification evidence, the outcome of every approved
write, publish status, and remaining compatibility risks.
