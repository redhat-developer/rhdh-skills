# Operator smoke chain

One Backstage CR namespace (`${NS_OP}`). OLM Subscription stays in
`rhdh-operator` (cluster-wide). After the CR exists: Guest ConfigMap (SKILL.md),
then verify. Fail if CSV `replaces` cannot resolve or an InstallPlan is `Failed`.
After each verify, print a live line (`Operator: deployed …` or `FAILED`).

Catalog source for an RC CSV:
[install-rhdh-catalog-source.sh](https://github.com/redhat-developer/rhdh-operator/blob/main/.rhdh/scripts/install-rhdh-catalog-source.sh)

CSV upgrades (channel / `startingCSV` / InstallPlan) go through
`scripts/operator_upgrade.py`. Do not hand-roll `oc patch` for those.

```bash
NS="${NS_OP}"
SUB_NS=rhdh-operator
```

## RC (default)

### 1. Install previous GA

OperatorHub channel `fast` (or `fast-${STREAM}`). Then create the CR:

```bash
oc create namespace "${NS}"
cat <<EOF | oc apply -n "${NS}" -f -
apiVersion: rhdh.redhat.com/v1alpha3
kind: Backstage
metadata:
  name: redhat-developer-hub
spec: {}
EOF
```

If the CRD is `v1alpha5`, use that `apiVersion`. Guest + verify. Images:
`registry.redhat.io/rhdh/…`. Live: `Operator: deployed older version ${PREV_GA}`.

### 2. Upgrade to this RC

Install the RC catalog, then switch the **existing** Subscription (same cluster,
same CR):

```bash
curl -sSLO https://raw.githubusercontent.com/redhat-developer/rhdh-operator/main/.rhdh/scripts/install-rhdh-catalog-source.sh
chmod +x install-rhdh-catalog-source.sh
./install-rhdh-catalog-source.sh -v "${STREAM}" --install-operator rhdh
python3 "${SKILL_DIR}/scripts/operator_upgrade.py" \
  --subscription-namespace "${SUB_NS}" \
  --channel "fast-${STREAM}" \
  --starting-csv "${RC_CSV}"
```

`${RC_CSV}` comes from the IIB / `oc get csv` — do not invent it. Then verify
the same CR. Fail if InstallPlan is `Failed`. Live:
`Operator: deployed latest CI version ${RC_VER} RC`.

### 3. Higher-stream (older branch only)

Skip when this RC is already the newest stream. Switch to the next-minor **GA**
channel (latest `1.10.z`, not 2.0). Live skip:
`Operator: skipped next-minor (this stream is newest)`.

```bash
python3 "${SKILL_DIR}/scripts/operator_upgrade.py" \
  --subscription-namespace "${SUB_NS}" \
  --channel "fast-${NEXT_STREAM}" \
  --starting-csv "${NEXT_GA_CSV}"
```

Then verify. Images must be `registry.redhat.io/rhdh/…`. Live:
`Operator: deployed next-minor GA ${NEXT_GA}`.

## GA run (only if asked)

Same CR namespace. Step 1–3 all use OperatorHub `fast` / `fast-1.y` (no IIB).
`fast` ↔ `fast-1.y` is the same `operator_upgrade.py --channel` invocation.
Every step must pull `registry.redhat.io/rhdh/…`.
