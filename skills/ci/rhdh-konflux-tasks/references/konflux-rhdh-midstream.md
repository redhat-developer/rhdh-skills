# RHDH midstream layout (4-rhdh)

`updateDigests.sh` also updates `.tekton-templates/*.yaml` via `TEMPLATEPATH`.

Detect which variant applies **before** editing (see table below). Edit **templates and shared pipelines first**, then regenerate or patch PLRs.

## Layout detection

| Marker | Variant | Typical branches |
|--------|---------|------------------|
| `.tekton-templates/rhdh-pipeline.yaml` | **Unified** — one `pipelineSpec` template + `components.yaml` | `rhdh-1-rhel-9`, `rhdh-1.10-rhel-9`, … |
| `.tekton-templates/rhdh-hub.yaml` (no `rhdh-pipeline.yaml`) | **Shared build-pipeline** — PLR wrappers + `build-pipeline-rhdh-*.yaml` | `rhdh-1.9-rhel-9` |

If unsure, run: `ls .tekton-templates/rhdh-pipeline.yaml .tekton-templates/rhdh-hub.yaml 2>/dev/null`

## OCI-TA file scope

Canonical rule and task mapping table:
[SKILL.md § Prefer `-oci-ta`](../SKILL.md#prefer--oci-ta-task-variants).

| Variant | In scope for `-oci-ta` swaps | Out of scope |
|---------|------------------------------|--------------|
| A (unified) | `rhdh-pipeline.yaml`, `rhdh-bootc-pipeline.yaml`; `rhdh-rag-content-*` PLRs on **1.10 only** (deprecated; removed on main / 2.1) | `rhdh-operator-bundle.yaml`, `rhdh-operator-bundle-*` PLRs |
| B (1.9) | `build-pipeline-rhdh-hub.yaml`, `build-pipeline-rhdh-operator.yaml`, hub/operator PLR wrappers | `rhdh-operator-bundle.yaml`, `prefetch-dependencies-bundle` |

`generatePipelineRuns.sh` still regenerates operator-bundle PLRs from its
template; leave that template unchanged during hub/operator OCI-TA work unless
the user explicitly requests operator-bundle changes.

---

## Variant A: Unified pipeline layout

Used on current stable branches. Hub, operator, and must-gather share `rhdh-pipeline.yaml`; operator-bundle uses a separate template.

### Files to update

| Location | When to edit |
|----------|----------------|
| `.tekton-templates/rhdh-pipeline.yaml` | hub, operator, must-gather |
| `.tekton-templates/rhdh-operator-bundle.yaml` | operator-bundle (different task set) |
| `.tekton-templates/components.yaml` | Metadata for `generatePipelineRuns.sh` only |
| `.tekton/rhdh-hub-<N>-{push,pull}.yaml` | Regenerate from `rhdh-pipeline.yaml` |
| `.tekton/rhdh-operator-<N>-{push,pull}.yaml` | Regenerate from `rhdh-pipeline.yaml` |
| `.tekton/rhdh-must-gather-<N>-{push,pull}.yaml` | Regenerate from `rhdh-pipeline.yaml` |
| `.tekton/rhdh-operator-bundle-<N>-{push,pull}.yaml` | Regenerate from `rhdh-operator-bundle.yaml` |
| `.tekton/rhdh-rag-content-<N>-{push,pull}.yaml` | **1.10 only** (deprecated; removed on main / 2.1). Inline `pipelineSpec` — **edit directly** when present (not in `components.yaml`) |
| `.tekton/fbc-<version>-push.yaml` | FBC; `build-image-index` without prefetch |
| `.tekton/images-mirror-set.yaml` | Only if task bundles are referenced |

### Regenerate

```bash
cd .tekton
./generatePipelineRuns.sh -t <x.y>    # e.g. 1, 1.10
```

- Version `1` → files like `rhdh-hub-1-push.yaml`, branch `rhdh-1-rhel-9`
- Version `1.10` → `rhdh-hub-1-10-push.yaml`, branch `rhdh-1.10-rhel-9`
- Updates component PLRs from templates and FBC `target_branch` in `fbc-*-push.yaml`

### Generator notes

- Migrations: edit `pipelineSpec.params` and task `params` in `rhdh-pipeline.yaml` / `rhdh-operator-bundle.yaml`.
- `components.yaml` only when extending generator placeholders (output image, prefetch, storage, etc.).
- After `updateDigests.sh`, **always** run `generatePipelineRuns.sh` if templates were migrated earlier than PLRs (stale PLRs may still have `dev-package-managers`).

---

## Variant B: Shared build-pipeline layout (1.9)

Older branch layout. Hub and operator PLRs are thin wrappers (`pipelineRef`); Tekton `Pipeline` objects hold the real `pipelineSpec`.

### Files to update

| Location | When to edit |
|----------|----------------|
| `.tekton/build-pipeline-rhdh-hub.yaml` | Shared pipeline (hub + operator-bundle paths when `component-type` matches) |
| `.tekton/build-pipeline-rhdh-operator.yaml` | Shared pipeline for operator (parallel structure to hub file) |
| `.tekton-templates/rhdh-hub.yaml` | PLR wrapper — pass new **pipeline** params in `spec.params` |
| `.tekton-templates/rhdh-operator.yaml` | PLR wrapper — same |
| `.tekton-templates/rhdh-operator-bundle.yaml` | Inline `pipelineSpec` in template (like unified bundle) |
| `.tekton/rhdh-hub-<N>-{push,pull}.yaml` | Regenerate from `rhdh-hub.yaml` |
| `.tekton/rhdh-operator-<N>-{push,pull}.yaml` | Regenerate from `rhdh-operator.yaml` |
| `.tekton/rhdh-operator-bundle-<N>-{push,pull}.yaml` | Regenerate from `rhdh-operator-bundle.yaml` |
| `.tekton/fbc-<version>-push.yaml` | FBC pipelines |
| `.tekton/build-pipeline-rhdh-hub.yaml` | Also updated by `updateDigests.sh` (not a template) |

No `must-gather` or `rag-content` PLRs on this layout.

### Regenerate

```bash
cd .tekton
./generatePipelineRuns.sh -t <x.y>    # e.g. 1.9
```

Produces `rhdh-{hub,operator,operator-bundle}-1-9-{push,pull}.yaml` via `sed` on per-component templates; updates FBC `target_branch` to `rhdh-1.9-rhel-9`.

### Migration: `prefetch-dependencies-oci-ta` 0.3

Apply in **three** places:

1. **Pipeline params** on `build-pipeline-rhdh-hub.yaml` and `build-pipeline-rhdh-operator.yaml`:
   - Add `enable-package-registry-proxy` (default `"true"`).
2. **Prefetch tasks** `prefetch-dependencies-hub` and `prefetch-dependencies-operator`:
   - Remove `dev-package-managers`; pass `enable-package-registry-proxy: $(params.enable-package-registry-proxy)`.
3. **PLR templates** `rhdh-hub.yaml` / `rhdh-operator.yaml`:
   - Add `spec.params` entry so the value reaches the shared pipeline.

Operator-bundle prefetch (`prefetch-dependencies-bundle`) is out of scope —
see [OCI-TA file scope](#oci-ta-file-scope) above.

### Generator notes

- `generatePipelineRuns.sh` does **not** rewrite `build-pipeline-*.yaml`; edit those files directly for task/digest/migration changes.
- PLR `pipelineRef.name` must match pipeline metadata (`build-pipeline-rhdh-hub` / `build-pipeline-rhdh-operator`) — generated files already do.

---

## Both variants: commit locally, do not push

Typical outcome on a branch:

1. `updateDigests.sh --minor --no-push` → **one local commit** (digest bumps).
2. Migration edits + `generatePipelineRuns.sh` → **second commit** (or leave unstaged for human review).

Human reviews the full diff across `.tekton/` and `.tekton-templates/`, then pushes or opens a PR.
