---
name: rhdh-catalog-index
description: >-
  Resolves, overrides and verifies the RHDH plugin catalog index on a running
  deployment, for Helm and for the Operator. Finds the current manifest-list
  digest for a stream, writes the override in the shape each install path
  accepts, and proves it took by reading the install-dynamic-plugins init
  container rather than trusting a green pod. Use for "the catalog index is
  stale", "override the catalog index", "pin a different plugin-catalog-index",
  "wrong orchestrator or lightspeed version got installed", "CATALOG_INDEX_IMAGE",
  "global.catalogIndex.image.tag", "mirror the catalog index for a disconnected
  install", "which index did this deployment actually use", or when older plugin
  builds appear with no error in the log.
compatibility: "oc, helm, skopeo and python3; cluster-admin on the target cluster."
---

# Override the RHDH plugin catalog index

The index decides which build of every OCI plugin a deployment installs. When it
is stale or has to be mirrored, you override it — on the chart for Helm, on the
Backstage CR for the Operator.

This does not run e2e tests (`/e2e-deploy-rhdh`, `/rhdh-prow-trigger`), smoke
test a release (`/rhdh-smoke-tests`), or fix an index at the source. It changes
which index a deployment consumes, and proves the change landed.

## The trap that makes this worth a skill

A stale index **installs cleanly**. `install-dynamic-plugins.py` falls back from
`registry.access.redhat.com/rhdh/` to `quay.io/rhdh/` when a manifest is missing:

```python
RHDH_REGISTRY_PREFIX = 'registry.access.redhat.com/rhdh/'
RHDH_FALLBACK_PREFIX = 'quay.io/rhdh/'
```

An index that names digests never published to the Red Hat registry still finds
them on quay, so every plugin installs, the pod goes green, and the user quietly
gets older builds. Nothing in the log says so except the fallback count.

So "it installed" is never the result. The fallback count is.

A disconnected cluster mirroring only from the Red Hat registry has no such
escape hatch — there the same index fails to pull outright.

## Step 1: resolve the digest

```bash
python3 scripts/resolve_index_digest.py --stream 1.10 \
  --compare-to <digest currently deployed>
```

Exit 2 means the deployment is behind. The script prints the manifest-list
digest and its per-architecture children side by side, because taking the child
is the easy mistake: it pins the reference to one architecture, and both digests
sit in the same tag listing.

Use the **manifest list**. The chart and the Operator both pin the list.

## Step 2: apply the override

Follow `/mutation-gate` before either command — both restart the deployment.

### Helm

```bash
helm upgrade <release> -n <namespace> oci://quay.io/rhdh/chart --version <chart> \
  --set global.clusterRouterBase=<router-base> \
  --set global.catalogIndex.image.tag=<BARE digest, no sha256: prefix>
```

`tag` carries a bare digest because `repository` already ends in `@sha256`. Pass
`global.clusterRouterBase` on every helm command; never `--reuse-values`.

### Operator

```yaml
apiVersion: rhdh.redhat.com/v1alpha5
kind: Backstage
metadata:
  name: <name>
  namespace: <namespace>
spec:
  application:
    extraEnvs:
      envs:
        - name: CATALOG_INDEX_IMAGE
          value: registry.access.redhat.com/rhdh/plugin-catalog-index@sha256:<digest>
          containers:
            - install-dynamic-plugins
```

Three ways this is rejected or silently wrong:

- `extraEnvs` is an **object holding an `envs` list**. A bare list fails
  validation: `spec.application.extraEnvs in body must be of type object: "array"`.
- **No `oci://` prefix** on the value. The operator's own default carries none.
- `v1alpha3` and below are **no longer served** as of 1.10. Use `v1alpha5`.

This is per Backstage CR, so every instance in the cluster needs it. A
cluster-wide alternative is `RELATED_IMAGE_catalog_index` through
`Subscription.spec.config.env` — the operator's default config names it, but
nothing sets it by default and it has not been verified here. Say so rather than
recommending it as tested.

## Step 3: prove it took

```bash
python3 scripts/verify_index.py --namespace <namespace> \
  --expect-digest sha256:<digest>
```

Exit 2 means the deployment is still on another index. Three numbers decide it:

| | Stale index | After the override |
|---|---|---|
| index used | the old digest | the digest you passed |
| quay.io fallbacks | non-zero | **0** |
| plugins installed | same either way | same either way |

The fallback count going to zero is the part that matters. Plugins installing is
not evidence — they install either way.

If the init container has not finished, the script says so; wait and re-run
rather than reading a partial log.

## Where the default comes from

Worth knowing when someone asks why a fresh install is already wrong:

- **Helm** — `global.catalogIndex.image` in the chart's `values.yaml`, pinned by
  digest at release time.
- **Operator** — the `CATALOG_INDEX_IMAGE` env in the `rhdh-default-config`
  ConfigMap the CSV ships. Read it with
  `oc get cm rhdh-default-config -n <operator-ns> -o yaml | grep -A2 CATALOG_INDEX_IMAGE`.

Both are pinned at build time, so both go stale the same way. RHDHBUGS-3720 is
the worked example: 1.10.4 shipped with an index whose orchestrator and
lightspeed digests were never published to the Red Hat registry.

## Completion

Complete when the resolved manifest-list digest is stated, the override is shown
exactly as applied on the path it was applied to, and `verify_index.py` has been
run against the deployment afterwards with its three numbers reported — index
used, plugins installed, fallback count.

A run that ends at "the pod is green" is not complete. So is one that reports a
digest without saying whether it came from the list or from an architecture
child. When the fallback count is above zero after an override, say so plainly:
the deployment is still resolving plugins from quay, and the override did not
take.
