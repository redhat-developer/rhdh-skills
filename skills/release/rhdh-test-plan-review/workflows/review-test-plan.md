# Workflow: Review RHDH Test Plan

Reviews a test plan Jira ticket against platform and integration support lifecycle pages. Suggests adding versions GA before RHDH Code Freeze and removing versions EOL before RHDH GA date.

<prerequisites>

| Requirement | Check |
|-------------|-------|
| **Jira** | `/rhdh-jira-context`'s setup.py reports acli presence and the token file |
| **Google Sheets** | `python scripts/check_gsheets.py --json` → `"capability_ready": true` |

If Jira is unreachable, say so and direct the human to `/setup-rhdh-skills jira`.

If the Google Sheets check fails, load `references/google-sheets-setup.md` and
direct the human to `/setup-rhdh-skills google-workspace`.

</prerequisites>

<process>

## Step 1: Fetch the test plan Jira ticket

Read `TICKET-ID` with your Jira tool and use the enriched issue. Do not
locate Jira scripts or credentials.

Extract the RHDH version from `fixVersions[0].name`. If empty, check `summary` for a version string (e.g., "RHDH 1.6 Test Plan").

Normalize: strip any non-numeric prefix ("RHDH ", "v", "rhdh-") → plain `major.minor` (e.g., "1.6").

If the version cannot be determined, ask: "I couldn't determine the RHDH version from this ticket. What version is this test plan for?"

---

## Step 2: Fetch RHDH milestone dates

Invoke `/rhdh-release-schedule` by name and prefer what it returns. The local
schedule adapter is the fallback when that skill is unavailable:

```bash
uv run scripts/fetch_schedule.py --version "1.6"
```

Expected output:

```json
{
  "version": "1.6",
  "feature_freeze": "2025-09-15",
  "code_freeze": "2025-10-01",
  "ga_date": "2025-10-15",
  "tab": "2025 Schedule"
}
```

**On `{"error": "spreadsheet_not_found"}`:** Ask the user:
> "I couldn't access the RHDH Release Schedule sheet (ID: `<spreadsheet_id>`). Please share the sheet URL or ID."

Extract the ID from the URL (the alphanumeric string between `/d/` and `/edit`) and retry:

```bash
uv run scripts/fetch_schedule.py --version "1.6" --sheet-id <id>
```

**On `{"error": "version_not_found"}`:** Ask: "I couldn't find RHDH [version] milestones in the schedule sheet. Could you confirm the exact version string as it appears in the sheet?"

Use `code_freeze` and `ga_date` throughout the rest of this workflow.

---

## Step 3: Parse the test plan description

The description is in Atlassian Document Format (ADF). Parse the ADF JSON to locate:

1. **Key dates table** — rows for Feature Freeze, Code Freeze, and GA. Each row has the milestone label in the first cell and the date in the second cell (may be empty).
2. **Platform versions table** — rows listing OCP, ARO, AKS, EKS, GKE, OSD, ROSA with version numbers.
3. **Integration versions table** — rows listing PostgreSQL variants, RHBK, Quay with version numbers.

Record the current version set for each entry. Normalize version strings to `major.minor` for comparison. Record current key dates (may be blank).

---

## Step 4: Fetch lifecycle data

Load `references/sources.md` for all lifecycle URLs and extraction guidance.

Invoke `/rhdh-platform-lifecycle` by name for each required product and use the
versions and dates it reports. If a product is unavailable, retry its
authoritative source up to three times; after that, mark the row unverified with
a warning instead of inventing lifecycle data.

Apply using `code_freeze` and `ga_date`:

- **Add**: version GA date ≤ `code_freeze` AND not already in table
- **Remove**: version EOL date ≤ `ga_date` AND currently in table

### Platform-specific rules

**OCP** — accumulate all active versions. Add any version GA ≤ `code_freeze`; remove any version EOL ≤ `ga_date`.

