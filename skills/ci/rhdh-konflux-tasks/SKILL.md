---
name: rhdh-konflux-tasks
description: >-
  Bumps Konflux Tekton task bundle digests in `.tekton` and `.tekton-templates`,
  applies each task's MIGRATION.md, regenerates PipelineRuns, and checks pins
  against data-acceptable-bundles so ECP does not reject expired or untrusted
  tag@sha256 refs (tasks.unsupported, required_untrusted_task_found). Then
  invokes /rhdh-base-images for the matching GitHub main or release-* branch so
  FROM tags, rpms.lock.yaml, and Node headers stay current. Use for
  "bump konflux task digests", "apply the tekton migration", "ECP violation",
  "expired task", "trusted task", "missing node headers", node-v*-headers.tar.gz,
  .nvm/releases, catalog builder.Containerfile, UBI nodejs,
  quay.io/konflux-ci/tekton-catalog/task-*
  upgrades such as buildah-oci-ta or prefetch-dependencies-oci-ta, and
  build-definitions MIGRATION.md URLs that 404. Runs on rhdh-plugin-catalog and
  RHDH midstream (updateDigests.sh, generatePipelineRuns.sh, updatePLRs.sh;
  generatePipelineRunsForPlugins.sh is the deprecated 1.9/1.10 name).
compatibility: "bash, skopeo, jq 1.7+, yq, and git; a checkout of the target Konflux branch. gh is optional, for PR creation."
---

# Konflux Tekton task updates

Keep builds working after a Konflux task tag bump: update the pinned
`tag@sha256` digests, apply what each task's `MIGRATION.md` documents, and
regenerate the PipelineRuns so they match the migrated templates.

## Route

Load `workflows/konflux-task-update.md`. It detects the repository layout and
sends you to the reference that matches:

- `references/konflux-plugin-catalog.md` — `rhdh-plugin-catalog`, marker
  `.tekton/updatePLRs.sh` (main / 2.1+). On 1.9 and 1.10 streams the generator
  is still named `.tekton/generatePipelineRunsForPlugins.sh` (deprecated;
  same layout).
- `references/konflux-rhdh-midstream.md` — RHDH midstream, variant A
  (`.tekton-templates/rhdh-pipeline.yaml`) and variant B
  (`.tekton-templates/rhdh-hub.yaml` with shared `build-pipeline-rhdh-*.yaml`).
- `references/konflux-migration-urls.md` — resolving a task name and tag to the
  live `MIGRATION.md`, since most tasks left `konflux-ci/build-definitions` and
  the versioned paths under it now 404.
- `references/konflux-trusted-tasks.md` — ECP / expired / untrusted pins;
  `scripts/check-trusted-tasks.sh` against `data-acceptable-bundles`.

After the digest/migration/trusted-task pass, invoke `/rhdh-base-images` **by
name** for the matching GitHub `main` or `release-*` line (see
[konflux-task-update.md](workflows/konflux-task-update.md) step 5). Do not run
that skill's scripts from here.

## Boundary with plugin midstream propagation

Two skills touch `.tekton`, and they touch it for different reasons.

- This skill owns Konflux task maintenance across a whole stream: digest bumps,
  migrations to templates and shared pipelines, and full PipelineRun
  regeneration for every component on the branch.
- `/rhdh-plugin-midstream-propagate` owns promoting one plugin workspace
  through overlays and into the catalog, including the surgical per-workspace
  PLR tag edit that goes with it — deliberately without a full regeneration.

If the request is "this plugin version needs to reach midstream", it is
`/rhdh-plugin-midstream-propagate`. If the request is "the Konflux tasks moved
and the pipelines need to catch up", it is this skill. Never run a full
regeneration to deliver a single workspace bump; it rewrites every component's
PLR.

## Boundary with base images

`/rhdh-base-images` owns `FROM` tags, `rpms.lock.yaml`, Node headers
(`.nvm/releases/node-v*-headers.tar.gz`), operator `go.mod`, plugin-catalog
`builder.Containerfile` / `.nvm/` / `konflux.additional-tags`, and overlays
`versions.json` `node`. This skill does not reconstruct that workflow. It maps
the Konflux stream to a GitHub branch selector, names the checkouts
(user-supplied, or `/rhdh-context`, including catalog and overlays), and
invokes `/rhdh-base-images`.

A Konflux log `could not find releases/node-v*-headers.tar.gz` is that handoff,
not a Tekton pin problem. Do not pin catalog FROM or copy `.nvm/` from this
skill.

| Konflux / catalog stream | `/rhdh-base-images` `-b` |
|--------------------------|--------------------------|
| `rhdh-1.9-rhel-9` | `release-1.9` |
| `rhdh-1.10-rhel-9` | `release-1.10` |
| `release-2.Y` | `release-2.Y` |
| `main` (2.1+) | `main` |
| other `rhdh-<ver>-rhel-<N>` | `release-<ver>` when that GitHub branch exists |

## Prefer `-oci-ta` task variants

When the Konflux catalog ships both a workspace-based task and an
`<name>-oci-ta` variant, **prefer the `-oci-ta` bundle** in templates,
shared pipelines, and PLRs. OCI-TA tasks pass artifacts via
`SOURCE_ARTIFACT` / `CACHI2_ARTIFACT` and `ociStorage` params instead of
the `source` workspace.

