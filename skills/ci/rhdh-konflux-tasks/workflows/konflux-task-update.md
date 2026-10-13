# Konflux Tekton updates

## Goal

After a **minor** Konflux task tag bump, update `.tekton` pipelines and generators so builds keep working. Apply what each `MIGRATION.md` says; do **not** add drift tests that block future Konflux updates.

## Prerequisites

`skopeo`, `jq` (>= 1.7), `yq`. Optional: `gh` for PR creation from scripts.

## Commit locally; never push without human review

| Script | Flag | Effect |
|--------|------|--------|
| `updateDigests.sh` | `--no-push` / `--nopush` (`-p`) | Commit locally; no push/PR |
| `updateDigests.sh` | `--minor` | Disables push; use with `--no-push` for clarity |
| `updateDigests.sh` | `--no-commit` / `-n` | Preview only |
| `updatePLRs.sh` | `--nopush` | Commit locally; no push |
| `updatePLRs.sh` | `--nocommit` | Write YAML only |
| `generatePipelineRunsForPlugins.sh` | `--nopush` / `--nocommit` | Deprecated name on 1.9 / 1.10; same flags |

`generatePipelineRuns.sh` does not commit or push.

**Do not** run digest/generator scripts without `--no-push` / `--nopush` unless the user explicitly requests a push.

## Detect repo layout

| Marker in repo | Read |
|----------------|------|
| `.tekton/updatePLRs.sh` | [konflux-plugin-catalog.md](../references/konflux-plugin-catalog.md) — main / 2.1+ |
| `.tekton/generatePipelineRunsForPlugins.sh` | [konflux-plugin-catalog.md](../references/konflux-plugin-catalog.md) — 1.9 / 1.10 (deprecated name) |
| `.tekton-templates/rhdh-pipeline.yaml` | [konflux-rhdh-midstream.md](../references/konflux-rhdh-midstream.md) — **variant A** (unified) |
| `.tekton-templates/rhdh-hub.yaml` (no `rhdh-pipeline.yaml`) | [konflux-rhdh-midstream.md](../references/konflux-rhdh-midstream.md) — **variant B** (1.9 shared build-pipeline) |

If both plugin-catalog and midstream markers exist, apply changes only for the repo/branch you are on.

## Workflow

### 0. OCI-TA preference (before digest bump)