**AKS, EKS, GKE** — single latest version only. Identify the newest version GA ≤ `code_freeze`. If it differs from the current, suggest replacing (not adding alongside).

**ARO, OSD, ROSA** — single version each, evaluated independently. Suggest replacing if a newer version is GA ≤ `code_freeze` and not EOL before `ga_date`. ARO, OSD, and ROSA are evaluated separately — do not assume they share the same version.

**RHBK** — track major versions only (e.g., `26`, not `26.0`). A major version is active if at least one of its minor releases is GA ≤ `code_freeze` and not EOL before `ga_date`. Add active majors not yet in table; remove a major only when **all** of its minor releases are EOL before `ga_date`.

**Quay** — single latest version only. Identify the newest version with a known GA date ≤ `code_freeze`. Suggest replacing the current version.

**PostgreSQL** — RHDH support policy page is the baseline (already officially supported). For any version Backstage supports but is NOT on the RHDH policy page, suggest it as a candidate with a mandatory warning:
> ⚠ Adding a new PostgreSQL version requires a dedicated RHDH Jira Feature ticket to extend database support — do not add without one.

Apply the EOL removal rule across all three providers (RDS, Azure DB, CloudSQL) — remove only if EOL across all three.

---

## Step 5: Present the overview diff

Include key dates first, then platforms, then integrations. Use ANSI colors (green for additions, red for removals) inside a code block:

```
Key Dates
─────────────────────────────────────────────────────────────────────
Milestone        │ Current    │ Suggested  │ Source
─────────────────────────────────────────────────────────────────────
Code Freeze      │ (empty)    │ 2026-05-19 │ RHDH schedule sheet
GA               │ (empty)    │ 2026-06-10 │ RHDH schedule sheet
─────────────────────────────────────────────────────────────────────

Platforms
─────────────────────────────────────────────────────────────────────
Platform  │ Current  │ Suggested  │ Reason
─────────────────────────────────────────────────────────────────────
ARO       │ 4.19     │ →4.20      │ ARO GA Oct 2025 ≤ code freeze
EKS       │ 1.34     │ →1.35      │ EKS release Jan 27 ≤ code freeze
─────────────────────────────────────────────────────────────────────

Integrations
─────────────────────────────────────────────────────────────────────
Integration  │ Current  │ Suggested  │ Reason
─────────────────────────────────────────────────────────────────────
RHBK         │ 24, 26   │ −24, 26    │ RHBK 24 EOL May 2025 ≤ ga date
─────────────────────────────────────────────────────────────────────
```

Skip rows with no proposed changes. Note skipped sources with ⚠.

---

## Step 6: Interactive line-by-line review

Walk through each proposed change **one at a time** — key dates first, then platforms, then integrations. This is decision-collection only — nothing is written to Jira here.

For each change:

```
──────────────────────────────────────────
 AKS  │ Current: 1.34
      │ Suggested: →1.35
      │ Reason: AKS GA Mar 2026 ≤ code freeze May 19
──────────────────────────────────────────
  [a] Accept suggestion  →  1.35
  [k] Keep current       →  1.34
  [e] Enter your own value
Choice [a/k/e]:
```

- **[a]**: record the suggested value
- **[k]**: record no change, move on
- **[e]**: prompt for a value, confirm, then record

After all decisions, print a summary of rows that will change, then ask:

```
How would you like to apply these changes?
  [d] Update the Jira description directly
  [c] Post a comment on the ticket with the suggested changes
  [n] Do nothing — discard all decisions
Choice [d/c/n]:
```

- **[d]**: proceed to Step 7
- **[c]**: proceed to Step 7b
- **[n]**: confirm no changes were made and stop

---

## Step 7: Apply changes — direct update

Modify only the version strings in platform/integration table cells and the date
cells in the key dates table. Preserve all other ADF structure exactly.

