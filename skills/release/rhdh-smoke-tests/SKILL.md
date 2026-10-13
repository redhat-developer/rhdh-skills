---
name: rhdh-smoke-tests
description: >-
  Walks RHDH smoke tests: inspect plugin-catalog-index OCI refs first, then Helm
  and Operator in parallel (one namespace each): install the previous GA, upgrade
  to this RC, then if this stream is not the newest, upgrade to the latest GA of
  the next minor. Sets Helm global.clusterRouterBase on every helm command (never
  --reuse-values). Prompts for an OpenShift console URL and oauth/token/display
  when oc is not logged in. Enables Guest via Helm upstream.backstage.appConfig
  or an Operator ConfigMap, then verifies pods, Guest sign-in, and extensions
  packages totalItems. Use for "run the helm smoke tests", "operator RC smoke",
  "parallel helm and operator smoke", "catalog-index smoke", "plugin-catalog-index
  pull", "inspect catalog OCI refs", "clusterRouterBase", "console URL login",
  "upgrade 1.10.3 to 1.10.4 RC", "1.9.8 to 1.9.9 then 1.10", "GA smoke test",
  or "SMOKE_TESTS helm and operator".
compatibility: >-
  oc, helm, python3, podman, skopeo, jq; a dedicated smoke kubeconfig (not
  Konflux); an rhdh-plugin-catalog checkout with build/scripts/checkIndexRefsPullable.sh.
---

# RHDH Helm and Operator smoke tests

Smoke test after an RC (Quay CI chart / IIB). Catalog-index OCI refs run
**first**. Helm **and** Operator are both mandatory after that. One Helm
namespace and one Operator namespace — the three checks are a chain in that
namespace, not three installs.

This is not full QE, Prow e2e, local compose, or an operator-PR catalog test.

## Route

1. Collect tags. Stop if tags are missing — do not invent CI tags. Require
   `INDEX_IMAGE` or derive
   `registry.access.redhat.com/rhdh/plugin-catalog-index:${RC_VER}`. Require
   `CATALOG_REPO` (rhdh-plugin-catalog checkout that contains
   `build/scripts/checkIndexRefsPullable.sh`).
2. Catalog-index OCI check **first**, before any Helm install/upgrade or
   Operator CSV work. Load `workflows/catalog-index.md`. That agent gets
   `CATALOG_REPO` and `INDEX_IMAGE` only (no kubeconfig). Wait until it
   finishes. A catalog fail does not skip Helm/Operator.
3. Establish `oc` (login below). Derive `CLUSTER_ROUTER_BASE` before Helm.
4. Default is an **RC** run. A **GA** run (published chart / OperatorHub `fast`,
   including `fast` ↔ `fast-1.y`) only when the user asked for GA.
5. Follow `/mutation-gate` **once** for both cluster chains (login + Helm +
   Operator). Then launch two agents in the **same turn** (Helm and Operator).
   Do not wait for Helm to finish before launching Operator. Do not run both
   cluster chains in the parent. Do not start them until step 2 has completed.
6. Load `workflows/helm.md` in the Helm agent, `workflows/operator.md` in the
   Operator agent.
7. After every install or upgrade: Guest (below), then verify (below), then a
   live line (below).

| Load when | File |
|---|---|
| Catalog-index OCI (first) | `workflows/catalog-index.md` |
| Helm chain | `workflows/helm.md` |
| Operator chain | `workflows/operator.md` |
| Guest fragment | `assets/app-config-guest.yaml` |
| Helm Guest overlay | `assets/helm-values-guest.yaml` |
| Console URL → router / API | `scripts/cluster_from_console.py` |

`SKILL_DIR` is the directory that contains this `SKILL.md`. The catalog script
lives in the plugin-catalog repo, not under `SKILL_DIR`.

## Cluster login

If `oc whoami` already succeeds, skip the prompt. Prefer the live domain:

```bash
oc get ingresses.config.openshift.io cluster -o jsonpath='{.spec.domain}'
```

That value is `CLUSTER_ROUTER_BASE` (example:
`apps.ci-ln-ibvnlsb-72292.gcp-2.ci.openshift.org`). Never leave Helm on
`apps.example.com`.

If the user did not supply a kubeconfig, API URL, or working `oc` session,
**stop and ask** for a console URL of this shape:

`https://console-openshift-console.apps.ci-ln-ibvnlsb-72292.gcp-2.ci.openshift.org/`

```bash
python3 "${SKILL_DIR}/scripts/cluster_from_console.py" "${CONSOLE_URL}"
```

Remind them how to mint a token (existing OAuth display page):

1. Open `tokenDisplayUrl` from the script (`https://oauth-openshift.${CLUSTER_ROUTER_BASE}/oauth/token/display`).
2. Display token; paste it once. Do not echo it in plans or logs.
3. `oc login --token=… --server="${apiServer}"`

## The chain (same namespace)

Three checks, one Helm release / one Backstage CR:

1. **Install previous GA** — published chart or OperatorHub `fast`. Verify.
2. **Upgrade to this RC** — Quay `*-CI` chart or IIB. Verify.
3. **Higher-stream** — only when this RC is **not** already the newest stream:
   upgrade to the **latest published GA of the next minor** (for example `1.10.z`,
   not a skip to 2.0). Verify.

Examples:

- Testing **1.10.4 RC** (newest stream): install `1.10.3` GA, upgrade to `1.10.4`
  RC. Skip step 3.
- Testing **1.9.9 RC** (older stream): install `1.9.8` GA, upgrade to `1.9.9` RC,
  then upgrade to latest `1.10.z` GA.

Leave the namespace in place after the chain so it can be inspected.

