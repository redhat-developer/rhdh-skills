# Feature and Program Increment readiness

Generate a release readiness report: feature status matrix, Program Increment funnel, epic roll-up, dependency map, blocker bugs, release notes readiness, and risk assessment.

Supports quick mode (ceremony prep, ~5 API calls) and deep mode (full coherence analysis with per-feature assessment, ~20+ calls).

Use paginated `acli` for bulk reads and the authenticated host adapter only for fields that `acli`
cannot return. Read-only: this route reports, and hands any fix to the skill that owns the write.

## Input

The caller provides:

1. **Release version** — e.g., `2.1`, `1.10`. Matches against candidate labels (`rhdh-2.1-candidate`) and fix versions.
2. **Team** — optional. If provided, filter to that team's Features/Epics only. If omitted, show all teams (program-level view).

## Mode Selection

> "Release status for {version}. **Quick** (ceremony prep, feature matrix + funnel) or **deep** (full coherence analysis, per-feature assessment)? [quick/deep]"

Default to **quick** if not specified.

## Quick Mode

### Step 1 — Fetch Features

Query RHDHPLAN Features with the candidate label or fix version. Replace `VERSION` with the target release version (e.g., `2.1`):

```bash
acli jira workitem search \
  --jql 'project = RHDHPLAN AND issuetype = Feature AND (labels = "rhdh-VERSION-candidate" OR fixVersion = "VERSION") ORDER BY priority ASC' \
  --fields "key,summary,status,priority,assignee,storypoints,labels,fixversions" --paginate --json
```

For Team, read `customfield_10001` with `acli jira workitem view KEY --fields '*all' --json`.
Use the authenticated host adapter only if the CLI omits it.

### Step 2 — Program Increment Funnel

Classify each Feature into PI release planning states based on its field values:

| PI State | Condition |
|----------|-----------|
| **Candidate Definition** | Labels include `needs-pm` or `needs-info` |
| **Defined but No Team** | Team field is empty |
| **Exploration** | Size is empty OR assignee is empty |
| **Ready for Commitment** | Size set, assignee set, has child Epics, fix version is empty |
| **Fixversion Set** | Fix version is set (committed to release) |

Show the funnel as a count breakdown:

```markdown
### Program Increment Funnel
| Stage | Count | Features |
|-------|-------|----------|
| ⚠ Candidate Definition (blocked on PM) | 2 | RHDHPLAN-402, RHDHPLAN-410 |
| ⚠ Defined but No Team | 1 | RHDHPLAN-415 |
| 🔍 Exploration | 3 | ... |
| ✅ Ready for Commitment | 2 | ... |
| ✅ Fixversion Set | 4 | ... |
```

### Step 3 — Feature Status Matrix

Map each Feature to its Jira workflow status with color coding:

| Icon | Status range |
|------|-------------|
| 🔴 | New, Refinement |
| 🟡 | Backlog |
| 🟢 | In Progress |
| ✅ | Release Pending, Closed |

Include: key, summary, status, owner, team, size, stretch flag.

### Step 4 — Stretch Features

Features with `stretch` label listed separately as descope candidates. These are first to cut if the release is at risk.

### Step 4b — Label Checks

For each Feature, verify expected labels:

| Label | Required when | Flag if missing |
|-------|--------------|----------------|
| `demo` | Customer-facing Feature | "Customer-facing Feature missing `demo` label — needs Feature Demo." |
| `rhdh-testday` | Test Day candidate | Informational only — note if present. |
| Documentation component | Feature requires docs | "No Documentation component — will Docs team create an Epic?" |

### Step 5 — Readiness Score

```
readiness = (Features in In Progress or later) / total Features × 100
```

Breakdown by status bucket.

### Step 6 — PM Blockers

Features with `needs-pm` or `needs-info` labels surfaced prominently:

```markdown
### ⏳ Waiting on PM ({count})
| Feature | Summary | Label | Days since label added |
```

## Deep Mode

Includes everything from quick mode, plus:

### Step 7 — Epic Roll-up

For each Feature, query child Epics:

```bash
jql: "issuetype = Epic AND parent = {feature_key}"
```

If 0 results, retry with legacy Epic Link: `"Epic Link" = {feature_key}` (older data may use this instead of `parent`).

Count Epics by status. Compute percent complete. Flag mismatches:

- Feature is "In Progress" but no child Epics are in progress → "Stale Feature status"
- Feature is "Backlog" but child Epics are "In Progress" → "Feature status behind Epics"

Invoke `/rhdh-jira-context` for the exit criteria of each Feature and Epic
status; it owns the workflow states and what each transition requires.

### Step 8 — Dependency Map

Scan `Blocks` and `Depend` issue links on Features and Epics. Filter to **cross-team and cross-project** dependencies only (same-team internal deps are noise).

For each dependency:

- Source issue (key, team, status)
- Target issue (key, team, status)
- Risk: is the blocker not started? Is it in a different team? Is it in a different project?

```markdown
### Dependencies (cross-team)
| Source | Depends on | Target Team | Target Status | Risk |
|--------|-----------|-------------|---------------|------|
| RHIDP-200 (COPE) | RHIDP-300 | Install Method | New | 🔴 not started |
```

### Step 9 — Blocker/Critical Bugs

Bugs in RHDHBUGS with the release fix version and priority Blocker or Critical:

```bash
jql: "project = RHDHBUGS AND priority in (Blocker, Critical) AND fixVersion = VERSION AND status != Closed"
```

Include: key, summary, status, assignee, days since last update.

### Step 10 — Release Notes Readiness

For Features and Epics in Release Pending or Closed, check:

