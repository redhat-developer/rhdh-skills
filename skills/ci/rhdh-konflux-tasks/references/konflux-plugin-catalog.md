# rhdh-plugin-catalog layout

## Files to update

| Location | When to edit |
|----------|----------------|
| `.tekton/oci-plugin-build-pipeline.yaml` | Shared `Pipeline`; most PLRs use `pipelineRef` |
| `.tekton/plugin-catalog-index-*-push.yaml` | Inline `pipelineSpec` (catalog index) |
| `.tekton/plugin-catalog-builder-*-{push,pull}.yaml` | Inline `pipelineSpec` (catalog builder) |
| `.tekton/*-push.yaml` (many components) | Usually `spec.params` only when migration adds pipeline params |
| `.tekton/*-pull.yaml` | Same when present |
| `.tekton/updatePLRs.sh` | Heredoc for regenerated PLRs + `*.Containerfile` (main / 2.1+) |
| `.tekton/generatePipelineRunsForPlugins.sh` | Deprecated name of `updatePLRs.sh` on 1.9 / 1.10 streams |
| `.tekton/updateToStableBranch.py` | Version renames only — not Konflux migrations |
| `build/scripts/checkTrustedTasks.sh` | ECP trusted-task check (same contract as the skill script) |
| `build/containerfiles/builder.Containerfile` | Pin UBI Node FROM (`ubi9/nodejs-*` or later `ubi10/nodejs-*`) `tag@sha256` to the latest image `/rhdh-base-images` reported for that image name; COPY `.nvm/` headers must match `node --version` in that image; rewrite `node-v*` in `konflux.additional-tags` to match `.nvmrc` |

Plugin PLRs with `pipelineRef: oci-plugin-build-pipeline` inherit task wiring from the shared pipeline; add PLR `spec.params` when migrations require explicit pipeline parameters.

## Regenerate

```bash
cd .tekton
./updatePLRs.sh -v <x.y.z> --nopush
# 1.9 / 1.10 streams still use the deprecated name:
# ./generatePipelineRunsForPlugins.sh -v <x.y.z> --nopush
```

## Validate trusted pins

After digest bumps or regen, run the 14-day-horizon checker —
[konflux-trusted-tasks.md](konflux-trusted-tasks.md):

```bash
./build/scripts/checkTrustedTasks.sh --json .tekton
```

## Generator: new pipeline params

Add to the PipelineRun heredoc `spec.params` when `oci-plugin-build-pipeline` gains a param, e.g.:

```yaml
  - name: enable-package-registry-proxy
    value: "true"
```

Do not embed full `pipelineSpec` in the generator.

## Version naming (x.y.z → x-y)

`updatePLRs.sh` (deprecated `generatePipelineRunsForPlugins.sh` on 1.9/1.10) derives `RHDH_XY_VERSION` from `-v x.y.z` (e.g. `1.10.0` → `1-10`). Use it everywhere; never hardcode `1-` in generated paths.

| Pattern | Example for 1.10.0 |
|---------|-------------------|
| PLR / Containerfile basename | `bcp-rbac-1-10-push.{yaml,Containerfile}` |
| Konflux component / application | `bcp-rbac-1-10`, `rhdh-plugin-catalog-1-10` |
| Target branch in CEL | `rhdh-1.10-rhel-9` (dots, not dashes) |
| Containerfile builder comment | `.tekton/plugin-catalog-builder-1-10-push.yaml` |

After regenerate, grep for stale `-1-push` (without minor version):

```bash
grep -R -F --include='*.Containerfile' -- '-1-push' .tekton
```

A hit like `plugin-catalog-builder-1-push.yaml` means the generator heredoc still hardcodes `1-` instead of `${RHDH_XY_VERSION}`.

## Catalog builder FROM and Node headers

`build/containerfiles/builder.Containerfile` is the image Konflux builds. It
**FROM**s `registry.access.redhat.com/ubi<N>/nodejs-<major>` (UBI 9 today; UBI
10 when that stream ships) and COPYs `.nvm/`, then unpacks
`releases/node-${NODE_HEADERS_VERSION}-headers.tar.gz` where
`NODE_HEADERS_VERSION=$(node --version)` in that FROM image. A missing tarball
is a **base-image / headers** gap, not a Tekton pin. Copying `.nvm/` while
leaving FROM on an older tag still builds the old Node.

This catalog tree has **no** `rpms.lock.yaml`.

After the digest bump, invoke `/rhdh-base-images` for the mapped GitHub branch
(`rhdh-1.9-rhel-9` → `release-1.9`, `rhdh-1.10-rhel-9` → `release-1.10`,
catalog `release-2.Y` → `release-2.Y`, `main` → `main`; later
`rhdh-*-rhel-10` streams use the same GitHub `release-*` / `main` mapping). Name the catalog checkout (and overlays, when
present). Do not run that skill's scripts from here, and do not pin FROM,
`.nvm/`, or `konflux.additional-tags` from this skill.