Follow `/mutation-gate`. State one operation: the target ticket, the exact
ADF document that will replace the description, the read-back that verifies it,
and what happens if the update fails. Wait for explicit approval, then invoke
`/rhdh-jira-update` to apply it and report the outcome. On failure, report it and
stop — do not continue to Step 8.

---

## Step 7b: Apply changes — post comment

Draft the comment text and **show it to the user before posting**:

```
*Test Plan Version Review — RHDH X.Y*

*Suggested platform/integration updates:*
• AKS: 1.34 → 1.35
• RHBK: 24, 26 → 26

These suggestions are based on support lifecycle pages checked on [today's date].
No changes have been applied to this ticket.
```

Invoke `/prose-editing` once on the completed comment body in the **flavored**
register. Preserve product versions, platform names, dates, and the claim about
whether changes were applied. Show and gate that edited body; `/rhdh-jira-update`
only transports it.

Follow `/mutation-gate`. State one operation: the target ticket and the exact
comment body shown above. The user may approve, edit, or cancel it. Post only
after approval. Hand the exact approved body to `/rhdh-jira-update` as
**caller-finalized**, so it transports the body without another prose pass or
confirmation. Report the outcome, then stop; do not create child tasks for a
comment-only outcome.

---

## Step 8: Create child tasks (after direct update only)

For each accepted change with an infrastructure impact, offer a child task one at a time:

| Change type | Child task title template |
|---|---|
| AKS version changed | `[RHDH X.Y] Update Kubernetes version to X.Y on AKS cluster` |
| EKS version changed | `[RHDH X.Y] Update Kubernetes version to X.Y on EKS cluster` |
| GKE version changed | `[RHDH X.Y] Update Kubernetes version to X.Y on GKE cluster` |
| OCP version added | `[RHDH X.Y] Create prow job for OCP X.Y` |
| OCP version removed | `[RHDH X.Y] Remove prow job for OCP X.Y` |
| ARO version changed | `[RHDH X.Y] Update ARO cluster to OCP X.Y` |
| OSD version changed | `[RHDH X.Y] Update OSD cluster to OCP X.Y` |
| ROSA version changed | `[RHDH X.Y] Update ROSA cluster to OCP X.Y` |

For each candidate:

```
──────────────────────────────────────────────────────────────
 Child task  │ [RHDH 1.10] Update Kubernetes version to 1.35 on EKS cluster
             │ Parent: RHIDP-XXXXX
──────────────────────────────────────────────────────────────
  [c] Create this task
  [s] Skip — do not create
  [e] Edit the title before creating
Choice [c/s/e]:
```

Collect every accepted child task into one stated set, following
`/mutation-gate` — one row per task with its exact title and parent key. Ask
for approval once for that exact batch, then create them through
`/rhdh-jira-create`. Create nothing that was not listed.

Report the created keys, and report every task the user skipped as skipped.

</process>

<gotchas>

- **ADF round-trip**: Send ADF when updating via REST — converting to plain text destroys formatting. Modify only version strings inside existing table cells.
- **Credential safety**: Jira access goes through your authenticated Jira tool.
  Credentials stay out of shell variables, files, previews, and the answer.
- **Key dates table**: Match milestone rows by label keyword (e.g., "Code Freeze", "GA announce"). Update only the date cell. Leave rows you cannot match untouched.
- **Version normalization**: Tables may use "v1.29", "1.29.x", or "Kubernetes 1.29" — normalize to `major.minor` before comparing.
- **fixVersions format varies**: May be "1.6", "RHDH 1.6", "rhdh-1.6" — strip prefixes before passing to `fetch_schedule.py`.
- **Schedule tab is year-based**: `fetch_schedule.py` tries current year first, then adjacent years. Pass `--sheet-id` if the schedule is in a non-default spreadsheet.
- **Child task issuetype**: Use `"Task"` with a `parent` field. If that fails with 400, retry with `"issuetype": {"name": "Subtask"}`.
- **Child task project key**: Use the same project key as the parent (e.g., `RHIDP`).

</gotchas>
