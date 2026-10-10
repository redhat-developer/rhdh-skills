# Plugin Detection from PR Files

Auto-detect plugin name from changed files in the PR.

## File Path Structure

RHDH plugin file paths follow this pattern:

```
workspaces/{PLUGIN}/plugins/{PLUGIN}/...
workspaces/{PLUGIN}/packages/...
workspaces/{PLUGIN}/.changeset/...
```

Examples:
```
workspaces/orchestrator/plugins/orchestrator/src/api.ts        → orchestrator
workspaces/lightspeed/plugins/lightspeed/package.json          → lightspeed
workspaces/topology/plugins/topology/src/components/Graph.tsx  → topology
```

## Detection Logic

```bash
detect_plugin_from_files() {
  local PR_NUM=$1
  
  echo "🔍 Detecting plugin from PR #$PR_NUM files..."
  
  # Get all changed files
  FILES=$(gh pr view $PR_NUM \
    --repo redhat-developer/rhdh-plugins \
    --json files \
    --jq '.files[].path')
  
  if [ -z "$FILES" ]; then
    echo "❌ Error: No files found in PR #$PR_NUM"
    return 1
  fi
  
  # Extract plugins from all files
  PLUGINS=()
  
  while IFS= read -r FILE; do
    # Skip non-workspace files
    if [[ ! "$FILE" =~ ^workspaces/ ]]; then
      continue
    fi
    
    # Extract plugin name (second path segment)
    FILE_PLUGIN=$(echo "$FILE" | cut -d'/' -f2)
    
    # Add to array if not already present
    if [[ ! " ${PLUGINS[@]} " =~ " ${FILE_PLUGIN} " ]]; then
      PLUGINS+=("$FILE_PLUGIN")
    fi
  done <<< "$FILES"
  
  # Validate results
  if [ ${#PLUGINS[@]} -eq 0 ]; then
    echo "❌ Error: No workspace files found in PR"
    echo ""
    echo "Files changed:"
    echo "$FILES"
    echo ""
    echo "This PR doesn't touch any plugin workspace"
    return 1
  fi
  
  if [ ${#PLUGINS[@]} -gt 1 ]; then
    echo "❌ Error: PR touches multiple plugins"
    echo ""
    echo "Plugins detected:"
    printf '  - %s\n' "${PLUGINS[@]}"
    echo ""
    echo "Please backport each plugin separately:"
    for P in "${PLUGINS[@]}"; do
      echo "  /backport-auto $RELEASE <commit-for-$P> --plugin $P"
    done
    return 1
  fi
  
  # Single plugin detected
  PLUGIN="${PLUGINS[0]}"
  
  echo "✅ Plugin detected: $PLUGIN"
  echo "   From files: $(echo "$FILES" | grep "^workspaces/$PLUGIN" | wc -l) files"
  
  return 0
}
```

## Edge Cases

### Root-level changes only

If PR only changes root files (CI, docs):

```
Files changed:
  .github/workflows/ci.yml
  README.md
  package.json

❌ Error: No workspace files found in PR
This PR doesn't touch any plugin workspace
```

### Multiple plugins

If PR touches multiple workspaces:

```
❌ Error: PR touches multiple plugins

Plugins detected:
  - orchestrator
  - lightspeed

Please backport each plugin separately:
  /backport-auto 1.10 abc123 --plugin orchestrator
  /backport-auto 1.10 def456 --plugin lightspeed
```

**Solution:** User must manually split the backport by providing specific commits per plugin.

### Mixed workspace and root files

```
Files changed:
  workspaces/orchestrator/plugins/orchestrator/src/api.ts
  .github/workflows/ci.yml
  README.md

✅ Plugin detected: orchestrator
   (Root files are ignored)
```

## Manual Plugin Override

If auto-detection fails or user wants to override:

```bash
# Add --plugin flag support
if [ -n "$PLUGIN_OVERRIDE" ]; then
  PLUGIN="$PLUGIN_OVERRIDE"
  echo "✅ Plugin set manually: $PLUGIN"
else
  detect_plugin_from_files $PR_NUM
fi
```

Usage:
```bash
/backport-auto 1.10 abc123,def456 --plugin orchestrator
```

## Validation

After detection, validate plugin exists:

```bash
validate_plugin() {
  local PLUGIN=$1
  
  # Check workspace directory exists
  if [ ! -d "workspaces/$PLUGIN" ]; then
    echo "❌ Error: Plugin workspace not found: workspaces/$PLUGIN"
    return 1
  fi
  
  # Check release branch exists
  if ! git ls-remote --heads upstream | grep -q "refs/heads/$PLUGIN/release-$RELEASE"; then
    echo "⚠️ Warning: Release branch not found: $PLUGIN/release-$RELEASE"
    echo ""
    read -p "Create release branch? [y/N]: " CREATE
    if [[ "$CREATE" =~ ^[Yy]$ ]]; then
      create_release_branch
    else
      return 1
    fi
  fi
  
  echo "✅ Plugin validated: $PLUGIN"
  return 0
}
```

## Plugin List (Reference)

Common RHDH plugins:
- `orchestrator`
- `lightspeed`
- `topology`
- `notifications`
- `rbac`
- `scaffolder-backend-module-annotations`
- `3scale-backend`
- `aap-backend`
- `acr`
- `ocm-backend`
- `ocm`
- `quay`
- `tekton`

(And many more - detection is dynamic, not hardcoded)

## File Path Patterns to Ignore

These don't indicate plugin:
```
.github/**                    → CI config
docs/**                       → Documentation
scripts/**                    → Build scripts
*.md                          → Markdown files
package.json (root)           → Root package
tsconfig.json (root)          → Root TypeScript config
```

Only consider:
```
workspaces/{plugin}/**        → Plugin files
```
