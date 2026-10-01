# AI Conflict Resolution

When cherry-pick conflicts occur and user chooses option 1 (AI resolution), follow this logic:

## Resolution Process

### 1. Gather Context

For each conflicting file:

```bash
# Get the conflicting file content (with markers)
CONFLICT_CONTENT=$(cat "$FILE")

# Get commit message (understand intent)
COMMIT_MSG=$(git log -1 --pretty=%B $COMMIT)

# Get the original diff from commit
COMMIT_DIFF=$(git show $COMMIT -- "$FILE")

# Get HEAD version (target branch state)
HEAD_VERSION=$(git show HEAD:"$FILE")
```

### 2. Analyze with AI

Use Read tool to examine the conflict:

**Understand both sides:**
- **HEAD side** (<<<<<<< HEAD): What's in the release branch
- **Incoming side** (>>>>>>> commit): What's being cherry-picked from main

**Determine conflict type:**
- **Version conflict**: package.json version numbers
- **Import conflict**: Different import statements
- **Code conflict**: Logic changes in same location
- **Formatting conflict**: Whitespace/style differences

**Strategy selection:**
- **Simple conflicts** (versions, imports): Auto-resolve with high confidence
- **Logic conflicts**: Merge both changes if compatible
- **Breaking conflicts**: Flag for manual review

### 3. Generate Resolution

Use Edit tool to write the resolved file (remove conflict markers):

**Resolution patterns:**

**package.json version conflict:**
```json
HEAD:     "version": "1.9.0"
INCOMING: "version": "1.10.0"

RESOLVE:  "version": "1.9.0"  // Keep HEAD - Version Packages will update
          + add any new dependencies from INCOMING
```

**Import conflict:**
```typescript
HEAD:     import { A } from './a';
INCOMING: import { A, B } from './a';

RESOLVE:  import { A, B } from './a';  // Merge both
```

**API change conflict:**
```typescript
HEAD:     fetch('/api/v1/data')
INCOMING: fetch('/api/v2/data', options)

RESOLVE:  fetch('/api/v2/data', options)  // Take incoming (upgrade)
```

**Logic merge:**
```typescript
HEAD:     if (condition) { doA(); }
INCOMING: if (condition) { doB(); }

RESOLVE:  if (condition) { 
            doA();  // Keep existing
            doB();  // Add new
          }
```

### 4. Validate Resolution

After writing resolved file:

**TypeScript/JavaScript validation:**
```bash
if [[ "$FILE" == *.ts ]] || [[ "$FILE" == *.tsx ]] || [[ "$FILE" == *.js ]]; then
  npx tsc --noEmit "$FILE" 2>/dev/null
  if [ $? -ne 0 ]; then
    echo "⚠️ Syntax error in AI resolution"
    echo "Falling back to manual resolution"
    return 1
  fi
fi
```

**Check for leftover markers:**
```bash
if grep -E "^<{7}|^={7}|^>{7}" "$FILE"; then
  echo "❌ Conflict markers still present"
  return 1
fi
```

### 5. Apply Resolution

```bash
# Stage the resolved file
git add "$FILE"

echo "✅ Resolved: $FILE"
```

## Confidence Scoring

Rate confidence for each resolution:

**HIGH (auto-apply):**
- Version number conflicts
- Import additions
- Whitespace/formatting
- Comment conflicts

**MEDIUM (show diff, ask approval):**
- Function signature changes
- API endpoint updates
- Simple logic additions

**LOW (require manual):**
- Complex business logic
- State management changes
- Database schemas
- Security code

## Error Handling

If AI resolution fails:

```bash
echo "❌ AI could not resolve: $FILE"
echo "Reason: [Complex logic conflict / Syntax error / Low confidence]"
echo ""
echo "Options:"
echo "  1. Show AI attempt and edit manually"
echo "  2. Abort and resolve from scratch"
```

## Example Resolution

**Input (conflicting file):**
```typescript
export class API {
<<<<<<< HEAD
  fetch(url: string) {
    return axios.get(url);
  }
=======
  fetch(url: string, options?: RequestOptions) {
    return axios.get(url, { params: options });
  }
>>>>>>> abc123
}
```

**AI Analysis:**
- HEAD: Simple fetch without options
- INCOMING: Added optional parameters
- Intent: Add filtering capability
- Compatibility: Changes are additive

**Resolution:**
```typescript
export class API {
  fetch(url: string, options?: RequestOptions) {
    return axios.get(url, { params: options });
  }
}
```

**Validation:**
- ✅ Syntax valid (tsc check passes)
- ✅ No conflict markers
- ✅ Preserves original functionality (options are optional)
- ✅ Adds new capability
