# Version Packages PR Detection

How to detect and validate the auto-generated Version Packages PR.

## What is Version Packages?

Version Packages is a GitHub workflow (changesets bot) that:
- Automatically runs after changes merge to `release-x.y/{plugin}` branches (recommended)
  or legacy `workspace/{plugin}` branches
- Updates version numbers in package.json files
- Generates CHANGELOG.md entries
- Publishes packages to npm with dist-tag `maintenance` after merge

**Prerequisite:** The target `release-x.y/{plugin}` branch must include the #4173
workflow changes. See `workflow-bootstrap.md`.

**PR Title Format:**
```
Version Packages (orchestrator)
Version Packages (lightspeed)
Version Packages (topology)
```

## Two Scenarios After Backport PR Merges

When the backport PR (fork → `release-x.y/{plugin}`) merges, the changesets bot does one of:

### Scenario A: No existing Version Packages PR
The bot **creates a new PR**. The skill must wait for it to appear.

### Scenario B: Version Packages PR already open for this plugin
The bot **updates the existing PR** by adding the new changeset/changelog entry to it. The skill must:
1. Detect the existing PR
2. Wait for the bot to push the update (new commit on the PR branch)
3. Proceed with that PR

## Detection Logic

```bash
detect_version_packages_pr() {
  local PLUGIN=$1
  local RELEASE=$2
  local RELEASE_BRANCH="release-${RELEASE}/${PLUGIN}"
  local MAX_WAIT=300  # 5 minutes
  local ELAPSED=0

  echo "🔍 Detecting Version Packages PR for $PLUGIN on $RELEASE_BRANCH..."

  # First, check if a VP PR already exists (Scenario B)
  VP_PR_NUM=$(gh pr list \
    --repo redhat-developer/rhdh-plugins \
    --base "$RELEASE_BRANCH" \
    --search "Version Packages (${PLUGIN}) in:title" \
    --state open \
    --json number,updatedAt \
    --jq '.[0].number')

  if [ -n "$VP_PR_NUM" ]; then
    echo "📋 Existing Version Packages PR found: #$VP_PR_NUM"
    echo "⏳ Waiting for bot to update it with new changeset..."
    
    # Record current commit on the PR branch to detect the update
    BEFORE_SHA=$(gh pr view $VP_PR_NUM \
      --repo redhat-developer/rhdh-plugins \
      --json headRefOid --jq '.headRefOid')
    
    while [ $ELAPSED -lt $MAX_WAIT ]; do
      CURRENT_SHA=$(gh pr view $VP_PR_NUM \
        --repo redhat-developer/rhdh-plugins \
        --json headRefOid --jq '.headRefOid')
      
      if [ "$CURRENT_SHA" != "$BEFORE_SHA" ]; then
        echo "✅ Version Packages PR #$VP_PR_NUM updated with new changeset"
        return 0
      fi
      
      echo "⏳ Waiting for update... (${ELAPSED}s)"
      sleep 10
      ELAPSED=$((ELAPSED + 10))
    done
    
    echo "⚠️ VP PR #$VP_PR_NUM exists but was not updated within ${MAX_WAIT}s"
    echo "   The bot may still be processing. Check the PR manually."
    echo "   PR: https://github.com/redhat-developer/rhdh-plugins/pull/$VP_PR_NUM"
    return 0  # Continue with existing PR anyway
  fi

  # Scenario A: No existing VP PR — wait for creation
  echo "⏳ No existing Version Packages PR. Waiting for bot to create one..."
  
  while [ -z "$VP_PR_NUM" ] && [ $ELAPSED -lt $MAX_WAIT ]; do
    VP_PR_NUM=$(gh pr list \
      --repo redhat-developer/rhdh-plugins \
      --base "$RELEASE_BRANCH" \
      --search "Version Packages (${PLUGIN}) in:title" \
      --state open \
      --json number \
      --jq '.[0].number')
    
    if [ -z "$VP_PR_NUM" ]; then
      echo "⏳ Waiting for Version Packages PR... (${ELAPSED}s)"
      sleep 10
      ELAPSED=$((ELAPSED + 10))
    fi
  done
  
  if [ -z "$VP_PR_NUM" ]; then
    echo "❌ Error: Version Packages PR not created after ${MAX_WAIT}s"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check if workflow triggered:"
    echo "     https://github.com/redhat-developer/rhdh-plugins/actions"
    echo ""
    echo "  2. Check if #4173 workflow is on the release branch (see workflow-bootstrap.md)"
    echo "  3. Check if PR already exists:"
    echo "     gh pr list --base $RELEASE_BRANCH --state all"
    echo ""
    echo "  3. Check workflow logs for errors"
    return 1
  fi
  
  echo "✅ Version Packages PR detected: #$VP_PR_NUM"
  
  return 0
}
```

