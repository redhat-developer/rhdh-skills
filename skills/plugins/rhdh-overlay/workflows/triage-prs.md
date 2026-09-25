# Workflow: Triage Overlay PRs

Prioritize open PRs in the overlay repository by criticality and surface
actionable next steps.

```bash
python scripts/triage-prs.py              # markdown report
python scripts/triage-prs.py --json        # structured JSON
```

One run lists the open PRs, classifies each by label, and computes assignment
and staleness. Consume its output rather than re-listing the same PRs; the
phases below are the classification logic it applies and the actions that follow.

<required_reading>
**Read this reference NOW:**

1. `references/label-priority.md` — PR classification by labels
</required_reading>

<prerequisites>
| Requirement | Details |
|-------------|---------|
| **Access** | Read access to [rhdh-plugin-export-overlays](https://github.com/redhat-developer/rhdh-plugin-export-overlays) |
| **Tools** | `gh` CLI authenticated |
| **Role** | Core Team (COPE, Plugins team) |
</prerequisites>

For a read the script does not cover — a narrower label filter, a check the
rollup omitted, a failing run's log — invoke `/rhdh-forge`, which owns the `gh`
and `jq` read patterns and the rate-limit guidance for wide sweeps. Do not write
intermediate results to a fixed temporary path.

<process>

## Phase 1: Classify by priority

| Priority | Labels | Meaning |
|----------|--------|---------|
| 🔴 Critical | `mandatory-workspace` + `workspace-update` | Updates to RHDH catalog plugins |
| 🟡 Medium | `mandatory-workspace` + `workspace-addition` | New plugins for the RHDH catalog |
| 🟢 Low | `workspace-addition` only | Community plugins, not in the catalog |
| ⚫ Skip | `do-not-merge` | OCI artifact generation only |

---

## Phase 2: Assess each priority PR

For every Critical and Medium PR:

**Assignment**

- ❌ No assignee and no individual reviewer → needs assignment
- ⚠️ Only a team reviewer → responsibility diluted
- ✅ Individual assigned → clear ownership

**Checks**

- `publish` must pass before merge
- `workspace-tests` / `smoke` validates that the plugin loads

A check absent from the rollup never ran. Treat that as "needs `/publish`", not
as a failure, and confirm any verdict against the head branch's runs before
reporting it.

**Staleness**

| Priority | Warn | Alert |
|----------|------|-------|
| Critical | 2 days | 5 days |
| Medium | 5 days | 10 days |
| Low | 14 days | 30 days |

---

## Phase 3: Generate the report

```markdown
## Overlay PR Triage Report
Generated: {date}

### 🔴 Critical — Mandatory Workspace Updates

| PR | Plugin | Days Stale | Assignee | Checks | Action |
|----|--------|------------|----------|--------|--------|
| #1234 | aws-ecs | 3 | @user | ✅ Publish ✅ Smoke | Ready to merge |
| #1235 | intelligent-assistant | 7 | (none) | ⏳ Publish | Assign + /publish |

### 🟡 Medium — Mandatory Workspace Additions

| PR | Plugin | Days Stale | Assignee | Checks | Action |
|----|--------|------------|----------|--------|--------|
| #1240 | new-plugin | 2 | @contributor | ❌ Missing CODEOWNERS | Request CODEOWNERS |

### 🟢 Low — Community Additions
[... or "No low-priority PRs" ...]

### ⚫ Skipped — Do Not Merge
| PR | Plugin | Reason |
|----|--------|--------|
| #1250 | orchestrator-test | OCI artifact only |

---

## Suggested Actions

1. [ ] **Assign** @someone to PR #1235 (intelligent-assistant, 7 days stale)
2. [ ] **Trigger** `/publish` on PR #1236
3. [ ] **Ping** @owner for PR #1237 (blocking release)
4. [ ] **Request** CODEOWNERS from contributor on PR #1240
```

---

## Phase 4: Take action

Triage is a read. Every action below is an external write.

### Trigger publish

For one PR or a user-selected batch, follow the guarded publish in `SKILL.md`:
state one comment operation per PR against its current head SHA, show the
complete ordered set, get approval, post only those comments, then report an
outcome for each. A triage request does not approve publication.

Bot-authored PRs never trigger publication themselves, so they accumulate in
this state. `/rhdh-forge` has the query that finds them.

### Suggest assignment

The script reports the CODEOWNERS entry for each workspace a PR touches. Naming
a candidate is free; assigning them is a write and goes through the gate.

### Draft a Slack ping

Load and follow `workflows/draft-notification.md` for every Slack draft. Use the
final messages it returns; this triage workflow does not compose a fallback.

</process>

<output_format>
The triage report should be:

1. **Actionable** — each row has a clear "Action" column
2. **Scannable** — grouped by priority, most important first
3. **Time-aware** — shows staleness, flags alerts
4. **Complete** — accounts for all open PRs, even if only to skip them
</output_format>

## Follow-up record

Return the complete triage report plus an action receipt for each external
write. Include deferred fixes, stale critical PRs, missing owners, release
blockers, and pending contributor replies. Do not maintain a local cache of PR
state; fetch it again on the next run.

<success_criteria>
Triage is complete when:

- [ ] All open PRs classified by priority
- [ ] Critical PRs have assignees or an action to assign
- [ ] Publish triggered, under an approved plan, on PRs that need it
- [ ] Stale PRs flagged with suggested owners
- [ ] Report generated for team review
</success_criteria>
