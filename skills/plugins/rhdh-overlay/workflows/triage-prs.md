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

**Next command**

Derive one next action per PR from its state. Apply the first row that matches.

| PR state | Next action |
|---|---|
| `do-not-merge` label | No action — OCI artifact only |
| Draft | Wait for the author |
| `publish` check failed | Read the run log, then `/publish` or `workflows/fix-build.md` |
| `publish` check missing | `/publish` |
| `publish` check pending | Wait |
| Any other check failed | Fix the failing check; `/publish` again if the check tests the published artifact |
| Checks pending | Wait |
| Checks unreadable | Re-run triage |
| Every check passed | Ready to merge |

A check absent from the rollup never ran. Treat that as "needs `/publish`", not
as a failure, and confirm any verdict against the head branch's runs before
reporting it.

`publish` is the only required status check on `main` and `release-**`. The
command that ran creates it, so a PR needs its next command before it can merge.

**What a PR without exactly one workspace needs**

`pr-actions.yaml` resolves exactly one workspace from the branch name or the PR
files. When a PR touches zero or several workspaces, `prepare` skips the pending
status and `add_no_workspace_comment` records a successful one under the
command's name, with a comment saying the action was cancelled. That status
satisfies the required check, so `/publish` is still the next command for such a
PR: it records the check without publishing anything or dispatching smoke tests.
Report the cancellation; do not report the PR as blocked.

Splitting the PR per workspace is optional and only right when the change
belongs to one workspace. Repo-wide changes to shared scripts and workflows
legitimately touch many workspaces and merge through the cancelled `/publish`
run. A `workspaces/release-<version>__<workspace>` branch resolves to its
workspace by name even when the PR touches several.

`/publish` success dispatches the workspace smoke tests itself, so `/smoketest`
is only for a published PR that needs another tag or a re-run.

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

| PR | Plugin | Days Stale | Assignee | Action |
|----|--------|------------|----------|--------|
| #1234 | aws-ecs | 3 | @user | Ready to merge |
| #1235 | intelligent-assistant | 7 | (none) | Trigger /publish + Assign owner |

### 🟡 Medium — Mandatory Workspace Additions

| PR | Plugin | Days Stale | Assignee | Action |
|----|--------|------------|----------|--------|
| #1240 | new-plugin | 2 | @contributor | Fix failing checks |
| #1242 | catalog,theme | 1 | @contributor | Trigger /publish (2 workspaces: /publish is cancelled and only records the required check) |

### 🟢 Low — Community Additions
[... or "No low-priority PRs" ...]

### ⚫ Skipped — Do Not Merge
| PR | Plugin | Reason |
|----|--------|--------|
| #1250 | orchestrator-test | OCI artifact only |

### ❓ Unknown — Needs Labels

| PR | Title | Days Stale | Author | Next |
|----|-------|------------|--------|------|
| #1244 | fix(ci): make the stale label truthful | 6 | @contributor | Trigger /publish |

---

## Suggested Actions

1. [ ] **Trigger /publish + Assign owner** — PR #1235 (intelligent-assistant, 7 days stale)
2. [ ] **Fix failing checks + Escalate (stale)** — PR #1240 (new-plugin, 9 days stale)
3. [ ] **Trigger /publish (2 workspaces: /publish is cancelled and only records the required check)** — PR #1242 (catalog,theme, 4 days stale)
```

Every tier that carries an action shows it, and the Unknown table shows the next
command, so an unlabeled PR still says what it needs. The Action column combines
the next command with ownership and staleness advice when either applies.

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
