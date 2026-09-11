---
name: rhdh-deploy-local-plugin
description: >-
  Build, package, and deploy a local RHDH/BCP plugin as an OCI image to an
  OpenShift cluster for testing. Uses rhdh-cli for export and packaging,
  handles GHCR auth, push, ConfigMap update, and pod rollout. Use when the
  user asks to "test on cluster", "deploy plugin to cluster", "build OCI image",
  "push plugin to GHCR", "verify dynamic plugin on OpenShift",
  "test my changes on cluster", or "deploy local changes".
---

<essential_principles>

<principle name="skill_entry_banner">
As the very first action when the skill is invoked, echo a skill entry banner to the terminal:
```
echo "================ Using Deploy Local Plugin Skill ==========="
```
This must happen before any other work (reading references, gathering inputs, etc.).
</principle>

<principle name="step_echo_banners">
Before executing each numbered Step, echo a clearly visible banner to the terminal so the user can track progress:
```
echo "================ Step N — <Step title> ==========="
```
This applies to ALL steps including Step 0. Run the echo command in the terminal before doing anything else for that step.
</principle>

<principle name="fail_fast">
If any step fails validation, STOP immediately with a clear error message and documentation link. Do NOT proceed to the next step. The user must fix the issue before continuing.
</principle>

<principle name="use_rhdh_cli">
Always use `@red-hat-developer-hub/cli` for export and OCI packaging. The CLI handles:
- Dynamic plugin export (`plugin export` → creates `dist-dynamic/`)
- OCI image creation with correct directory structure (`plugin package --tag`)
- Automatic `io.backstage.dynamic-packages` annotation

Do NOT manually create Containerfiles, generate annotations, or call `podman build` directly.
Docs: https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html/installing_and_viewing_plugins_in_red_hat_developer_hub/assembly-third-party-plugins
</principle>

<principle name="oci_uri_format">
The `dynamic-plugins.yaml` entry format is a plain OCI URI **without** any `!plugin-name` suffix:

**Correct:** `oci://ghcr.io/user/repo/red-hat-developer-hub-backstage-plugin-quickstart:tag`
**Wrong:**  `oci://ghcr.io/user/repo/backstage-plugin-quickstart:tag!red-hat-developer-hub-backstage-plugin-quickstart`

The `plugin package` CLI may print an example with the `!` fragment selector — **ignore it**. The current RHDH format does not use this suffix. The image name in the OCI path must match the official overlay naming convention: `<scope>-<package-name>` (e.g., `@red-hat-developer-hub/backstage-plugin-quickstart` → `red-hat-developer-hub-backstage-plugin-quickstart`).
</principle>

</essential_principles>

## Step 0 — Readiness Check

```
echo "================ Step 0 — Readiness Check ==========="
```

Verify all tools are present. Print a status table using `[PASS]` / `[FAIL]` / `[WARN]` indicators. If any must-have check fails, STOP with install instructions.

### Must-have tools

| Tool | Check command | Install link |
|------|--------------|--------------|
| `podman` | `podman --version` | https://podman.io/docs/installation |
| `oc` | `oc version --client` | https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html |
| `gh` | `gh --version` | https://cli.github.com/manual/installation |
| `npx` | `npx --version` | https://nodejs.org/en/download |
| `yarn` | `yarn --version` | https://yarnpkg.com/getting-started/install |

### Must-have auth checks

| Check | Command | Fix |
|-------|---------|-----|
| gh authenticated | `gh auth status` | `gh auth login` — https://cli.github.com/manual/gh_auth_login |
| `write:packages` scope | `gh auth status 2>&1 \| grep write:packages` | `gh auth refresh -h github.com -s write:packages` — https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic |
| GHCR login | `podman login ghcr.io --get-login` | `gh auth token \| podman login ghcr.io -u $(gh api user -q .login) --password-stdin` |

### Good-to-have (warn only)

| Check | Condition | What it enables | Link |
|-------|-----------|----------------|------|
| Cluster login | `oc whoami` | Deploy directly without re-login | `oc login <url> --username <u> --password <p>` |

### Output format

```
 [PASS]  podman — v5.4.0
 [PASS]  oc — v4.17.0
 [PASS]  gh — v2.70.0
 [PASS]  npx — v10.9.4
 [PASS]  yarn — v4.9.1
 [PASS]  gh auth — authenticated as its-mitesh-kumar
 [PASS]  write:packages — scope present
 [PASS]  GHCR login — active
 [WARN]  oc cluster — not logged in (will need login in Step 4)
```

**If ANY must-have check fails:** Print the fix command, documentation link, and STOP.

---

<intake>

## Step 1 — Gather Inputs

```
echo "================ Step 1 — Gather Inputs ==========="
```

Identify what to deploy. Gather from user or infer from current working directory:

| Variable | How to resolve |
|----------|----------------|
| `WORKSPACE` | Directory name under `workspaces/` (infer from cwd or ask) |
| `PLUGIN` | Directory name under `plugins/` (infer from cwd or ask) |
| `NAMESPACE` | Namespace where RHDH runs on the cluster (ask user) |
| `CLUSTER_API` | Cluster API URL (ask if `oc whoami` fails) |
| `GHCR_USER` | From `gh api user -q .login` |

