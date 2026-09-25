# Grill Behavior

The RHDH-specific half of an issue-creation interview. The general interview
cadence belongs to the external `grilling` skill; what is here is the part
`grilling` cannot know — which challenges matter for an RHDH Feature, Epic,
Story, Task, or Bug, and how to infer RHDH Jira fields from the conversation.

Load this alongside the caller's type-specific questions. Apply every applicable
behavior during the grill — don't skip challenges to be polite.

Sizing scales are in [sizing.md](sizing.md) alongside this file. Field IDs,
labels, and the component catalog are in `/rhdh-jira-api`.

## Cadence

**Invoke the named skill `grilling` once covering Fill Gaps + Challenge.** Do not
locate or read its files and do not re-implement its cadence here.

**Grill complete when:** every applicable Challenge Behavior from the matrix below has been applied (or explicitly skipped with a reason), inferred fields are confirmed, and Validate before creating passes.

Domain-specific challenges below stay in this skill. If the conversation already established context (e.g., chained from a parent issue), don't re-ask — carry it forward.

### Grilling prerequisite

The external `grilling` skill is a hard prerequisite for creating an issue. It is
not bundled with this pack — the user installs it separately.

If the host reports `grilling` unavailable, stop before creating anything. Say
that `grilling` is missing, that issue creation is gated on it, and that the fix
is to run `/setup-rhdh-skills install`. Do not probe host skill directories, run
an installer, or improvise a substitute interview. Resume only once `grilling`
can be invoked by name.

Creation is the only gated path, and deliberately so. **Do not gate
`/rhdh-jira-refine`, `/rhdh-jira-update`, `/rhdh-jira-sprint-plan`, or
`/rhdh-jira-sprint-report` on grilling** — those read or adjust work that already
exists, and blocking them on an optional external skill would take a whole
capability offline for no benefit.

## Field Inference

Don't ask the user to fill in each Jira field manually. Instead, infer field values from the conversation and present a recommendation for confirmation. The grill is a conversation, not a form.

After the grill questions are complete, present all inferred fields at once:

> "Based on our discussion, here's what I'd set:"
>
> - **Priority**: Major — this is a functional gap, not a regression or blocker
> - **Team**: COPE — you mentioned this is in the dynamic plugins area
> - **Size**: M (3) — cross-team coordination + 4 AC items suggests ~3 sprints
> - **Component**: Plugins — primary area of change
> - **Assignee**: Allison Hill — top expertise in plugins per assign analysis
> - **Labels**: `rhdh-2.1-candidate`, `demo`, `RHDH-Customer` — customer-origin feature (CASE-12345) targeting 2.1
>
> "Adjust any of these? [y to confirm / list changes]"

### Inference signals

| Field | Infer from |
|-------|------------|
| **Priority** | Severity of the problem, customer impact, blocker language, urgency words. Default to Major unless clear signals suggest otherwise. |
| **Team** | Components mentioned, domain area, who the user is, parent issue's team, which team owns the affected code. |
| **Size** | AC count, dependency count, complexity signals from the grill ("need to investigate", "multiple PRs", "cross-team"). Use the scales in [sizing.md](sizing.md). |
| **Component** | Technical domain discussed (RBAC, plugins, catalog, helm, operator, CI/CD, docs). Match against the component catalog in `/rhdh-jira-api`. Also check codebase context — if the user has been editing files during the session, infer from file paths (see below). |
| **Assignee** | If the user is describing their own work, suggest them. Otherwise, run a lightweight expertise match from the conversation context (component + domain keywords against team roster). For a real roster-and-capacity analysis, hand off to `/rhdh-jira-update`. |
| **Labels** | Customer-facing → `demo`. Release target mentioned → `rhdh-X.Y-candidate`. Stretch goal language → `stretch`. Support/customer origin → single `RHDH-Customer` (never also apply `rhdh-customer`). |
| **Affects Version** | RHDHBUGS Bugs only. Infer from Build Details / prerequisites. Required at create — see `/rhdh-jira-api` (`fields.md`, Bug workflow). Confirm before the write gate. Not Fix Version. |

### Codebase-aware component inference

If the session involved editing or reading files, use the file paths to infer the component:

```bash
# Check recently modified files in the working tree
git diff --name-only HEAD~3 2>/dev/null | head -20
```

Path-to-component signals:

| Path pattern | Component |
|--------------|-----------|
| `plugins/catalog/`, `catalog-backend` | Catalog |
| `plugins/rbac/`, `rbac-backend` | RBAC |
| `plugins/tekton/` | Tekton |
| `plugins/topology/` | Topology |
| `plugins/lightspeed/` | Lightspeed |
| `plugins/bulk-import/` | Bulk Import |
| `packages/backend/`, `packages/app/` | Build |
| `docker/`, `Dockerfile`, `Containerfile` | Build |
| `charts/`, `helm/` | Helm |
| `docs/`, `*.md` in doc paths | Documentation |
| `e2e/`, `playwright/`, `cypress/` | Test Framework |
| `.github/`, `ci/`, `.tekton/` | CI/CD |