## Validation

After detection, validate the PR:

```bash
validate_version_packages_pr() {
  local VP_PR_NUM=$1
  local PLUGIN=$2
  local RELEASE_BRANCH=$3
  
  echo "🔍 Validating Version Packages PR #$VP_PR_NUM..."
  
  # Get PR details
  VP_DATA=$(gh pr view $VP_PR_NUM \
    --repo redhat-developer/rhdh-plugins \
    --json title,baseRefName,headRefName,author,labels)
  
  VP_TITLE=$(echo "$VP_DATA" | jq -r '.title')
  VP_BASE=$(echo "$VP_DATA" | jq -r '.baseRefName')
  VP_HEAD=$(echo "$VP_DATA" | jq -r '.headRefName')
  VP_AUTHOR=$(echo "$VP_DATA" | jq -r '.author.login')
  
  # Validate title
  if [[ ! "$VP_TITLE" =~ ^Version\ Packages\ \(${PLUGIN}\)$ ]]; then
    echo "⚠️ Warning: PR title doesn't match expected pattern"
    echo "   Expected: Version Packages ($PLUGIN)"
    echo "   Got: $VP_TITLE"
  fi
  
  # Validate base branch
  if [ "$VP_BASE" != "$RELEASE_BRANCH" ]; then
    echo "❌ Error: Version Packages PR has wrong base branch"
    echo "   Expected: $RELEASE_BRANCH"
    echo "   Got: $VP_BASE"
    return 1
  fi
  
  # Validate head branch pattern
  if [[ ! "$VP_HEAD" =~ ^changeset-release/ ]]; then
    echo "⚠️ Warning: Head branch doesn't match expected pattern"
    echo "   Expected: changeset-release/*"
    echo "   Got: $VP_HEAD"
  fi
  
  # Validate author (should be bot)
  if [[ ! "$VP_AUTHOR" =~ bot$ ]] && [ "$VP_AUTHOR" != "github-actions[bot]" ]; then
    echo "⚠️ Warning: PR author is not a bot"
    echo "   Author: $VP_AUTHOR"
    echo "   Expected: github-actions[bot] or similar"
  fi
  
  echo "✅ Version Packages PR validated"
  
  return 0
}
```

## Why Detection Can Fail

**1. Workflow didn't trigger:**
- Release branch missing #4173 workflow changes (see `workflow-bootstrap.md`)
- Backport PR was created from fork (not upstream) — usually fine; workflow uses target branch file
- Workflow permissions issue
- GitHub Actions disabled

**2. Workflow is slow:**
- High GitHub Actions queue
- Complex changeset calculation
- Many packages to update

**3. No version changes:**
- Changeset not created
- Changes in non-published paths (dev/, tests/)
- Package already at correct version

**4. PR already exists:**
- Previous backport created VP PR
- Manual VP PR created

## Handling Edge Cases

### PR already exists (merged or open)

```bash
# Check for existing VP PR (any state)
EXISTING_VP=$(gh pr list \
  --repo redhat-developer/rhdh-plugins \
  --base "$RELEASE_BRANCH" \
  --search "Version Packages (${PLUGIN}) in:title" \
  --state all \
  --json number,state \
  --jq '.[0]')

VP_STATE=$(echo "$EXISTING_VP" | jq -r '.state')

if [ "$VP_STATE" == "MERGED" ]; then
  echo "✅ Version Packages PR already merged"
  VP_PR_NUM=$(echo "$EXISTING_VP" | jq -r '.number')
  # Get merge commit
  VP_COMMIT=$(gh pr view $VP_PR_NUM --json mergeCommit --jq '.mergeCommit.oid')
  return 0
fi
```

### No changeset needed

If changes don't affect published packages:

