# Overlays Repository Update

How to update the overlays repository after Version Packages merges.

## Workflow-Based Approach

The overlays repo has a GitHub Actions workflow (`update-plugins-repo-refs.yaml`) that
automates source.json and metadata updates. The backport script triggers this workflow
instead of manually cloning and editing files.

### Workflow: "Update plugins repository references"

- **File:** `.github/workflows/update-plugins-repo-refs.yaml`
- **Trigger:** `workflow_dispatch` with inputs
- **Repo:** `redhat-developer/rhdh-plugin-export-overlays`

**Key inputs:**
| Input | Description |
|-------|-------------|
| `single-branch` | Target branch (e.g. `release-1.10`). If omitted, auto-detects last 2 release branches. |
| `workspace-path` | Specific workspace to update (optional). |
| `verbose` | Enable verbose logging. |
| `force` | Force update even if no changes detected. |

### Triggering from the script

```bash
gh workflow run update-plugins-repo-refs.yaml \
  --repo redhat-developer/rhdh-plugin-export-overlays \
  -f single-branch=release-1.10
```

**Important:** Always specify `single-branch` to target the correct release branch.
Without it, the workflow auto-detects branches and may not update the one you need.

## What the Workflow Does

1. Checks each workspace's `source.json` for the current `repo-ref`
2. Finds the latest commit on the corresponding upstream branch
3. If the commit differs, creates/updates a PR with:
   - Updated `source.json` (new `repo-ref`)
   - Updated metadata YAML files (new versions)
4. Triggers auto-publish via `pr-actions.yaml` with `/publish`

## After the Workflow Runs

The workflow creates a PR (e.g. "Update orchestrator workspace to commit abc123").
The backport script then:

1. Finds the PR by searching for the plugin name in open PRs
2. Adds `/ok-to-test` label
3. Checks if auto-publish fired (the workflow has a built-in auto-publish step)
4. If auto-publish didn't fire, comments `/publish` manually
5. Waits for `/publish` result
6. Waits for all CI checks to pass
7. Merges the PR

## /publish Command Flow

`/publish` triggers image builds and metadata validation. The publish workflow
(`pr-actions.yaml`) runs an export step that:

1. Checks out the source repo at the `repo-ref` commit
2. Applies patches from `workspaces/{plugin}/patches/` (if any)
3. Builds dynamic plugin images
4. Reports success or failure as a PR comment

**Common failure:** If the source code changed and existing patches no longer apply
(e.g. `0-cve-yarn-lock.patch` fails because yarn.lock shifted), the patch must be
re-rolled by the patch maintainer. This is not something the backport script can fix.

## Error Handling

**Workflow not found:**
```
Could not find workflow: update-plugins-repo-refs.yaml
```
Check workflow name and repo access.

**PR not created after workflow:**
The workflow may complete without creating a PR if it determines no update is needed
(e.g. source.json already points to the latest commit). Check the workflow run logs.

**/publish validation failure:**
If `/publish` reports version mismatches or patch failures, the overlays PR needs
manual intervention. The script leaves the PR open and reports the error.

## IMPORTANT: Never merge without /publish

Overlays PRs MUST go through `/publish` before merging. The `/publish` command:
1. Validates metadata versions match actual package versions
2. Triggers image builds
3. Only after success should the PR be merged
