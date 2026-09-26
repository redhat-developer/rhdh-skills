# CI Monitoring and Auto-Merge

Monitors GitHub Actions checks on PRs and auto-merges when all green.

## Monitor CI Function

```bash
monitor_ci_and_merge() {
  local PR_NUM=$1
  local REPO=${2:-"redhat-developer/rhdh-plugins"}  # optional repo, defaults to rhdh-plugins
  local MAX_WAIT=3600  # 60 minutes — some checks like ci/prow/e2e-ocp-helm take 30+ min
  local ELAPSED=0
  
  echo "⏳ Monitoring CI on PR #$PR_NUM ($REPO)..."
  
  while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Get check status
    STATUS=$(gh pr view $PR_NUM \
      --repo $REPO \
      --json statusCheckRollup \
      --jq '.statusCheckRollup')
    
    # Count checks by conclusion
    TOTAL=$(echo "$STATUS" | jq 'length')
    SUCCESS=$(echo "$STATUS" | jq '[.[] | select(.conclusion == "SUCCESS")] | length')
    FAILURE=$(echo "$STATUS" | jq '[.[] | select(.conclusion == "FAILURE")] | length')
    PENDING=$(echo "$STATUS" | jq '[.[] | select(.conclusion == null or .conclusion == "PENDING")] | length')
    
    echo "   Checks: $SUCCESS/$TOTAL passed, $PENDING pending, $FAILURE failed"
    
    # Show names of pending checks (helps user see what's slow)
    if [ $PENDING -gt 0 ]; then
      echo "   Pending:"
      echo "$STATUS" | jq -r '.[] | select(.conclusion == null or .conclusion == "PENDING") | "     - \(.name)"'
    fi
    
    # Check for failures
    if [ $FAILURE -gt 0 ]; then
      echo ""
      echo "❌ CI failed on PR #$PR_NUM"
      echo ""
      echo "Failed checks:"
      echo "$STATUS" | jq -r '.[] | select(.conclusion == "FAILURE") | "  - \(.name): \(.detailsUrl)"'
      echo ""
      echo "Fix the failures and retry backport"
      exit 1
    fi
    
    # Check if all complete and successful
    if [ $PENDING -eq 0 ] && [ $SUCCESS -eq $TOTAL ]; then
      echo ""
      echo "✅ All checks passed!"
      
      # Auto-merge
      merge_pr $PR_NUM $REPO
      return 0
    fi
    
    # Wait and retry
    sleep 30
    ELAPSED=$((ELAPSED + 30))
  done
  
  # Timeout
  echo ""
  echo "❌ Timeout waiting for CI (${MAX_WAIT}s exceeded)"
  echo "PR: #$PR_NUM still has pending checks"
  echo ""
  echo "Pending checks:"
  echo "$STATUS" | jq -r '.[] | select(.conclusion == null or .conclusion == "PENDING") | "  - \(.name)"'
  echo ""
  echo "Options:"
  echo "  1. Check PR manually: https://github.com/$REPO/pull/$PR_NUM"
  echo "  2. Resume after CI completes: /backport-continue $RELEASE $PR_NUM"
  exit 1
}
```

## Merge PR Function

```bash
merge_pr() {
  local PR_NUM=$1
  local REPO=${2:-"redhat-developer/rhdh-plugins"}
  
  echo "🔀 Merging PR #$PR_NUM ($REPO)..."
  
  # Use auto-merge (queues for merge when ready)
  gh pr merge $PR_NUM \
    --repo $REPO \
    --squash \
    --auto
  
  if [ $? -eq 0 ]; then
    echo "✅ Merge queued for PR #$PR_NUM"
  else
    echo "❌ Failed to merge PR #$PR_NUM"
    echo "Check merge requirements manually"
    exit 1
  fi
}
```

## Wait for PR Merged Function

```bash
wait_for_pr_merged() {
  local PR_NUM=$1
  local MAX_WAIT=300  # 5 minutes
  local ELAPSED=0
  
  echo "⏳ Waiting for PR #$PR_NUM to fully merge..."
  
  while [ $ELAPSED -lt $MAX_WAIT ]; do
    STATE=$(gh pr view $PR_NUM \
      --repo redhat-developer/rhdh-plugins \
      --json state \
      --jq '.state')
    
    if [ "$STATE" == "MERGED" ]; then
      echo "✅ PR #$PR_NUM merged"
      return 0
    fi
    
    sleep 10
    ELAPSED=$((ELAPSED + 10))
  done
  
  echo "❌ Timeout waiting for merge"
  exit 1
}
```

## Check Status Options

GitHub check conclusions:
- `SUCCESS` - Check passed
- `FAILURE` - Check failed
- `NEUTRAL` - Check completed but no pass/fail
- `CANCELLED` - Check was cancelled
- `SKIPPED` - Check was skipped
- `TIMED_OUT` - Check timed out
- `ACTION_REQUIRED` - Manual action needed
- `null` or `PENDING` - Still running

## Error Scenarios

**CI fails:**
```
❌ CI failed on PR #3500

Failed checks:
  - TypeScript: https://github.com/.../actions/runs/123
  - Lint: https://github.com/.../actions/runs/124

Fix the failures and retry backport
```

**Timeout waiting:**
```
❌ Timeout waiting for CI (1800s exceeded)
PR: #3500 still has pending checks

Options:
  1. Check PR manually: https://github.com/.../pull/3500
  2. Resume after CI completes: /backport-continue 1.10 3456
```

**Merge conflict (GitHub prevents merge):**
```
❌ Failed to merge PR #3500
Merge requirements not met:
  - Requires: 1 approving review
  - Has: 0 reviews

Approve the PR and retry
```

## Handling Protected Branches

If branch protection requires reviews:

```bash
# Check merge requirements
MERGEABLE=$(gh pr view $PR_NUM --json mergeable --jq '.mergeable')

if [ "$MERGEABLE" != "MERGEABLE" ]; then
  echo "⚠️ PR not auto-mergeable"
  echo "Reason: Branch protection requirements"
  echo ""
  echo "Check requirements:"
  gh pr view $PR_NUM --json reviewDecision,statusCheckRollup
  echo ""
  echo "Manual approval may be needed"
  exit 1
fi
```

## CI Check Names (Common)

Typical checks in rhdh-plugins:
- `build`
- `test`
- `lint`
- `type-check`
- `prettier`
- `verify-changesets`
- `verify-repository`
- `e2e` (if applicable)

Typical checks in rhdh-plugin-export-overlays (can be slow):
- `ci/prow/e2e-ocp-helm` — **can take 30+ minutes**
- `ci/prow/images`
- `/publish` validation (triggered by comment, not automatic)
- Other Prow-based checks

All must pass for auto-merge. The 60-minute timeout accounts for slow Prow checks.