Derive from plugin's `package.json`:
- `PLUGIN_SHORT` — full image name matching overlay convention: `@scope/name` → `scope-name` (with `-dynamic` suffix stripped)
- `VERSION` — from `version` field
- `TAG` — pattern: `bs_<backstage-version>__<plugin-version>-test`

```bash
GHCR_USER=$(gh api user -q .login)
cd workspaces/${WORKSPACE}/plugins/${PLUGIN}
# Convert scoped name to overlay image name: @red-hat-developer-hub/backstage-plugin-foo → red-hat-developer-hub-backstage-plugin-foo
PLUGIN_SHORT=$(node -p "require('./package.json').name.replace('@','').replace('/','-').replace(/-dynamic$/, '')")
VERSION=$(node -p "require('./package.json').version")
BS_VERSION=$(node -p "require('./package.json').backstage?.supportedVersions || require('../../../backstage.json')?.version || 'unknown'")
TAG="bs_${BS_VERSION}__${VERSION}-test"

echo "  Plugin: ${PLUGIN_SHORT}"
echo "  Version: ${VERSION}"
echo "  Tag: ${TAG}"
echo "  GHCR user: ${GHCR_USER}"
echo "  Image: ghcr.io/${GHCR_USER}/rhdh-plugin-export-overlays/${PLUGIN_SHORT}:${TAG}"
```

**Wait for user response if workspace/namespace are not clear.**

</intake>

---

## Step 2 — Build, Export & Package

```
echo "================ Step 2 — Build, Export & Package ==========="
```

```bash
echo "  Running yarn tsc..."
yarn tsc

echo "  Running yarn build..."
yarn build

echo "  Exporting as dynamic plugin..."
npx @red-hat-developer-hub/cli@latest plugin export

echo "  Packaging as OCI image..."
npx @red-hat-developer-hub/cli@latest plugin package \
  --tag ghcr.io/${GHCR_USER}/rhdh-plugin-export-overlays/${PLUGIN_SHORT}:${TAG}
```

**Validation:** The `plugin package` command should:
1. Print `detected backstage feature:` lines (e.g., `./alpha => @backstage/FrontendPlugin`)
2. Print the `dynamic-plugins.yaml` entry to use on the cluster
3. Exit with code 0

**If `plugin export` fails:** Check `yarn build` output for TypeScript errors. Run `yarn tsc` separately to diagnose.

**If `plugin package` fails:**
- Container tool not found: add `--container-tool docker` or ensure `podman` is on PATH
- Permission denied: check container runtime is running (`podman machine start` on macOS)

---

## Step 3 — Push to GHCR

```
echo "================ Step 3 — Push to GHCR ==========="
```

```bash
podman push ghcr.io/${GHCR_USER}/rhdh-plugin-export-overlays/${PLUGIN_SHORT}:${TAG}
```

**If push fails with `permission_denied`:**
```
 [FAIL]  Push failed — token lacks required scopes
 Fix:
   1. gh auth refresh -h github.com -s write:packages
   2. gh auth token | podman login ghcr.io -u ${GHCR_USER} --password-stdin
   3. Retry the push
 Docs: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
```

**After successful push — ensure GHCR package is public:**

GHCR packages default to **private** on first push. A private image will cause `skopeo inspect` / `unauthorized` errors when the cluster tries to pull it. Make the package public via the GitHub API:

```bash
echo "  Ensuring GHCR package is public..."
gh api --method PATCH /user/packages/container/rhdh-plugin-export-overlays%2F${PLUGIN_SHORT} \
  -f visibility=public 2>&1

if [ $? -eq 0 ]; then
  echo " [PASS]  GHCR package is public"
else
  echo " [FAIL]  Could not set package visibility to public"
  echo " Fix: Go to https://github.com/users/${GHCR_USER}/packages/container/package/rhdh-plugin-export-overlays%2F${PLUGIN_SHORT}"
  echo "       → Package settings → Change visibility → Public"
  echo " Then retry the deploy step."
  exit 1
fi
```

**Validation:** Verify the package is actually public before proceeding to deploy (the `podman pull` check is unreliable here because podman is already authenticated to GHCR):

```bash
VISIBILITY=$(gh api /user/packages/container/rhdh-plugin-export-overlays%2F${PLUGIN_SHORT} -q .visibility 2>/dev/null)
if [ "$VISIBILITY" = "public" ]; then
  echo " [PASS]  Package visibility confirmed: public"
else
  echo " [FAIL]  Package visibility: ${VISIBILITY:-unknown} (expected: public)"
  echo " Fix: https://github.com/users/${GHCR_USER}/packages/container/package/rhdh-plugin-export-overlays%2F${PLUGIN_SHORT}"
  echo "       → Package settings → Change visibility → Public"
  exit 1
fi
```

---

## Step 4 — Deploy to Cluster

```
echo "================ Step 4 — Deploy to Cluster ==========="
```

### 4.1 — Ensure cluster login