This is a hint, not definitive. Present as: "You've been working in `plugins/catalog/` — setting Component to Catalog." The user can override.

### When inference is weak

If a field can't be inferred with reasonable confidence, say so: "I'm not sure about the team — is this COPE or Install Method?" Don't guess silently. One targeted question is better than a wrong default.

## Challenge Behaviors

### Challenge sizing

After the user proposes a size (T-shirt or story points):

- Count the acceptance criteria items. If the AC count seems high for the proposed size, push back: "You have {N} acceptance criteria items — is {size} realistic?"
- Check for cross-team dependencies. Dependencies add coordination overhead that inflates effort.
- Check for unknowns. If the user said "we need to investigate" or "not sure about," that's a spike signal — suggest time-boxing or splitting the unknown into a separate spike.
- Cross-reference against the sizing guide already loaded by the create command (T-shirt for Features/Epics; Fibonacci for Stories/Tasks).

### Challenge completeness

After the user describes scope and AC:

- **Testing**: "Does QE need to be involved? Is there a test plan or automation needed?" If the issue type is an Epic or Feature and no testing consideration was mentioned, ask.
- **Documentation**: "Does this change user-facing behavior? If so, docs need updating." If documentation wasn't mentioned for a user-facing change, flag it.
- **Upstream**: "Is there upstream Backstage work that needs to land first? Or is this purely downstream?" Don't assume — ask if not clear from context.
- **Security**: For features touching auth, RBAC, permissions, or API endpoints: "Any security considerations?"
- **Migration/Breaking changes**: "Does this change existing behavior? Will users need to update their configuration?"

Skip challenges that clearly don't apply. Don't ask about docs for a CI pipeline task. Don't ask about upstream for a purely downstream bug fix.

### Challenge scope

- **Split signals**: If a single AC item is complex enough to be its own issue, say so: "This AC item — '{item}' — sounds like it could be a separate {Story/Epic}. Should we split it?"
- **Overlap**: During the duplicate check (which runs after the grill), if related issues were found, revisit scope: "This overlaps with {KEY}. Should this issue be scoped to only the non-overlapping parts?"
- **Scope creep markers**: If the user keeps adding "also it should..." or "and maybe we could..." — pause and ask: "We're growing the scope. Should some of this be a follow-up issue?"

### Challenge epic independence

When creating an Epic (especially under a parent Feature), challenge whether it is independently shippable or is really an implementation detail of a sibling Epic:

- "Could this be acceptance criteria on [sibling Epic] instead of its own Epic?"
- "Does this Epic produce a separately testable, deployable, or documentable artifact?"
- "If you removed this Epic, would the parent Feature have a functional gap — or would a sibling Epic just grow by a few ACs?"

**Signals that an Epic should be folded into a sibling:**

- Ships in the same PR or package as another Epic under the same Feature
- Has no independent acceptance criteria beyond "implement X" (where X is a detail of a broader capability)
- Cannot be demoed or documented independently of a sibling
- Its User Scenarios are identical to a sibling's
- Sized XS while sibling Epics cover the same technical domain

When folding is warranted, recommend adding scope as ACs on the sibling Epic instead of creating a new one.

### Challenge AC quality

After the user provides acceptance criteria, verify they are specific, testable, and substantive:

- **Minimum count**: An Epic must have at least 3 substantive ACs beyond the standard DEV/QE/DOC checklist items. If it has fewer, push: "The standard checklist items are process gates, not functional acceptance criteria. What does 'done' look like for a user or operator?"
- **Verifiable outcomes**: Each AC should specify a verifiable outcome, not an activity. Flag activity-style ACs: "Implement audit logging" → should be "Audit events are emitted with: timestamp, actor, action, target entity."
- **Vague language**: Flag ACs containing "works correctly", "is supported", "is handled properly", "is implemented" — these are not testable. Ask: "How would QE verify this? What specific behavior would they check?"
- **Measurable where possible**: For performance, scale, or capacity ACs, push for numbers: "How many concurrent users? What latency target? What's the minimum throughput?"

### Challenge sibling overlap

When creating an Epic under a Feature that already has sibling Epics:

1. List existing sibling Epics (query `parent = FEATURE-KEY AND issuetype = Epic AND status != Closed`)
2. For each sibling, compare scope: "Does this new Epic share implementation surface, test surface, or deliverable artifacts with [sibling]?"
3. Check for overlapping signals:
   - Same target codebase or package
   - Same dependencies listed
   - User Scenarios that describe the same user journey
   - ACs that would be verified by the same tests