Operator OLM Subscription is cluster-wide (`rhdh-operator`). Helm and Operator
chains can share a cluster; do not run two Operator CSV targets at once.

Each cluster subagent gets absolute `SKILL_DIR`, `KUBECONFIG`, tags, namespace, and
(Helm only) `CLUSTER_ROUTER_BASE`. The catalog agent gets `CATALOG_REPO` and
`INDEX_IMAGE` only.

## Shared setup

```bash
export KUBECONFIG=/path/to/smoke.kubeconfig
oc whoami

# tags from Slack / Quay / charts.openshift.io — do not guess
PREV_GA=1.10.3
RC_CHART=1.10-NNN-CI
RC_VER=1.10.4
STREAM=1.10
NEXT_GA=            # e.g. 1.10.3 when testing 1.9.9; omit if this stream is newest
NEXT_STREAM=        # e.g. 1.10 when testing 1.9
NS_HELM=rhdh-${STREAM}-helm
NS_OP=rhdh-${STREAM}-op
CLUSTER_ROUTER_BASE=apps.example.cluster
CATALOG_REPO=/path/to/rhdh-plugin-catalog
INDEX_IMAGE=registry.access.redhat.com/rhdh/plugin-catalog-index:${RC_VER}
```

## Guest enablement

Guest is off by default. Apply after every install or upgrade, before verify.

**Helm — `upstream.backstage.appConfig`.** Pass
`"${SKILL_DIR}/assets/helm-values-guest.yaml"` and
`--set global.clusterRouterBase="${CLUSTER_ROUTER_BASE}"` on the install and
every `helm upgrade`. Do not use `--reuse-values` (it pins GA image digests).
Do not `oc create configmap` and do not use `extraAppConfig`.

**Operator — ConfigMap + Backstage CR.** Apply once; it survives CSV upgrades.

```bash
oc -n "${NS_OP}" create configmap app-config-guest \
  --from-file=app-config-guest.yaml="${SKILL_DIR}/assets/app-config-guest.yaml" \
  --dry-run=client -o yaml | oc apply -f -
CR_NAME=$(oc -n "${NS_OP}" get backstage -o jsonpath='{.items[0].metadata.name}')
oc -n "${NS_OP}" patch backstage "${CR_NAME}" --type merge -p \
  '{"spec":{"application":{"appConfig":{"configMaps":[{"name":"app-config-guest"}]}}}}'
```

## Verify

`scripts/verify_ns.py --namespace "${NS}"` after Guest. Fail on
`ImagePullBackOff`, `CrashLoopBackOff`, `OOMKilled`, or 401/403 in
`install-dynamic-plugins`. 504 right after install = still starting.

Report `Total items` from `/api/extensions/packages` (`totalItems`, not a JSON
array). Fail when the catalog is empty or Guest is missing. A populated catalog
under 100 is not a failure; pass `--min-packages` only when you expect a larger
catalog.

UI: Administration → Extensions → Catalog must not be empty.

## Live lines

After the catalog script, print one line (prefix `Catalog:`). When the script
reports failures, keep its **Could not pull** table in the transcript. Do not
expect a passing table unless the script was run with `--debug` (passing table
precedes failures in that mode). After each install or upgrade + verify, print
one line (prefix `Helm:` or `Operator:`). Use real tags.

- `Catalog: inspected N unique refs from plugin-catalog-index:1.10.4`
- `Helm: deployed older version 1.10.3`
- `Helm: deployed latest CI version 1.10.4 RC`
- `Helm: deployed next-minor GA 1.10.3`
- Same shapes with `Operator:` (CSV/channel when that is what was installed)

Failure: same sentence, then `FAILED` and the reason. Skip:
`Helm: skipped next-minor (this stream is newest)`.

## Gotchas

- Empty Operator CatalogSource: wait for a new IIB; do not proceed.
- GA images must be `registry.redhat.io/rhdh/…`. Quay `*-CI` after a "GA" step
  means the install is still on RC tags.
- Helm Guest via `extraAppConfig` fights the chart-generated `appConfig`.
- Helm `--reuse-values` keeps GA image digests on an RC upgrade.
- Catalog UI warning `spec.backstage` additionalProperty `author` is not
  `packages-low`.
- Index field is `registryReference`, not `oci://…!package`. Inspect as written.
- `checkIndexUpToDate.sh` (git vs latest tags) is not this smoke.
- Catalog script prints failure tables only by default; `--debug` adds passing refs.
- `tree` is human debug only; the catalog script does not require it.

## Completion

After catalog and both cluster agents finish, print this table (Status first,
fixed-width column). **Seven** rows; catalog is **row 1**. Higher-stream stays
`⚠️ skip` when this stream is newest. Do not drop a row. Substitute real
versions. Failed: `❌ fail` and put the reason after the test name in column two.

```
| Status     | Smoke Test |
|:-----------|:-----------|
| ✅ pass | Inspect catalog-index OCI refs registry.access.redhat.com/rhdh/plugin-catalog-index:1.10.4 |
| ✅ pass | Install Helm Previous GA 1.10.3 |
| ✅ pass | Upgrade Helm RC 1.10-170-CI |
| ⚠️ skip | Upgrade Helm higher-stream |
| ✅ pass | Install Operator Previous GA 1.10.3 |
| ✅ pass | Install Operator RC v1.10.4 |
| ⚠️ skip | Upgrade Operator higher-stream |
```

If Markdown collapses padding, use HTML `<colgroup><col style="width:11em"><col></colgroup>`.

Name the Guest method under the table (Helm `appConfig` vs Operator ConfigMap),
not as an eighth row. A step that never ran because an earlier write was refused
is skipped, not omitted.
