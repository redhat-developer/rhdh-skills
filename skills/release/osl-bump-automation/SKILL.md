---
name: osl-bump-automation
description: Run the scripted status, prepare, and verify workflow for an OpenShift Serverless Logic (OSL) version bump across the rhdh-chart and rhdh-operator repositories.
---

# OSL bump automation

This skill reports and applies an OpenShift Serverless Logic (OSL) version bump across `redhat-developer/rhdh-chart` and `redhat-developer/rhdh-operator`: status, a dry-run plan, the edit, and a verification pass.

The workflow is implemented in the scripts under `scripts/`. Run them and read their output; do not reproduce the procedure as prompt steps, and do not re-derive the RHDHBUGS-3766/RHDHBUGS-3767 history on each run.

The two repositories are separate checkouts with separate histories, so a bump is always two independent changes.

## When to use

- A new OSL patch or minor release must land in both repositories - a CVE fix or a rebuild.
- Someone asks where a bump stands: tickets, pull requests, base branches, merged versus open, hold label, catalog state.
- A working tree needs checking before commit or review: did every OSL reference move?

Out of scope: merging pull requests, publishing to OperatorHub, and deciding that a CSV exists. Catalog state comes from the cluster or from `oc`, never from a ticket status.

## Prerequisites

| Dependency | Used for | If it is missing |
| --- | --- | --- |
| `acli`, or Atlassian MCP output passed with `--jira-json` | ticket state and PR references | the Jira section reports `unavailable` |
| `gh`, or GitHub MCP output passed with `--github-json` | PR state, base branch, merged or open, hold labels | the GitHub section reports `unavailable` |
| `oc` (optional) | `oc get packagemanifest logic-operator` | catalog state is reported as `unknown` |

A missing tool is reported as `unavailable`, never as "nothing found". `unknown` is a
valid catalog answer, and a Jira status never proves that a CSV is published.

## Commands

Run from the skill's directory. `status`, `plan`, and `verify` are read-only; `apply` requires `--write`, `plan` previews without it.

Run with `--workspace` pointing at the directory that contains `rhdh-chart/` and `rhdh-operator/`, or pass `--chart-repo` / `--operator-repo` explicitly.
Keep `--release` on: it refuses to run when a checkout is on the wrong branch for that release line.

Summarise the current state:

```bash
python3 scripts/osl_status.py --issue RHIDP-17562 --json
```

Plan a bump without writing:

```bash
python3 scripts/osl_bump.py plan --version 1.40.0 \
  --chart-repo <chart> --operator-repo <operator>
```

Apply it:

```bash
python3 scripts/osl_bump.py apply --version 1.40.0 \
  --chart-repo <chart> --operator-repo <operator> --write
```

Verify every reference agrees:

```bash
python3 scripts/osl_bump.py verify --version 1.40.0 \
  --chart-repo <chart> --operator-repo <operator>
```

`--kn-workflow-version <tag>` moves the kn-workflow tool tag only when it is passed; omitting it preserves the checked-in pin. Exit codes: `0` clean, `1` ran and found a mismatch, `2` could not run.

## Rules
- `apply --write` edits the working tree only. Do not commit, push, or open a pull request unless the engineer explicitly asks for the PRs.
- When they do: commit one signed-off change per repository, then hand off to `/rhdh-pr-mr` with the base branch from `references/osl-releases.json`. The skill owns push, PR/MR creation, attribution checks, and Jira linking - do not reimplement any of it here.
- Never merge, never remove a hold, and never publish to OperatorHub.
- Never infer catalog availability from a Jira status. If the catalog cannot be read, report `unknown`.
- Generated files must match their source: `dist/rhdh/install.yaml`, `bundle/rhdh/manifests/rhdh-plugin-deps_v1_configmap.yaml`, `README.md`, `values.schema.json`.
- The kn-workflow tool tag is not the OSL version. Rebuilds have shipped a CSV newer than the tool (SRVLOGIC-1303), so the pin is preserved unless `--kn-workflow-version` is passed.

## Reference

Read [references/osl-releases.json](references/osl-releases.json) before preparing a bump on a release line. It maps `1.9`, `1.10`, and `main` to their branches, records the kn-workflow pin policy, and lists the files each repository must change.

## Completion

Report what was produced: the status summary, the planned or applied file set, and the verfication result. State any dependency that was unavailable and any check that could not run.

A bump is complete only when `verify` exits `0` for each repository that was changed, and the diffs contain nothing beyond the reported files.