```bash
# After 5 minutes with no VP PR
echo "⚠️ No Version Packages PR created"
echo ""
echo "Possible reasons:"
echo "  1. Changeset not included in backport"
echo "  2. Changes only in non-published paths (dev/, tests/)"
echo "  3. Package version already correct"
echo ""
echo "Check release branch manually:"
echo "  git log upstream/release-x.y/$PLUGIN"
echo ""
read -p "Skip Version Packages step? [y/N]: " SKIP

if [[ "$SKIP" =~ ^[Yy]$ ]]; then
  # Continue without VP
  VP_PR_NUM=""
  VP_COMMIT=$(git rev-parse upstream/release-x.y/$PLUGIN)
  return 0
fi
```

## Extract Version Information

From Version Packages PR body:

```bash
extract_version_from_vp_pr() {
  local VP_PR_NUM=$1
  
  # Get PR body
  VP_BODY=$(gh pr view $VP_PR_NUM --json body --jq '.body')
  
  # Extract version (format: @redhat-developer/package@1.2.3)
  VERSION=$(echo "$VP_BODY" | grep -oP '@redhat-developer/[^@]+@\K[\d.]+' | head -1)
  
  if [ -z "$VERSION" ]; then
    echo "⚠️ Could not extract version from VP PR"
    VERSION="unknown"
  fi
  
  echo "📦 Version: $VERSION"
  export VP_VERSION=$VERSION
}
```

## Monitoring VP PR Creation

Real-time monitoring:

```bash
watch_for_vp_pr() {
  local PLUGIN=$1
  local START_TIME=$(date +%s)
  
  echo "⏳ Watching for Version Packages PR creation..."
  echo "   Plugin: $PLUGIN"
  echo "   Started: $(date)"
  echo ""
  
  while true; do
    ELAPSED=$(($(date +%s) - START_TIME))
    
    # Check if PR exists
    VP_PR_NUM=$(gh pr list \
      --repo redhat-developer/rhdh-plugins \
      --base "release-x.y/${PLUGIN}" \
      --search "Version Packages (${PLUGIN}) in:title" \
      --state open \
      --json number \
      --jq '.[0].number')
    
    if [ -n "$VP_PR_NUM" ]; then
      echo ""
      echo "✅ Version Packages PR created: #$VP_PR_NUM"
      echo "   Elapsed: ${ELAPSED}s"
      return 0
    fi
    
    # Show progress
    printf "\r⏳ Waiting... %ds" $ELAPSED
    
    # Timeout after 5 minutes
    if [ $ELAPSED -gt 300 ]; then
      echo ""
      echo "❌ Timeout after 300s"
      return 1
    fi
    
    sleep 10
  done
}
```

## Multiple Version Packages PRs

If multiple VP PRs exist:

```bash
# Get all open VP PRs
VP_PRS=$(gh pr list \
  --repo redhat-developer/rhdh-plugins \
  --base "release-x.y/${PLUGIN}" \
  --search "Version Packages in:title" \
  --state open \
  --json number,title,createdAt)

COUNT=$(echo "$VP_PRS" | jq 'length')

if [ $COUNT -gt 1 ]; then
  echo "⚠️ Multiple Version Packages PRs found:"
  echo "$VP_PRS" | jq -r '.[] | "  #\(.number): \(.title) (created \(.createdAt))"'
  echo ""
  echo "Using most recent: #$(echo "$VP_PRS" | jq -r '.[0].number')"
fi
```

## Workflow Check

Verify workflow is running:

```bash
check_vp_workflow() {
  local PLUGIN=$1
  
  # Get recent workflow runs
  RUNS=$(gh run list \
    --repo redhat-developer/rhdh-plugins \
    --workflow "Version Packages" \
    --limit 5 \
    --json status,conclusion,createdAt,databaseId)
  
  LATEST_RUN=$(echo "$RUNS" | jq -r '.[0]')
  RUN_STATUS=$(echo "$LATEST_RUN" | jq -r '.status')
  
  echo "Latest Version Packages workflow:"
  echo "  Status: $RUN_STATUS"
  
  if [ "$RUN_STATUS" == "in_progress" ]; then
    echo "  ⏳ Workflow is running, PR will be created soon"
  elif [ "$RUN_STATUS" == "completed" ]; then
    echo "  ✅ Workflow completed, check for PR"
  fi
}
```