Scan for legacy (non-OCI-TA) `taskRef` bundles and migrate where the catalog
offers `<name>-oci-ta` — [SKILL.md § Prefer `-oci-ta`](../SKILL.md#prefer--oci-ta-task-variants).
Midstream paths in scope vs out of scope:
[konflux-rhdh-midstream.md § OCI-TA file scope](../references/konflux-rhdh-midstream.md#oci-ta-file-scope).

### 1. Bump digests

```bash
cd .tekton
./updateDigests.sh --minor --no-push
```

- Updates `tag@sha256` in `.tekton/*.yaml` and `.tekton-templates/*.yaml` (via `TEMPLATEPATH`).
- On variant B, also updates `.tekton/build-pipeline-rhdh-*.yaml`.
- Tag changes list `MIGRATION.md` URLs via `migrationDocURL` in `updateDigests.sh` (see [konflux-migration-urls.md](../references/konflux-migration-urls.md)). Do not use deleted `build-definitions/task/<name>/<tag>/` paths.
- If `updateDigests.sh` still hard-codes those 404 URLs, update it to use `migrationDocURL`, then re-run or rewrite printed links before opening a browser.
- Digest-only (no tag bump): `./updateDigests.sh --no-push -q`

Review `git diff` for `quay.io/konflux-ci/tekton-catalog/task-*` changes.

### 2. Apply migrations

For each tag bump from `updateDigests.sh` (or from the diff):

1. Resolve the live migration doc with [konflux-migration-urls.md](../references/konflux-migration-urls.md) (example: [`buildah-oci-ta/MIGRATION.md`](https://github.com/konflux-ci/build-pipeline-tasks/blob/main/task/buildah-oci-ta/MIGRATION.md)).
2. Fetch raw `MIGRATION.md` (and `CHANGELOG.md` / `migrations/*.sh` if needed).
3. Apply **only** documented user actions in templates and shared pipelines (see [konflux-rhdh-midstream.md](../references/konflux-rhdh-midstream.md) for per-variant file list).
4. Skip “no action required” sections.

If PLRs still contain removed params (e.g. `dev-package-managers`) but templates are fixed, migrations are incomplete until step 3.

### 3. Regenerate PipelineRuns

**Always run** after template or shared-pipeline migration edits (not optional when params changed):

```bash
cd .tekton
./generatePipelineRuns.sh -t <version>
```

| Branch example | `-t` value | PLR suffix |
|----------------|------------|------------|
| `rhdh-1-rhel-9` | `1` | `rhdh-hub-1-push.yaml` |
| `rhdh-1.9-rhel-9` | `1.9` | `rhdh-hub-1-9-push.yaml` |
| `rhdh-1.10-rhel-9` | `1.10` | `rhdh-hub-1-10-push.yaml` |

On **main** / next midstream trees whose CEL already uses `target_branch == "main"`, after regen with `-t 2` (or similar), restore CEL/`on-push-for-*` to `main` if the generator rewrote them to `release-<version>`.

- **Variant A:** on **1.10 only**, also patch `rhdh-rag-content-<N>-{push,pull}.yaml` by hand (inline `pipelineSpec`, not generated). That prefix is deprecated and is gone on main / 2.1 — skip it there.
- **Variant B:** hub/operator PLRs regenerate from `rhdh-hub.yaml` / `rhdh-operator.yaml`; `build-pipeline-*.yaml` is edited directly, not by the generator.

Commit migration + regen locally when ready; do not push until human review.

### 4. Trusted-task / ECP check

After regen, validate pins against `data-acceptable-bundles` with a **14-day**
expiry horizon — [konflux-trusted-tasks.md](../references/konflux-trusted-tasks.md).
This is the live ECP allow-list, not a frozen `verify_*` param-drift guard.

```bash
scripts/check-trusted-tasks.sh --json .tekton .tekton-templates
```

On plugin-catalog, `build/scripts/checkTrustedTasks.sh` is the same script.

- Exit 1 with a successor: `--apply-trusted-digests` for same-tag SHA, or
  `updateDigests.sh --minor` plus `MIGRATION.md` when the suggested pin is a
  new tag. Re-check.
- `expiring-no-successor` / `expired-no-successor`: **must** appear in the
  user-facing summary (expiry date, re-run in a few days, Slack `#konflux-users`).
  Do not invent a pin. `expired-no-successor` is a hard stop.

### 5. Base images, RPMs, Node headers

Konflux plugin-catalog builds COPY `.nvm/` and fail when the builder image's
Node version has no matching `releases/node-v*-headers.tar.gz` (log:
`could not find releases/node-v*-headers.tar.gz`). That is **not** a Tekton
digest problem.

1. Map the stream to a GitHub selector — [SKILL.md § Boundary with base images](../SKILL.md#boundary-with-base-images). Example: catalog `rhdh-1.10-rhel-9` → `-b release-1.10`; catalog `release-2.1` → `-b release-2.1`.
2. Name `rhdh`, `rhdh-operator`, `rhdh-must-gather`, plugin-catalog, and overlays checkouts (user, or `/rhdh-context`).
3. Invoke **`/rhdh-base-images` by name**. Do not run `base-images-and-rpms.sh` from this skill. Analyze first; if headers, `FROM` tags, catalog builder pins, overlays `versions.json` `node`, or RPMs are stale, let that skill own the update and `/mutation-gate`.
4. Do not pin `builder.Containerfile`, copy `.nvm/`, or edit overlays `versions.json` from this skill.

### 6. Human review and push

Human reviews the full diff (digest commit plus any migration/regen commits), then `git push` or opens a PR.

When this skill opens a PR or MR, end the title with the target branch in brackets (`chore: update Konflux Tekton tasks [release-2.1]`, including `[main]`). `/rhdh-pr-mr` appends that suffix when it is missing. Always include https://github.com/redhat-developer/rhdh-skills/tree/main/skills/ci/rhdh-konflux-tasks in the body. Before opening, ask which Jira key to cite. If the user gives a key, add `https://redhat.atlassian.net/browse/<KEY>` and pass `--issue`. If they omit it or say "no jira", omit the Jira line and do not pass `--issue`. Do not look a key up and do not invent one.

## Known migration patterns

Use live `MIGRATION.md` as source of truth. Common cases:

| Task | Action |
|------|--------|
| `prefetch-dependencies` → `prefetch-dependencies-oci-ta` | See [SKILL.md § Prefer `-oci-ta`](../SKILL.md#prefer--oci-ta-task-variants). |
| `prefetch-dependencies-oci-ta` 0.2→0.3 | Remove `dev-package-managers`; add pipeline param `enable-package-registry-proxy` (default `"true"`) and pass to prefetch task. Variant B: also add param on `build-pipeline-rhdh-{hub,operator}.yaml` tasks `prefetch-dependencies-hub` / `prefetch-dependencies-operator`, and on PLR `spec.params` in `rhdh-hub.yaml` / `rhdh-operator.yaml`. |
| `build-image-index` 0.2→0.3 | Remove `COMMIT_SHA` / `IMAGE_EXPIRES_AFTER` from **build-image-index** task only; keep on buildah (`build-container`) and prefetch |
| `init` 0.3→0.4 | No pipeline changes |
| `init` 0.4.1→0.4.2 | Remove broken auto-added `sast-target-dirs` pipeline param if present |
| `init` 0.4.2→0.4.3 | Add opt-in pipeline params `source-date-epoch`, `rewrite-timestamp`, `omit-history` and wire to buildah as `SOURCE_DATE_EPOCH` / `REWRITE_TIMESTAMP` / `OMIT_HISTORY` |
| `show-sbom` / `summary` (deprecated) | Remove `show-sbom` / `show-summary` finally tasks (migration scripts delete them) |

## Anti-patterns

- Opening or fetching `build-definitions/blob/main/task/<name>/<full-tag>/MIGRATION.md` (deleted; use [konflux-migration-urls.md](../references/konflux-migration-urls.md)).
- Pushing without `--no-push` / `--nopush` and human sign-off.
- Leaving removed task params (`dev-package-managers`, `COMMIT_SHA` on `build-image-index`).
- Skipping `generatePipelineRuns.sh` after fixing templates while PLRs still reference old params.
- Editing only PLRs when templates or `build-pipeline-*.yaml` are the source of truth.
- Adding `verify_*` guards that freeze pipeline params and fail the next Konflux bump (the trusted-task check is different: it reads the live allow-list).
- Dropping `image-expires-after` from PLRs only because `build-image-index` no longer uses it.
- Hardcoding `1-` in `updatePLRs.sh` (or deprecated `generatePipelineRunsForPlugins.sh`) Containerfile comments; use `${RHDH_XY_VERSION}` so `1.10.0` becomes `1-10`, not `1`.
- Migrating operator-bundle to `-oci-ta` on a stream-wide pass — see [SKILL.md § Prefer `-oci-ta`](../SKILL.md#prefer--oci-ta-task-variants).
- Reconstructing `/rhdh-base-images` script flags in this skill, or skipping that handoff when Konflux logs `could not find releases/node-v*-headers.tar.gz`.
- Copying plugin-catalog `.nvm/` headers while leaving `builder.Containerfile` FROM on an older UBI Node tag. Konflux still builds the old Node until FROM moves.
- Copying headers / `.nvmrc` while leaving a stale `node-v*` in `konflux.additional-tags`. Konflux keeps publishing the old tag until that label matches `.nvmrc`.
