# Trigger Nightly ProwJobs

Trigger RHDH nightly ProwJobs via the OpenShift CI Gangway REST API.

Supports two repositories:

- **rhdh** — the main RHDH application (`periodic-ci-redhat-developer-rhdh-*-nightly`)
- **rhdh-plugin-export-overlays** — plugin export overlays (`periodic-ci-redhat-developer-rhdh-plugin-export-overlays-*-nightly`)

Run every command below from this skill's directory.

## Flow

1. Resolve the requested job; fetch available jobs when selection is needed
2. Fill in any requested overrides that are missing values
3. Preview, apply the write gate, execute, and report results

For a supplied full job name and flags, go directly to the preview in Step 3.
For an existing execution ID, use the status command under "Status and recovery".

## Step 1: Fetch Jobs and Select

List configured nightly jobs:

```bash
uv run scripts/trigger_nightly_job.py --list
```

Present the jobs in a table with columns: short name and which branches have it. Derive the short name from the job name part after the branch segment (e.g. `e2e-ocp-helm-nightly` -> "OCP Helm"):

| Repo | Job | main | release-1.9 | release-1.8 |
|------|-----|------|-------------|-------------|
| rhdh | OCP Helm | x | x | x |
| rhdh | AKS Helm | x | x | |
| overlays | OCP Helm | x | | |

Then ask the user to describe which job and branch they want in natural language.

### Natural Language Mapping

Map the user's description to the matching full job name from the fetched list. If no branch is mentioned, default to `main`:

**RHDH repo jobs:**

- "ocp helm" / "openshift helm" -> `e2e-ocp-helm-nightly` (not upgrade, not versioned)
- "operator" / "ocp operator" -> `e2e-ocp-operator-nightly` (not auth-providers)
- "helm upgrade" / "upgrade test" -> `e2e-ocp-helm-upgrade-nightly`
- "auth providers" / "authentication" -> `e2e-ocp-operator-auth-providers-nightly`
- "4.17", "4.19", "4.20", "4.21" -> `e2e-ocp-v4-{VERSION}-helm-nightly`
- "aks helm" / "azure helm" -> `e2e-aks-helm-nightly`
- "aks operator" / "azure operator" -> `e2e-aks-operator-nightly`
- "eks helm" / "aws helm" -> `e2e-eks-helm-nightly`
- "eks operator" / "aws operator" -> `e2e-eks-operator-nightly`
- "gke helm" / "google helm" -> `e2e-gke-helm-nightly`
- "gke operator" / "google operator" -> `e2e-gke-operator-nightly`
- "osd" / "osd gcp" -> `e2e-osd-gcp-helm-nightly` or `e2e-osd-gcp-operator-nightly`
- Branch: "1.9", "release 1.9", "1.8 branch" -> match from that branch
- Multiple: "all AKS jobs", "all Operator jobs on main" -> offer to trigger them in sequence

**Overlay repo jobs:**

- "overlay nightly" / "overlay helm" / "overlays nightly" -> `periodic-ci-redhat-developer-rhdh-plugin-export-overlays-main-e2e-ocp-helm-nightly`

### Shared Cluster Constraint (GKE / OSD-GCP only)

GKE and OSD-GCP each share a single cluster — never run two jobs on the same platform simultaneously. Before triggering, warn the user.

## Step 2: Options

### Overlay repo jobs

Overlay jobs support fork overrides (`--org`, `--repo`, `--branch`), catalog index override (`--catalog-index-image`), and Playwright version override (`--playwright-version`).

Image overrides (`--image-registry`, `--image-repo`, `--tag`), `--chart-version`, and `--send-alerts` are NOT supported — the script will error if these are passed for an overlay job.

If the user doesn't need any overrides, skip this step and go directly to Step 3.

### RHDH repo jobs

Present all options together. The user picks by number — multiple selections allowed (e.g. "2, 5"):

**Image override:**

1. **Default image** — no image flags, use whatever the job is configured with
2. **Custom tag only** — override just the tag, keep default registry and repo
3. **Custom repo + tag** — override image repository and tag, keep default registry (`quay.io`)
4. **Fully custom image** — override registry, repo, and tag

**Catalog & chart override:**
5. **Catalog index image** — override the plugin catalog index image (`--catalog-index-image`)
6. **Chart version** — override the Helm chart version (`--chart-version`)

**Additional options:**
7. **Fork override** — run against a fork instead of `redhat-developer/rhdh`
8. **Send Slack alerts** — notify via `--send-alerts`

Constraint: `--image-repo` requires `--tag`, but `--tag` works on its own. `--playwright-version` is overlay-only and will error for RHDH jobs.

### Follow-up based on selections

**If 2 or 3 selected (quay.io registry)** — fetch available tags and present as numbered options. For `release-*` branches, derive `--tag-filter` by stripping the `release-` prefix. For `main`, omit `--tag-filter` to show all available versions:

