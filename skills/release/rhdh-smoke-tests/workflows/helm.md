# Helm smoke chain

One namespace, one release `redhat-developer-hub`. Each step is **one**
`helm` command: this chart version, Guest `-f`, and
`--set global.clusterRouterBase="${CLUSTER_ROUTER_BASE}"`. Do not pass
`--reuse-values` — that pins GA hub / catalog-index / Lightspeed digests over
the RC chart and forces a second upgrade. Then verify.

`${CLUSTER_ROUTER_BASE}` is the live ingress domain (not `apps.example.com`).
Parent derived it before launching this agent.

```bash
helm repo add openshift-helm-charts https://charts.openshift.io/
helm repo update
NS="${NS_HELM}"
```

Fail the chain if an upgrade rolls back, CrashLoops, or Guest/catalog breaks.

After each verify, print a live line (`Helm: deployed …` or `FAILED`).

## RC (default)

### 1. Install previous GA

```bash
helm install redhat-developer-hub openshift-helm-charts/redhat-developer-hub \
  --version "${PREV_GA}" --namespace "${NS}" --create-namespace \
  -f "${SKILL_DIR}/assets/helm-values-guest.yaml" \
  --set global.clusterRouterBase="${CLUSTER_ROUTER_BASE}"
```

Then verify. Live: `Helm: deployed older version ${PREV_GA}`.

### 2. Upgrade to this RC

```bash
helm upgrade redhat-developer-hub oci://quay.io/rhdh/chart --version "${RC_CHART}" \
  -n "${NS}" \
  -f "${SKILL_DIR}/assets/helm-values-guest.yaml" \
  --set global.clusterRouterBase="${CLUSTER_ROUTER_BASE}"
oc -n "${NS}" rollout status deploy/redhat-developer-hub
```

Then verify. Images may be Quay `*-CI` on this step. Live:
`Helm: deployed latest CI version ${RC_VER} RC` (include `${RC_CHART}`).

### 3. Higher-stream (older branch only)

Skip when this RC is already the newest stream. Target the latest **published**
next-minor GA (`${NEXT_GA}`), not a next-minor CI tag. Live skip:
`Helm: skipped next-minor (this stream is newest)`.

```bash
helm upgrade redhat-developer-hub openshift-helm-charts/redhat-developer-hub \
  --version "${NEXT_GA}" -n "${NS}" \
  -f "${SKILL_DIR}/assets/helm-values-guest.yaml" \
  --set global.clusterRouterBase="${CLUSTER_ROUTER_BASE}"
oc -n "${NS}" rollout status deploy/redhat-developer-hub
```

Then verify. Images must be `registry.redhat.io/rhdh/…`. Live:
`Helm: deployed next-minor GA ${NEXT_GA}`.

## GA run (only if asked)

Same three steps in `${NS_HELM}`. Step 2 uses `--version "${RC_VER}"` from
`openshift-helm-charts/redhat-developer-hub` instead of `oci://quay.io/rhdh/chart`.
Every step must pull `registry.redhat.io/rhdh/…`. Still no `--reuse-values`.