```bash
if ! oc whoami &>/dev/null; then
  echo " [FAIL]  Not logged into cluster"
  echo " Fix: oc login ${CLUSTER_API} --username <user> --password <pass> --insecure-skip-tls-verify"
  echo " Docs: https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html#cli-logging-in_cli-developer-commands"
  exit 1
fi
echo " [PASS]  Cluster: $(oc whoami --show-server)"
```

### 4.2 — Update ConfigMap

```bash
oc get configmap dynamic-plugins -n ${NAMESPACE} \
  -o jsonpath='{.data.dynamic-plugins\.yaml}' > /tmp/dynamic-plugins.yaml

# Replace official image with test image
sed -i.bak "s|ghcr.io/redhat-developer/rhdh-plugin-export-overlays/${PLUGIN_SHORT}:[^ '\"]*|ghcr.io/${GHCR_USER}/rhdh-plugin-export-overlays/${PLUGIN_SHORT}:${TAG}|g" /tmp/dynamic-plugins.yaml

oc create configmap dynamic-plugins \
  --from-file=dynamic-plugins.yaml=/tmp/dynamic-plugins.yaml \
  -n ${NAMESPACE} --dry-run=client -o yaml | oc apply -f -

echo "  ConfigMap updated"
```

### 4.3 — Restart pod

```bash
oc delete pod -n ${NAMESPACE} -l app.kubernetes.io/instance=redhat-developer-hub
echo "  Pod deleted, waiting for new pod..."
```

---

## Step 5 — Validate Deployment

```
echo "================ Step 5 — Validate Deployment ==========="
```

```bash
echo "  Waiting for rollout..."
oc rollout status deployment/redhat-developer-hub -n ${NAMESPACE} --timeout=180s

POD=$(oc get pods -n ${NAMESPACE} -l app.kubernetes.io/instance=redhat-developer-hub -o name | head -1)
echo "  Pod: ${POD}"

echo "  Checking init container logs..."
INSTALL_LOG=$(oc logs ${POD} -n ${NAMESPACE} -c install-dynamic-plugins 2>&1 | grep "${PLUGIN_SHORT}")
if echo "$INSTALL_LOG" | grep -q "Installed"; then
  echo " [PASS]  Plugin installed by init container"
else
  echo " [FAIL]  Plugin NOT found in init logs"
  echo "  Detail: ${INSTALL_LOG}"
  echo "  Fix: Check OCI image structure — see references/oci-structure.md"
  exit 1
fi

echo "  Checking for runtime errors..."
ERRORS=$(oc logs ${POD} -n ${NAMESPACE} -c backstage-backend 2>&1 | grep -i "error" | grep "${PLUGIN_SHORT}")
if [ -z "$ERRORS" ]; then
  echo " [PASS]  No runtime errors"
else
  echo " [WARN]  Errors found:"
  echo "  ${ERRORS}"
fi

echo "  Verifying plugin directory..."
FILES=$(oc exec ${POD} -n ${NAMESPACE} -c backstage-backend -- ls /opt/app-root/src/dynamic-plugins-root/${PLUGIN_SHORT}/ 2>&1)
if echo "$FILES" | grep -q "package.json"; then
  echo " [PASS]  Plugin files present (package.json, dist/, dist-scalprum/)"
else
  echo " [FAIL]  Plugin directory empty or missing package.json"
  echo "  Got: ${FILES}"
  exit 1
fi

echo ""
echo "================ DONE ==========="
echo "  Image: ghcr.io/${GHCR_USER}/rhdh-plugin-export-overlays/${PLUGIN_SHORT}:${TAG}"
echo "  Cluster: $(oc whoami --show-server)"
echo "  Namespace: ${NAMESPACE}"
echo "  Pod: ${POD}"
echo ""
echo "  Next: Open the RHDH UI and verify your changes are visible."
echo "  App Visualizer: <rhdh-url>/_visualizer/tree"
```

---

## Rollback

```
echo "================ Rollback — Reverting to official image ==========="
```

```bash
cp /tmp/dynamic-plugins.yaml.bak /tmp/dynamic-plugins.yaml
oc create configmap dynamic-plugins \
  --from-file=dynamic-plugins.yaml=/tmp/dynamic-plugins.yaml \
  -n ${NAMESPACE} --dry-run=client -o yaml | oc apply -f -
oc delete pod -n ${NAMESPACE} -l app.kubernetes.io/instance=redhat-developer-hub
oc rollout status deployment/redhat-developer-hub -n ${NAMESPACE} --timeout=180s
echo " [PASS]  Rolled back to official image"
```

---

## When NOT to Use

- **Plugins already in the overlay CI** — if the plugin is already published via `rhdh-plugin-export-overlays` CI and you just need to bump a version, use the `overlay` skill instead.
- **Local dev testing** — if you only need to test locally with `yarn start`, use `rhdh-local` skill or `packages: all` in `app-config.yaml`.
- **Helm chart changes** — this skill deploys plugin OCI images, not Helm value changes.

---

<reference_index>

## Reference Index

| Reference | Load when... |
|-----------|-------------|
| `references/oci-structure.md` | When debugging image build, annotation issues, or `plugin package` failures |

</reference_index>