4. If overlap is found: "This overlaps with {KEY} ({summary}). Should this scope be added to {KEY} as additional ACs instead of creating a new Epic?"

This catches cases where two Epics have different summaries but overlapping scope (e.g., "OCI Registry Ingestion" and "OCI Connector" that target the same package).

### Probe risks and unknowns

- "What could go wrong with this approach?"
- "Are there any unknowns that might change the sizing?"
- "Is there a dependency on another team or external service that could block this?"
- "Has this been attempted before? If so, what happened?"

Don't ask all four — pick the ones that are relevant based on context. For a simple Task with clear scope, skip risk probing. For a Feature with cross-team dependencies, probe harder.

### Cross-reference existing issues

During the grill (not just during duplicate check), search for related work:

- If the user mentions a component, search for open issues in that component: "There are {N} open issues in {component} — any of these related?"
- If the user mentions a dependency, verify it exists in Jira: "You mentioned depending on {thing} — is that tracked as a Jira issue?"
- If a related issue is found, ask whether to add an issue link (Blocks, Depends, Related).

Keep this lightweight. One search during the grill is enough — don't run a search after every answer.

### Validate before creating

Before proceeding to creation, verify the issue would pass New-status entry criteria:

- Are all required fields for New status determined? (Assignee, Priority, Team, Component — varies by type; for RHDHBUGS Bugs also Affects Version — see `/rhdh-jira-api`)
- Is the description substantive enough? A one-sentence description on a Feature is a red flag.
- Is the summary clear and specific? Summaries like "Update plugins" or "Fix bug" are too vague.

Also enforce customer identity and label rules. `/rhdh-jira-api` holds the authoritative detail:

- **Preferred pattern:** Put support-ticket / case keys (and persona/use-case language) in summary/description when needed; apply a single `RHDH-Customer` Jira label for customer-origin work; put customer-identifying detail only in restricted-visibility comments when the project supports it.
- **Guardrail:** Never put customer names or other identifying detail in unprotected fields (summary, description, public fields).
- **Labels:** Apply exactly one `RHDH-Customer` — never both `RHDH-Customer` and `rhdh-customer` (Jira label search is case-insensitive).

If validation fails, ask the user to fill the gap rather than creating a half-baked issue.

## Applicability by Issue Type

Not every behavior applies to every type. Use this as a guide:

| Behavior | Feature | Epic | Story | Task | Bug |
|----------|---------|------|-------|------|-----|
| Challenge sizing | ✅ | ✅ | ✅ | ✅ (if SP set) | ❌ |
| Completeness: testing | ✅ | ✅ | ✅ | ❌ | ❌ |
| Completeness: docs | ✅ | ✅ | ✅ (if user-facing) | ❌ | ❌ |
| Completeness: upstream | ✅ | ✅ | ✅ | ❌ | ❌ |
| Completeness: security | ✅ | ✅ | ✅ | ✅ | ❌ |
| Completeness: migration | ✅ | ✅ | ✅ | ❌ | ❌ |
| Challenge scope | ✅ | ✅ | ✅ | ❌ | ❌ |
| Challenge epic independence | ❌ | ✅ | ❌ | ❌ | ❌ |
| Challenge AC quality | ✅ | ✅ | ✅ | ❌ | ❌ |
| Challenge sibling overlap | ❌ | ✅ | ❌ | ❌ | ❌ |
| Probe risks | ✅ | ✅ | ❌ | ❌ | ❌ |
| Cross-reference | ✅ | ✅ | ✅ | ✅ | ✅ |
| Validate before creating | ✅ | ✅ | ✅ | ✅ | ✅ |

**Vulnerability** follows the Story column. Always requires Security component.

Bugs skip most challenges — the goal is to capture the defect accurately, not challenge whether it should exist. Cross-reference and validation still apply (check for duplicates, ensure fields are set).

Tasks skip scope/risk challenges unless they're complex (multi-day, cross-system). Use judgment.

## Comment Suggestions

After the issue is created, proactively suggest comments for context that emerged during the grill but doesn't belong in the description:

- **Decision trail**: "We discussed [alternative] but chose [approach] because [reason]."
- **Elaboration**: "Additional context about [topic] that supports the decision."
- **Abandoned paths**: "Initially considered [approach], abandoned because [reason]."
- **Customer context**: Prefer support key + use case ("Raised via CASE-123 — SSO timeout during session refresh"). Put customer-identifying detail only in a restricted-visibility comment when needed; never paste customer names into unprotected fields.

Present each suggestion with a recommended comment text. The user approves, edits, or skips each one.