- Release Note Type (`customfield_10785`) is set
- Release Note Text (`customfield_10783`) is set

Flag missing: "RN fields not set — required before closing."

### Step 11 — Per-Feature Coherence Analysis

For each Feature, assess:

1. Are exit criteria met for current status? (ask `/rhdh-jira-context`)
2. Are all child Epics sized?
3. Are child Epics assigned to teams?
4. Are there child Epics without Stories/Tasks (if Epic is in To Do+)?
5. Is there a Design Doc or RFE link (if Feature is in Refinement+)?

Produce a coherence score per Feature: `checks_passed / total_checks × 100`.

### Step 12 — Risk Assessment

Synthesize a 1-paragraph risk assessment:

- How many Features are blocked (on PM, on dependencies, on bugs)?
- What's the readiness score?
- Are there stale Features (New status, no activity)?
- Stretch feature count vs committed count
- Recommend: specific actions (assign, descope, escalate)

## Output

### Report shape

```json
{
  "version": "2.1",
  "team": null,
  "mode": "deep",
  "feature_count": 12,
  "readiness_score": 67,
  "pi_funnel": {
    "candidate_definition": ["RHDHPLAN-402"],
    "no_team": ["RHDHPLAN-415"],
    "exploration": ["RHDHPLAN-420", "RHDHPLAN-421"],
    "ready_for_commitment": ["RHDHPLAN-430"],
    "fixversion_set": ["RHDHPLAN-400", "RHDHPLAN-401"]
  },
  "features": [
    {
      "key": "RHDHPLAN-400",
      "summary": "...",
      "status": "In Progress",
      "owner": "Noah Rhodes",
      "team": "COPE",
      "size": "M",
      "stretch": false,
      "epic_count": 4,
      "epics_complete": 3,
      "coherence_score": 85,
      "rn_ready": true
    }
  ],
  "dependencies": [
    {"source": "RHIDP-200", "source_team": "COPE", "target": "RHIDP-300", "target_team": "Install Method", "target_status": "New", "risk": "high"}
  ],
  "blocker_bugs": [
    {"key": "RHDHBUGS-3100", "summary": "...", "assignee": "Connie Lawrence", "days_stale": 5}
  ],
  "stretch_features": ["RHDHPLAN-410"],
  "pm_blockers": ["RHDHPLAN-402"],
  "rn_missing": ["RHIDP-500"],
  "risk_assessment": "67% readiness. 1 Feature in New with no owner. 2 Blocker bugs. Recommend: assign RHDHPLAN-402 or descope."
}
```

### Markdown Template

```markdown
## Release Status — RHDH {version}

Features: {count} | Readiness: {score}% | Mode: {mode}

### Program Increment Funnel
| Stage | Count | Features |
|-------|-------|----------|

### Feature Matrix
| # | Feature | Status | Owner | Team | Size | Epics | Stretch |
|---|---------|--------|-------|------|------|-------|---------|

### ⏳ Waiting on PM ({count})
| Feature | Summary | Label | Days |

### 🔗 Dependencies — cross-team (deep only)
| Source | Depends on | Target Team | Status | Risk |

### 🐛 Blocker Bugs ({count})
| Bug | Summary | Assignee | Days stale |

### 📝 Release Notes Missing ({count}) (deep only)
| Issue | Type | Missing |

### 📊 Stretch Features (descope candidates)
| Feature | Summary | Owner | Status |

### Risk Assessment
{risk_paragraph}
```

## Remediation

This route does not write to Jira. After presenting the report, offer the fixes it
implies and hand each accepted one to `/rhdh-jira-update`, which states the target and
exact command, gets approval, and reports the outcome.

**⚠ Automation warning:** Setting fix version on a Feature cascades to all child Epics automatically (Jira automation rule). Setting Epic status also cascades to parent Feature. Ask `/rhdh-jira-context` for the automation rules. Warn the user before any fix version change.

Fixes worth offering:

- **Set fix version** on Features in "Ready for Commitment" (cascades to child Epics)
- **Create missing Epics** (Eng, QE, Doc) for Features in Backlog+ — via `/rhdh-jira-create`
- **Transition Feature status** when exit criteria are met
- **Assign owner** to unassigned Features
- **Add missing RN fields** — ask the user for Release Note Type and Text first

## Error Handling

| Error | Action |
|-------|--------|
| No Features match version/label | "No Features found. Check version name or label." |
| RHDHPLAN inaccessible | Stop. User lacks project access. |
| RHIDP inaccessible | Warn. Continue without Epic data. |
| Team field REST call fails | Skip team filtering. Show all Features. |
| Epic query returns 0 children | Note "no child Epics" — this is a finding, not an error. |
| Bulk search fails | Retry the paginated `acli` search once; do not fall back to raw REST search. |

## Caveats

1. **Team field requires REST fallback.** One REST call per Feature for team data. For 12 Features, this is 12 extra calls in quick mode.
2. **Coherence analysis is deep-mode only.** Quick mode skips per-feature exit criteria validation and epic child checks.
3. **PI funnel states are computed, not stored.** Jira doesn't have a "PI State" field — the funnel is derived from field values (labels, size, assignee, fix version).
4. **Cross-team dependency detection requires issue links.** Features/Epics without `Blocks`/`Depend` links won't show in the dependency map even if real dependencies exist.

## Success criteria

- [ ] Every Feature matching the version or candidate label appears in exactly one funnel stage
- [ ] Every Feature carries its status, owner, team, and size, or names the field as unretrieved
- [ ] The readiness score states the numerator and denominator it was computed from
- [ ] Deep mode names each Feature whose child Epics could not be read, rather than reporting zero
- [ ] Nothing was written to Jira by this route
