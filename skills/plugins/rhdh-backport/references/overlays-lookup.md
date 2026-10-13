# Overlays Repository Lookup

How to read baseline commit from the overlays repository for workspace reset.

## Repository Structure

```
rhdh-plugin-export-overlays/
├── .github/
├── workspaces/
│   ├── orchestrator/
│   │   ├── source.json          ← Read repo-ref from here
│   │   ├── plugins-list.yaml
│   │   └── ...
│   ├── lightspeed/
│   │   ├── source.json
│   │   └── ...
│   └── topology/
│       ├── source.json
│       └── ...
└── README.md
```

## Branch Structure

Overlays uses release branches that match RHDH releases:

```
Branches:
  main                    → Development
  release-1.9             → RHDH 1.9 releases
  release-1.10            → RHDH 1.10 releases
  release-1.11            → RHDH 1.11 releases
```

**CRITICAL:** Always use the release branch matching your backport target!

```bash
Backporting to 1.10 → Use overlays release-1.10 branch
Backporting to 1.9  → Use overlays release-1.9 branch
```

## source.json Format

```json
{
  "repo": "https://github.com/redhat-developer/rhdh-plugins",
  "repo-ref": "abc123def456...",
  "backstage-version": "1.35.0",
  "skip-packages": []
}
```

**Key field:**
- `repo-ref`: Git commit SHA of the last published version for this release

## Lookup Process

```bash
lookup_overlays_baseline() {
  local PLUGIN=$1
  local RELEASE=$2
  
  echo "📍 Looking up overlays baseline for $PLUGIN @ $RELEASE"
  
  # Clone overlays (or use cached copy)
  OVERLAYS_DIR="/tmp/overlays-${RELEASE}"
  OVERLAYS_REPO="rhdh-plugin-export-overlays"
  OVERLAYS_BRANCH="release-${RELEASE}"
  
  if [ ! -d "$OVERLAYS_DIR" ]; then
    gh repo clone redhat-developer/$OVERLAYS_REPO "$OVERLAYS_DIR"
  fi
  
  cd "$OVERLAYS_DIR"
  git fetch origin
  git checkout "$OVERLAYS_BRANCH"
  git pull origin "$OVERLAYS_BRANCH"
  
  # Read source.json
  SOURCE_FILE="workspaces/${PLUGIN}/source.json"
  
  if [ ! -f "$SOURCE_FILE" ]; then
    echo "❌ Error: $SOURCE_FILE not found"
    echo ""
    echo "Possible reasons:"
    echo "  1. Plugin not published in release-${RELEASE}"
    echo "  2. Wrong plugin name"
    echo "  3. Overlays branch doesn't exist"
    echo ""
    echo "Check: https://github.com/redhat-developer/$OVERLAYS_REPO/tree/$OVERLAYS_BRANCH/workspaces"
    return 1
  fi
  
  # Extract repo-ref
  BASELINE_COMMIT=$(jq -r '.["repo-ref"]' "$SOURCE_FILE")
  
  if [ -z "$BASELINE_COMMIT" ] || [ "$BASELINE_COMMIT" == "null" ]; then
    echo "❌ Error: repo-ref not found in $SOURCE_FILE"
    return 1
  fi
  
  echo "✅ Baseline commit: $BASELINE_COMMIT"
  echo "   From: overlays/$OVERLAYS_BRANCH/$SOURCE_FILE"
  
  # Store for later
  export BASELINE_COMMIT
  
  return 0
}
```

## Why This Matters

The `repo-ref` commit represents:
- ✅ The last Version Packages commit for this release
- ✅ The exact state that was published to npm
- ✅ The correct baseline for cherry-picking new changes

**Without resetting to this commit:**
- ❌ Workspace branch contains changes from main
- ❌ Cherry-pick will conflict with commits that don't belong in the release
- ❌ Version numbers will be wrong

## Example Lookup

```bash
$ lookup_overlays_baseline "orchestrator" "1.10"

📍 Looking up overlays baseline for orchestrator @ 1.10
Cloning into '/tmp/overlays-1.10'...
✅ Cloned overlays repository

Switched to branch 'release-1.10'
✅ Checked out release-1.10

Reading: workspaces/orchestrator/source.json
{
  "repo": "https://github.com/redhat-developer/rhdh-plugins",
  "repo-ref": "xyz789abc123def456...",
  "backstage-version": "1.35.0"
}

✅ Baseline commit: xyz789abc123def456
   From: overlays/release-1.10/workspaces/orchestrator/source.json
```

## Validation

After extracting commit:

```bash
validate_baseline_commit() {
  local COMMIT=$1
  
  # Check commit exists in rhdh-plugins
  cd ~/rhdh-plugins  # or actual repo path
  git fetch upstream
  
  if ! git cat-file -t $COMMIT &>/dev/null; then
    echo "❌ Error: Baseline commit not found: $COMMIT"
    echo ""
    echo "Overlays source.json may be outdated or incorrect"
    echo "Check overlays repository manually"
    return 1
  fi
  
  # Check commit is in correct branch
  if ! git branch -r --contains $COMMIT | grep -q "upstream/workspace/$PLUGIN"; then
    echo "⚠️ Warning: Baseline commit not in workspace/$PLUGIN"
    echo "This may indicate source.json is outdated"
  fi
  
  echo "✅ Baseline commit validated"
  return 0
}
```

## Common Errors

**Plugin not in overlays:**
```
❌ Error: workspaces/orchestrator/source.json not found

Possible reasons:
  1. Plugin not published in release-1.10
  2. Wrong plugin name
  3. Overlays branch doesn't exist

Check: https://github.com/redhat-developer/rhdh-plugin-export-overlays/tree/release-1.10/workspaces
```

**Wrong branch:**
```
❌ Error: Branch release-1.10 not found

Available branches:
  - release-1.8
  - release-1.9

Release 1.10 may not exist yet
```

**Commit not found:**
```
❌ Error: Baseline commit not found: abc123

Overlays source.json may be outdated or incorrect
Fetch latest from upstream: git fetch upstream
```

## Caching Strategy

To avoid repeated clones:

```bash
# Cache overlays per release
CACHE_DIR="$HOME/.cache/rhdh-overlays"
OVERLAYS_DIR="$CACHE_DIR/release-${RELEASE}"

if [ -d "$OVERLAYS_DIR" ]; then
  # Update existing cache
  cd "$OVERLAYS_DIR"
  git fetch origin
  git checkout "$OVERLAYS_BRANCH"
  git reset --hard origin/"$OVERLAYS_BRANCH"
else
  # Clone fresh
  mkdir -p "$CACHE_DIR"
  gh repo clone redhat-developer/$OVERLAYS_REPO "$OVERLAYS_DIR"
fi
```