**Operator-bundle exception:** do not migrate `rhdh-operator-bundle.yaml` or
`rhdh-operator-bundle-*` PLRs to `-oci-ta` tasks on a stream-wide pass unless
the user explicitly requests operator-bundle changes. Hub, operator,
must-gather, and bootc are in scope. `rhdh-rag-content-*` is 1.10-only
(deprecated; removed on main / 2.1). Per-variant file lists:
[konflux-rhdh-midstream.md](references/konflux-rhdh-midstream.md#oci-ta-file-scope).

| Legacy task | Preferred OCI-TA task |
|-------------|----------------------|
| `git-clone` | `git-clone-oci-ta` |
| `prefetch-dependencies` | `prefetch-dependencies-oci-ta` |
| `buildah` | `buildah-oci-ta` |
| `source-build` | `source-build-oci-ta` |
| `sast-snyk-check` | `sast-snyk-check-oci-ta` |
| `sast-shell-check` | `sast-shell-check-oci-ta` |
| `sast-unicode-check` | `sast-unicode-check-oci-ta` |
| `push-dockerfile` | `push-dockerfile-oci-ta` |

**`prefetch-dependencies` → `prefetch-dependencies-oci-ta`** (pipeline task
name may stay `prefetch-dependencies`): add `SOURCE_ARTIFACT`,
`ociStorage`, `ociArtifactExpiresAfter`, `enable-package-registry-proxy`;
drop `dev-package-managers` and the `source` workspace; keep
`git-basic-auth` and `netrc`; wire downstream tasks to prefetch
`SOURCE_ARTIFACT` / `CACHI2_ARTIFACT` results.

OCI-TA swaps are **not** handled by `updateDigests.sh` — apply params and
workspaces from the task's live `MIGRATION.md`, then regenerate PLRs.

## Writing rules

Editing `.tekton` YAML, committing, pushing, and opening a pull request are
writes. Follow `/mutation-gate`.

- Always pass `--no-push` / `--nopush`. Do not push or open a PR unless the user
  explicitly asks. `generatePipelineRuns.sh` neither commits nor pushes. When the
  user does ask to open a PR/MR, invoke `/rhdh-pr-mr` by name after
  `/mutation-gate` approval.
- When this skill opens a PR or MR, end the title with the target branch in
  brackets, for example `chore: update Konflux Tekton tasks [release-2.1]`.
  Include `[main]` on `main`. `/rhdh-pr-mr` appends that suffix when it is missing.
- Always include https://github.com/redhat-developer/rhdh-skills/tree/main/skills/ci/rhdh-konflux-tasks in the body.
  Before opening, ask which Jira key to cite. If the user gives a key, add
  `https://redhat.atlassian.net/browse/<KEY>` and pass `--issue`. If they omit
  it or say "no jira", omit the Jira line and do not pass `--issue`. Do not
  look a key up and do not invent one.
- When replacing a legacy task with `-oci-ta`, edit templates and shared
  pipelines first, then regenerate PLRs (or patch inline `pipelineSpec` PLRs by
  hand). Editing only PLRs leaves the source of truth stale.
- Apply only the user actions a live `MIGRATION.md` documents. Skip "no action
  required" sections. Do not invent `verify_*` guards that freeze pipeline params
  and fail the next Konflux bump. Do run `scripts/check-trusted-tasks.sh` against
  the live trusted-task list — that is an ECP allow-list check, not param drift.
- Review `git diff` for `quay.io/konflux-ci/tekton-catalog/task-*` changes before
  committing.
- After the Tekton pass, invoke `/rhdh-base-images` by name (never its script
  paths). Map the stream to `main` or `release-*`. Pass named rhdh, catalog, and
  overlays checkouts so that skill pins `builder.Containerfile` / `.nvm/` /
  overlays `versions.json`. Do not edit those files from this skill.
- The human reviews the whole diff across `.tekton/` and `.tekton-templates/`
  and decides when it is pushed.

## Completion

An update is complete when every task whose tag moved is named with its old and
new tag, each one is paired with the migration that was applied or with the
reason none was needed, the affected templates and shared pipelines are listed,
and `generatePipelineRuns.sh` or `updatePLRs.sh` (or deprecated
`generatePipelineRunsForPlugins.sh` on 1.9/1.10) has run
wherever a template or pipeline parameter changed. Say which files were
regenerated and which were edited by hand. Variant B `build-pipeline-*.yaml`
files are never touched by the generator. `rhdh-rag-content-*` inline
`pipelineSpec` PLRs exist only on 1.10 (deprecated; removed on main / 2.1) —
edit those by hand when present; do not look for them on main.

`scripts/check-trusted-tasks.sh` (14-day horizon) is green, **or** the only
remaining issues are documented `expiring-no-successor` / `expired-no-successor`
warnings. Surface those in the user-facing summary (expiry date, re-run in a few
days, Slack `#konflux-users`). Do not treat a no-successor warning as debug.

`/rhdh-base-images` has run for the mapped GitHub branch (analyze at minimum).
Name current vs latest `FROM` tags, Node header version, whether headers or
RPMs changed, and on plugin-catalog the `builder.Containerfile` FROM old→new,
whether `.nvm/releases/` matches `node --version` in that image, and that
`grep konflux.additional-tags build/containerfiles/builder.Containerfile`
contains `node-v` matching `.nvmrc`. If that skill was skipped, say why (no
checkouts named and `/rhdh-context` found none).

State the commit state and, explicitly, that nothing was pushed, unless the user
asked for a push. Name any migration document that could not be resolved rather
than assuming the bump needed no action.