```bash
# For release-1.10 branch:
uv run scripts/trigger_nightly_job.py --list-tags --tag-filter 1.10

# For main branch (show all versions):
uv run scripts/trigger_nightly_job.py --list-tags
```

Use `--image-repo <REPO>` to query a different image repository (default: `rhdh/rhdh-hub-rhel9`). Present the numbered results with a final option to enter a custom tag (e.g. `next`, `latest`). For option 3, also ask for the image repository.

**If 4 selected (non-quay registry)** — ask for all three values (tag fetching not available):

- Registry (e.g. `brew.registry.redhat.io`)
- Image repo (e.g. `rhdh/rhdh-hub-rhel9`)
- Tag (e.g. `1.9`)

**If 5 selected** — ask for catalog index image (e.g. `quay.io/rhdh/plugin-catalog-index:1.9-60` for RC, `registry.access.redhat.com/rhdh/plugin-catalog-index:1.9.4` for GA).

**If 6 selected** — ask for chart version (e.g. `1.9-227-CI`).

**If 7 selected** — ask for:

- GitHub org (`--org`): e.g. `my-github-user`
- Repo name (`--repo`): e.g. `rhdh`
- Branch (`--branch`): e.g. `my-feature-branch`

## Step 3: Plan, approve, and execute

Run this command with `--dry-run` first. Use the printed execution command and
request details in the write gate described in `../SKILL.md`. Supplement the
resource impact and abort guidance with any known platform-specific details.

```bash
uv run scripts/trigger_nightly_job.py \
  --job <FULL_JOB_NAME> \
  [--image-registry <REGISTRY>] \
  [--image-repo <REPO>] \
  [--tag <TAG>] \
  [--catalog-index-image <IMAGE>] \
  [--chart-version <VERSION>] \
  [--playwright-version <VERSION>] \
  [--org <ORG>] \
  [--repo <REPO>] \
  [--branch <BRANCH>] \
  [--send-alerts] \
  [--dry-run]
```

After approval, run the preview's `execution_command`. If parameters change,
generate a new preview before submitting.

After execution, show the API response and any returned URL or ID. If both are
missing, report that verification is incomplete.

### Status and recovery

To refresh an existing execution, use the GET-only status command:

```bash
uv run scripts/trigger_nightly_job.py --status <EXECUTION_ID>
```

The CLI also prints this command after submission. Repeating a trigger creates
another ProwJob; use `--status` for follow-up, including when URL polling fails.
Status cannot be combined with `--job`, `--dry-run`, or trigger overrides.

Preserve the adapter's error diagnosis. Authentication failures name the setup
route; permission failures require access review. An invalid request, unknown
execution, rate limit, service failure, or network failure has its own guidance.
Do not reinterpret every API failure as an invalid job name.

Creation is not idempotent. If a POST times out, receives a server error, or
returns an unreadable response, the job may already exist. Inspect the named
job's Prow history before another submission; if an execution ID is known, use
`--status`. Report status lookup failures separately from submission failures.

Use the preview's abort guidance when stopping a submitted run is requested.
Stopping the client does not cancel the ProwJob, and this CLI has no cancel
operation. An OpenShift CI administrator needs the execution ID or URL to abort
the run and check resource cleanup.

### RC Verification Example

```bash
uv run scripts/trigger_nightly_job.py \
  --job periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly \
  --image-repo rhdh/rhdh-hub-rhel9 --tag 1.9-227 \
  --catalog-index-image quay.io/rhdh/plugin-catalog-index:1.9 \
  --chart-version 1.9-227-CI
```

### GA Verification Example

```bash
uv run scripts/trigger_nightly_job.py \
  --job periodic-ci-redhat-developer-rhdh-main-e2e-ocp-helm-nightly \
  --image-registry registry.redhat.io --image-repo rhdh/rhdh-hub-rhel9 --tag 1.9.4 \
  --catalog-index-image registry.access.redhat.com/rhdh/plugin-catalog-index:1.9.4
```

## Reference

- Script flags: `-j/--job`, `-l/--list`, `-T/--list-tags`, `--status`, `--tag-filter`, `-I/--image-registry`, `-q/--image-repo`, `-t/--tag`, `--catalog-index-image`, `--chart-version`, `--playwright-version`, `-o/--org`, `-r/--repo`, `-b/--branch`, `-S/--send-alerts`, `-n/--dry-run`, `--json`
- API behavior: <https://docs.ci.openshift.org/how-tos/triggering-prowjobs-via-rest/>
- Authentication and the adapter boundary: see `../SKILL.md`
- RHDH jobs list: <https://prow.ci.openshift.org/configured-jobs/redhat-developer/rhdh>
- Overlay jobs list: <https://prow.ci.openshift.org/configured-jobs/redhat-developer/rhdh-plugin-export-overlays>
- Image tags: <https://quay.io/repository/rhdh/rhdh-hub-rhel9?tab=tags>

## Related Skills

- **`/rhdh-overlay`**: Manage the rhdh-plugin-export-overlays repository
