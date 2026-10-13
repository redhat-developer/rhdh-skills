# PR Detection and Parsing

Parse PR source from user input (number, URL, or commit SHA).

## Input Formats

### PR Number
```bash
Input: "3456"
Output: PR_NUM=3456
```

### PR URL Formats

**Full URL:**
```bash
Input: "https://github.com/redhat-developer/rhdh-plugins/pull/3456"
Regex: https://github.com/[^/]+/[^/]+/pull/(\d+)
Output: PR_NUM=3456
```

**Short URL:**
```bash
Input: "github.com/redhat-developer/rhdh-plugins/pull/3456"
Regex: github.com/[^/]+/[^/]+/pull/(\d+)
Output: PR_NUM=3456
```

**GitHub CLI format:**
```bash
Input: "#3456"
Output: PR_NUM=3456
```

### Commit SHA

**Single commit:**
```bash
Input: "abc123def456"
Output: COMMIT_SHA=abc123def456
```

**Multiple commits (comma-separated):**
```bash
Input: "abc123,def456,ghi789"
Output: COMMITS=(abc123 def456 ghi789)
```

## Parsing Logic

```bash
parse_pr_source() {
  local INPUT=$1
  
  # Try PR number (pure digits)
  if [[ "$INPUT" =~ ^[0-9]+$ ]]; then
    PR_NUM=$INPUT
    return 0
  fi
  
  # Try PR URL
  if [[ "$INPUT" =~ github.com/[^/]+/[^/]+/pull/([0-9]+) ]]; then
    PR_NUM=${BASH_REMATCH[1]}
    return 0
  fi
  
  # Try #3456 format
  if [[ "$INPUT" =~ ^#([0-9]+)$ ]]; then
    PR_NUM=${BASH_REMATCH[1]}
    return 0
  fi
  
  # Try commit SHA (40 hex chars or 7+ short SHA)
  if [[ "$INPUT" =~ ^[a-f0-9]{7,40}$ ]]; then
    COMMIT_SHA=$INPUT
    return 0
  fi
  
  # Try comma-separated commits
  if [[ "$INPUT" =~ ^[a-f0-9]{7,}(,[a-f0-9]{7,})+$ ]]; then
    IFS=',' read -ra COMMITS <<< "$INPUT"
    return 0
  fi
  
  # Invalid format
  echo "❌ Error: Invalid PR source format"
  echo "Expected:"
  echo "  - PR number: 3456"
  echo "  - PR URL: https://github.com/.../pull/3456"
  echo "  - Commit SHA: abc123def"
  echo ""
  echo "Got: $INPUT"
  return 1
}
```

## Fetch PR Details

Once PR_NUM is determined:

```bash
fetch_pr_details() {
  local PR_NUM=$1
  
  echo "📥 Fetching PR #$PR_NUM details..."
  
  # Fetch all needed info in one call
  PR_DATA=$(gh pr view $PR_NUM \
    --repo redhat-developer/rhdh-plugins \
    --json files,mergeCommit,title,url,state,baseRefName,headRefName)
  
  # Extract fields
  PR_TITLE=$(echo "$PR_DATA" | jq -r '.title')
  PR_URL=$(echo "$PR_DATA" | jq -r '.url')
  PR_STATE=$(echo "$PR_DATA" | jq -r '.state')
  MERGE_COMMIT=$(echo "$PR_DATA" | jq -r '.mergeCommit.oid')
  BASE_BRANCH=$(echo "$PR_DATA" | jq -r '.baseRefName')
  FILES=$(echo "$PR_DATA" | jq -r '.files[].path')
  
  # Validate PR is merged
  if [ "$PR_STATE" != "MERGED" ]; then
    echo "❌ Error: PR #$PR_NUM is not merged (state: $PR_STATE)"
    echo "Only merged PRs can be backported"
    return 1
  fi
  
  # Validate PR targeted main
  if [ "$BASE_BRANCH" != "main" ]; then
    echo "⚠️ Warning: PR #$PR_NUM was not merged to main"
    echo "Base branch: $BASE_BRANCH"
    echo ""
    read -p "Continue anyway? [y/N]: " CONTINUE
    if [[ ! "$CONTINUE" =~ ^[Yy]$ ]]; then
      return 1
    fi
  fi
  
  echo "✅ PR details fetched"
  echo "   Title: $PR_TITLE"
  echo "   Merge commit: $MERGE_COMMIT"
  
  return 0
}
```

## Extract Commits from PR

If user provides PR number but wants specific commits from it:

```bash
get_pr_commits() {
  local PR_NUM=$1
  
  # Get all commits from the PR
  COMMITS=$(gh pr view $PR_NUM \
    --repo redhat-developer/rhdh-plugins \
    --json commits \
    --jq '.commits[].oid')
  
  echo "Commits in PR #$PR_NUM:"
  echo "$COMMITS" | nl
  
  # Usually we just want the merge commit
  # But for non-squashed PRs, may need all commits
}
```

## Validation Checks

```bash
validate_pr_source() {
  # Check PR exists
  if ! gh pr view $PR_NUM --repo redhat-developer/rhdh-plugins &>/dev/null; then
    echo "❌ Error: PR #$PR_NUM not found"
    return 1
  fi
  
  # Check PR is merged
  STATE=$(gh pr view $PR_NUM --json state --jq '.state')
  if [ "$STATE" != "MERGED" ]; then
    echo "❌ Error: PR #$PR_NUM is not merged"
    return 1
  fi
  
  # Check commit exists (if commit SHA provided)
  if [ -n "$COMMIT_SHA" ]; then
    if ! git cat-file -t $COMMIT_SHA &>/dev/null; then
      echo "❌ Error: Commit $COMMIT_SHA not found"
      return 1
    fi
  fi
  
  return 0
}
```

## Error Messages

**Invalid format:**
```
❌ Error: Invalid PR source format
Expected:
  - PR number: 3456
  - PR URL: https://github.com/.../pull/3456
  - Commit SHA: abc123def

Got: invalid-input
```

**PR not found:**
```
❌ Error: PR #3456 not found
Check the PR number and try again
```

**PR not merged:**
```
❌ Error: PR #3456 is not merged (state: OPEN)
Only merged PRs can be backported
```

**Commit not found:**
```
❌ Error: Commit abc123 not found
Fetch latest changes or check commit SHA
```
