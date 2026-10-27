# Workflow: Create an RHDH Plugin Pull Request

<essential_principles>

<principle name="scoped_dist_cleanup">
Pre-build cleanup uses `rm -rf plugins/*/dist packages/*/dist` scoped to the workspace directory. If permission errors occur (root-owned files from a prior Docker build), **skip only `yarn build:all`** and warn the user to run `sudo chown -R $(whoami) .` to fix ownership permanently. Never use `sudo` in the skill itself. Never use `find -name dist` or any broad recursive search — that deletes `dist/` inside `node_modules` and breaks everything.
</principle>

<principle name="changesets_skip_packages">
Only plugins under `plugins/*` with published-source changes need changesets. Always ignore `packages/*` — those are private app/backend packages that are never published. Within each plugin, only include it if changes touch `src/` or other published paths (root `index.ts`, `config.d.ts`, `package.json`). Changes only in `dev/`, `tests/`, `__fixtures__/`, or storybook stories do not require a changeset.
</principle>

<principle name="baseline_diffing">
Capture `git status --porcelain` before builds as the baseline, minus the change set. After builds, only stage the change set plus files that are new relative to that baseline. Pre-existing dirty files (local config overrides, dev fixtures) must never be staged, and a file named by the change handoff's file list is never treated as pre-existing.
</principle>

<principle name="no_manual_pr_creation">
Follow every step sequentially, including build, changeset, commit, recording
upload, push, and PR creation. A supplied change handoff pre-populates fields;
it does not skip publication safeguards.
</principle>

<principle name="recordings_upload_hard_gate">
When the change handoff supplies recordings, the GIF upload in Step 10.2 is MANDATORY — not optional. You MUST upload both GIF files to the dedicated `screenrecordings` branch on the user's fork via the GitHub Contents API and extract real `raw.githubusercontent.com` URLs BEFORE constructing the PR body. NEVER upload to the feature branch (it pollutes the PR diff and lands on upstream main). NEVER use placeholder URLs, `github.com/user-attachments/assets/` URLs, or any fabricated URLs. If the upload fails, you MUST either retry or inform the user that manual upload is needed — do NOT silently proceed with broken image links.
</principle>

</essential_principles>

## Prerequisites

- **`gh` CLI** — GitHub CLI must be installed and authenticated (`gh auth status` should show logged in). Install: <https://cli.github.com/>
- **`/rhdh-jira-update`** — required only when the published PR must be linked
  back to Jira; **`/rhdh-jira-context`** when field or JQL context is needed.
  This workflow never reads Jira credentials or chooses a Jira transport.
- Working checkout of `rhdh-plugins` (or `community-plugins`)
- `yarn` available on PATH

---

## Approval mode

There is no auto-approve mode. Treat legacy `--a` as unsupported and explain
that every external write is stated in full — target, exact command, and preview
of the change — approved as that stated set, and then reported operation by
operation. Earlier intent to publish never authorizes an operation whose exact
target and payload have not been shown.

---

## Step 1 — Detect repo profile

Read `references/repo-profiles.md` and follow the detection logic. Run `git remote -v`, match the remote URLs, and load the matching profile (upstream repo, npm scope, PR body template, changeset docs link).

If no profile matches, ask the user which repo they are targeting before proceeding.

Store the profile values for use in Steps 5, 6, and 10.

---

## Step 1.5 — Resolve issue context

Determine whether the PR is linked to a Jira issue, GitHub issue, or neither.

### Source 1: Caller context (highest priority)

If the change handoff names an issue reference, map it to these fields and use it directly:

- **`issue_source` = `jira`:** Use `jira_key`, `jira_url`, `jira_summary` mapped from the handoff. Skip detection.
- **`issue_source` = `github`:** Use `github_issue_number`, `github_issue_url`, `github_issue_repo`, `github_issue_title` mapped from the handoff. Skip detection.

### Source 2: User argument

If no change handoff was supplied, parse the user's argument:

**Jira patterns** (read `references/jira-input.md`):

- If input matches `(RHIDP|RHDHBUGS|RHDHPLAN|RHDHSUPP)-\d+` anywhere in the string, extract that as the key.
- If input contains `atlassian.net/browse/`, extract everything after `/browse/` as the key.
- Construct: `jira_url = https://redhat.atlassian.net/browse/<jira_key>`
- Set `issue_source = jira`.

**GitHub patterns** (read `references/github-input.md`):

- If input contains `github.com/.../issues/<N>`, extract owner/repo and number.
- If input matches `#\d+`, resolve repo from `git remote -v`.
- Construct: `github_issue_url = https://github.com/<owner>/<repo>/issues/<N>`
- Set `issue_source = github`.

### Source 3: Branch name

If no argument matched, check the current branch name:

- Jira key pattern: `fix/RHDHBUGS-1934-keyboard-nav` → extract `RHDHBUGS-1934`, set `issue_source = jira`.
- GitHub issue pattern: `fix/607-report-portal-crash` → extract `#607` only if combined with repo context from `git remote -v`, set `issue_source = github`.

### Source 4: Prompt

Ask: "Issue key, URL, or #number? (enter to skip)".

### Fetch summary (if not provided by caller)

- **Jira:** Read the issue with your Jira tool and consume the detail.
  If no Jira tool is available, store `jira_summary = null`, retain
  the key, and report that Jira enrichment is unavailable and that the human's
  next step is `/setup-rhdh-skills jira`. Do not inspect credentials or call Jira
  REST, MCP, GraphQL, or `acli` from this workflow.
- **GitHub:** `gh issue view <N> --repo <repo> --json title -q .title`. If fetch fails, store `github_issue_title = null` and continue.

### Store

Set `issue_source` = `jira`, `github`, or `null`. If `null`, all issue-specific behavior in later steps is skipped.

---

## Step 2 — Resolve the change set and detect workspace(s)

1. **If a change handoff was supplied:** the change set is its file list. The producing
   skill does not stage, so these paths are normally unstaged or untracked. Run
   `git status --porcelain -- <files>` and confirm every path appears as modified, added,
   or untracked; report any path that is missing or clean and stop. Do not stage here —
   staging happens once, at the Step 8 gate, for exactly these paths plus the
   build-generated files.
2. **If no handoff was supplied:** run `git diff --cached --name-only`. If no files are
   staged, stop: "No staged changes found. Stage your changes with `git add` before running this command."
3. Record the **change diff** command used by later steps: `git diff --cached` when the
   change set came from the index, `git diff -- <change set paths>` when it came from
   the handoff.
4. Extract workspace names from the change-set paths. The workspace is the second path segment (e.g., `workspaces/bulk-import/plugins/foo/src/index.ts` → workspace `bulk-import`, path `workspaces/bulk-import`).
5. If the change set spans **multiple** workspaces, inform the user: "Changes detected in **N** workspace(s): `<list>`. Proceed? (Yes/No)". Wait for confirmation. If declined, stop.
6. Store the change set, the change diff command, and the workspace names and paths for later steps.

---

## Step 3 — Capture baseline snapshot

Run `git status --porcelain` and save the output as the **baseline snapshot**, then remove
every change-set path from it. The baseline exists to identify files that were already
dirty for unrelated reasons; a file the change set names is part of this change, so it
must never be filtered out as pre-existing in Step 7.

---

## Step 4 — Create branch (only if on `main`) [APPROVAL GATE]

1. Run `git branch --show-current`.
2. **If on `main`:**
   a. Analyze the change diff (Step 2) to understand the changes.
   b. Generate a branch name:
      - **If `jira_key` is set:** `fix/<workspace>-<JIRA-KEY>-<short-slug>` (e.g., `fix/adoption-insights-RHDHBUGS-1934-keyboard-nav-dropdown`). This matches the existing repo convention and enables auto-linking in the Jira Development panel.
      - **If no Jira key:** `feat/<workspace>-<short-description>` (use `fix/` for bug fixes). For multiple workspaces, use a general description.
   c. Present the proposed branch name and a one-line summary. Wait for
      approval before creating the local branch.
   d. Run `git checkout -b <branch-name>`.
3. **If NOT on `main`:** skip branch creation. Inform the user: "Already on branch `<name>`, skipping branch creation."

---

## Step 5 — Build and validate each workspace

For **each** workspace from Step 2, run the following commands **sequentially** inside the workspace directory (e.g., `workspaces/bulk-import`). If any command fails, **stop immediately** and report the error with the failing command, workspace, and output.

### 5.0 — Pre-build cleanup

Remove stale `dist/` directories that may contain root-owned files from previous Docker or sudo builds:

```
rm -rf plugins/*/dist packages/*/dist
```

**If `EACCES` permission error occurs:** Set a flag `SKIP_BUILD_ALL=true`. Log a warning with the permanent fix:

```
echo "⚠️  Skipping yarn build:all — dist/ has root-owned files. Run 'sudo chown -R $(whoami) .' to fix ownership, then re-run."
```

Never use `sudo` in the skill itself — just tell the user how to fix it.

### 5.1–5.6 — Build pipeline

Run in order:

1. `yarn` — install dependencies
2. `yarn prettier:fix` — format code
3. `yarn tsc:full` — full TypeScript type check
4. `yarn build:all` — build all packages. **Skip this step if `SKIP_BUILD_ALL=true`** (from 5.0 fallback).
5. `yarn test --watchAll=false` — run tests (disable Jest watch mode)
6. `yarn build:api-reports:only` — generate/update API reports (depends on `tsc:full`, always runs)

---

## Step 6 — Generate changeset per workspace

For **each** workspace from Step 2, generate a changeset programmatically. Use the npm scope from the detected repo profile (Step 1).

1. From the change diff (Step 2), determine:
   - Which **plugins** under this workspace are affected (look at `plugins/*` only — **ignore `packages/*`**).
   - Within each plugin, only include it if changes touch published paths (`src/`, root `index.ts`, `config.d.ts`, `package.json`). Skip plugins with changes only in `dev/`, `tests/`, `__fixtures__/`, or stories.
   - Read each affected plugin's `package.json` for its npm package name.
   - Infer the semver bump: `patch` for fixes, `minor` for features, `major` for breaking changes.
   - **If no plugins have published-source changes, skip changeset generation for this workspace.**
2. Generate a short summary (1-2 sentences).
3. Generate a random changeset ID: `<adjective>-<noun>-<verb>` pattern, lowercase, 5-8 chars per word. Each workspace gets a unique ID.
4. Write the changeset file to `<workspace>/.changeset/<random-id>.md`:

```
---
'<package-name>': <bump-type>
---

<summary>
```

If multiple packages are affected, list each on its own YAML line.

**Do NOT run `yarn changeset` interactively.** Create files programmatically.

---

## Step 7 — Identify build-generated files

1. Run `git status --porcelain` for the **current snapshot**.
2. Compare against the **baseline snapshot** from Step 3.
3. Files only in the current snapshot are build-generated (created by Step 5 builds or Step 6 changesets).
4. Files already in the baseline are pre-existing — exclude them from staging. Change-set
   paths were removed from the baseline in Step 3, so they stay in the publication set.

---

## Step 8 — Stage the publication set [APPROVAL GATE]

1. Present one exact path list: the change set from Step 2 (already staged when it came
   from the index) plus the build-generated files from Step 7.
2. Ask the user for approval before staging. This local approval does not
   authorize any later external write.
3. Run `git add` for exactly the approved paths. Never use `git add -A` or a directory
   argument that could pick up a pre-existing dirty file.
4. Confirm with `git diff --cached --name-only` that the index now equals the approved
   list. This set is the content the Step 10 push carries.

---

## Step 9 — Commit [APPROVAL GATE]

1. Run `git diff --cached --stat` to review all staged changes.
2. Generate a commit message in conventional commit format: `<type>(<workspace>): <short description>` (e.g., `feat(bulk-import): add batch repository import support`).
3. **If `issue_source` is set**, append a `Fixes:` trailer in the commit body — but **only if the issue type is allowed for this repo profile**:
   - **rhdh-plugins:** Both Jira and GitHub issue URLs are allowed.
   - **community-plugins:** Only GitHub issue URLs are allowed. If `issue_source = jira`, do NOT add a `Fixes:` trailer (Jira info must never appear in community-plugins git history).

   Examples:
   - rhdh-plugins + Jira: `Fixes: https://redhat.atlassian.net/browse/RHDHBUGS-1934`
   - rhdh-plugins + GitHub: `Fixes: https://github.com/redhat-developer/rhdh-plugins/issues/607`
   - community-plugins + GitHub: `Fixes: https://github.com/backstage/community-plugins/issues/3574`
   - community-plugins + Jira: **no trailer** (omit entirely)

```
fix(adoption-insights): enable keyboard navigation in header date-range dropdown

Fixes: <issue_url>
```

4. Present the commit message and staged file summary. Wait for approval before
   committing. This local approval does not authorize push or PR creation.
5. Commit with the **`-s` flag** (Signed-off-by):

```
git commit -s -m "<subject>" -m "Fixes: <issue_url>"
```

Where `<issue_url>` is `jira_url` or `github_issue_url` depending on `issue_source`. If `issue_source` is null, or if the profile is community-plugins and `issue_source` is jira, omit the second `-m` flag.

---

## Step 10 — Push and create PR

Before the first external operation, follow the write gate in `SKILL.md`. State
every operation in the set with its target, exact command, and preview — the
push, the Git ref creation when the `screenrecordings` branch is missing, each
GitHub Contents upload, and the PR-create request — get approval for that stated
set, execute only that set, and report the outcome of every operation in it.

If recording uploads are required, their returned URLs materially change the
PR body. Use one approved set for the push and uploads, report its outcomes,
then state and get approval for a second set containing the exact PR title and
body. Without recordings, push and PR creation may share one approval only when
the full PR payload is already exact.

1. Push the branch:

```
git push -u origin HEAD
```

2. **Upload recording GIFs to dedicated `screenrecordings` branch [HARD GATE when `recordings` is provided]**:

   Skip this sub-step ONLY if the change handoff supplied no recordings. When recordings are provided, this sub-step is MANDATORY — do NOT skip, defer, or substitute with placeholder URLs.

   GIFs are uploaded to a dedicated `screenrecordings` branch on the user's fork — NOT the feature branch. This keeps the GIFs out of the PR diff and prevents them from landing on upstream `main` when the PR merges.

   a. Verify both local GIF files exist before proceeding:

   ```
   ls -la <recordings.before> <recordings.after>
   ```

   If either file is missing, STOP and inform the user.

   b. Determine the fork owner and repo name from the `origin` remote URL (e.g., `its-mitesh-kumar/rhdh-plugins`).
   c. Build the issue-specific upload path to avoid filename collisions across bug fixes:
   - If `issue_source = jira`: `ISSUE_ID = <jira_key>` (e.g., `RHDHBUGS-2911`)
   - If `issue_source = github`: `ISSUE_ID = <github_issue_number>` (e.g., `9834`)
   - If no issue context: `ISSUE_ID = $(date +%Y%m%d-%H%M%S)`

   Upload path: `screenrecordings/<workspace>-<ISSUE_ID>/before-fix.gif` and `.../after-fix.gif`.

   d. Check whether the `screenrecordings` branch exists on the fork before
   stating the first set of writes. If it is absent, resolve the exact
   default-branch SHA and state the branch-creation request as one of the
   operations in the same set as the uploads. First run only the read-only
   checks:

   ```
   if ! gh api repos/<fork-owner>/<repo-name>/git/ref/heads/screenrecordings --silent; then
     DEFAULT_SHA=$(gh api repos/<fork-owner>/<repo-name>/git/ref/heads/main --jq .object.sha)
   fi
   ```

   When the branch is absent, show this exact request and the resolved SHA as
   part of the stated set. Run it only after the user approves that set:

   ```
   gh api --method POST repos/<fork-owner>/<repo-name>/git/refs \
     -f ref=refs/heads/screenrecordings -f sha="$DEFAULT_SHA"
   ```

   e. For each GIF file (`recordings.before` and `recordings.after`), upload to the `screenrecordings` branch via the GitHub Contents API:

   ```
   GIF_B64=$(base64 -i <local-gif-path>)
   RESPONSE=$(gh api --method PUT \
     repos/<fork-owner>/<repo-name>/contents/screenrecordings/<workspace>-<ISSUE_ID>/<before|after>-fix.gif \
     -f message="docs: add <before|after>-fix recording for <workspace>-<ISSUE_ID>" \
     -f content="$GIF_B64" -f branch=screenrecordings)
   echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); url=d.get('content',{}).get('download_url',''); print('download_url:', url); exit(0 if url.startswith('https://raw.githubusercontent.com') else 1)"
   ```

   f. Extract the `download_url` from the JSON response — this is the `raw.githubusercontent.com` URL. **Verify** that the URL starts with `https://raw.githubusercontent.com/` — if it does not, the upload failed.
   g. Store both URLs: `before_gif_url`, `after_gif_url`.
   h. Echo a verification banner:

   ```
   echo "✅ GIF upload verified: before=$before_gif_url after=$after_gif_url"
   ```

   **If upload fails:** Retry once. If the retry also fails, log a warning and inform the user to manually drag GIFs into the PR description on GitHub. Use placeholder text `_(Recording upload failed — drag GIF manually)_` in the PR body instead of a broken image link. NEVER fabricate a URL that looks real but does not resolve.

3. Generate a PR title from the commit subject line.
4. Build the PR body from the detected repo profile template (Step 1). The body has conditional sections:
   - **`## Fixed`** — repo-dependent:
     - **rhdh-plugins:** include if `issue_source` is set. Jira: `- [<JIRA-KEY>](<jira_url>) — <jira_summary>`. GitHub: `- Fixes <github_issue_url>`.
     - **community-plugins:** include ONLY if `issue_source = github`. Use `- Fixes <github_issue_url>` (triggers auto-close). NEVER include Jira info — omit `## Fixed` entirely when `issue_source = jira`.
   - **`## UI before changes` / `## UI after changes`** — include only if the change handoff supplied recordings. Use the `raw.githubusercontent.com` URLs from sub-step 2 in the markdown: `![Before fix](<before_gif_url>)` / `![After fix](<after_gif_url>)`. **CRITICAL**: Both URLs MUST have been obtained from the GitHub Contents API response in sub-step 2. NEVER construct, guess, or fabricate these URLs. If sub-step 2 failed and you have no valid URLs, use the placeholder text from the failure path instead of a broken image link.
   - **`pr_description_extra`** — derive this from the handoff's root cause when present and insert it after the generated description paragraph.
   - **`## Test Plan`** — include only if the handoff supplied a test plan. Insert the markdown checklist as-is.
   - **`## Checklist`** — always present.
   - **`## Note`** — include when a bug-fix change handoff was supplied. Omit for a standalone publication request.
5. Invoke `/prose-editing` once on the completed reviewer-facing title and body
   in the **flavored** register. Preserve issue-closing syntax, headings,
   checkboxes, links, image URLs, and supplied test-plan text exactly. Use the
   edited result for the approval preview and `gh pr create`; the command is a
   transport layer and must not edit it again.
6. Create the PR using `gh pr create` with the repo-appropriate template. Use the upstream repo value for `--repo` and `main` for `--base`. Pass the body via HEREDOC:

```
gh pr create --repo <upstream-repo> --base main --title "<title>" --body "$(cat <<'EOF'
<assembled PR body>
EOF
)"
```

7. Capture and store the PR URL for Step 11.
8. Display the PR URL.

---

## Step 11 — Post-PR issue updates

**Skip this step entirely if `issue_source` is null.**

### If `issue_source` = `jira`

Prefer `/rhdh-jira-link`. It creates the remote link and the structured comment
in one pass, and it moves an RHDHPLAN Epic, Story, or Task to RHIDP first when
that is needed. Invoke it by name with the normalized key, the PR URL, and the
title `<repo-short> #<pr_number>: <PR_title>`; it reports the effective key,
which may differ from the one you passed if the issue moved project.

Then invoke `/rhdh-jira-update` with the effective key for the remaining outcome:

1. transition to `Review` when that transition is currently available.

If `/rhdh-jira-link` is unavailable, invoke `/rhdh-jira-update` for all three
outcomes instead — comment `PR submitted: <PR_URL>`, transition to `Review`, and
add `<PR_URL>` as a remote link titled `GitHub PR: <PR_title>`.

Either way the Jira owner states each write with its target and exact command,
waits for approval, and reports the outcome of every operation. Do not call Jira
REST, MCP, GraphQL, or `acli` here. If neither skill is available, keep the
successful PR result and report the three outstanding outcomes so a human can
finish them.

### If `issue_source` = `github`

State a new set of writes now that `<PR_URL>` is known. Its only operation is the
GitHub issue comment below: show the exact command, repository, issue number, and
body, get approval for that stated operation, execute it, and report its outcome
alongside the PR result.

1. **Comment** on the GitHub issue:

   ```
   gh issue comment <github_issue_number> --repo <github_issue_repo> --body "Fix submitted: <PR_URL>"
   ```

2. **Auto-close** — no explicit action needed. The `Fixes <github_issue_url>` in the PR body (Step 10) causes GitHub to automatically close the issue when the PR merges.

**If the comment fails:** Log a warning and continue:

```
echo "⚠️  Could not comment on #<github_issue_number>. Add manually: <PR_URL>"
```

---

## Gotchas

- **Fork workflows:** The user may have `origin` pointing to their fork and `upstream` to the canonical repo. Detection checks all remotes, not just `origin`. The `--repo` flag on `gh pr create` targets the canonical upstream regardless of which remote `origin` points to.
- **Multiple workspaces:** Each workspace gets its own build cycle (Step 5) and changeset (Step 6). The commit (Step 9) bundles everything into one commit. If the user prefers separate PRs per workspace, they should stage and run the skill once per workspace.
- **Changeset ID collisions:** Each workspace must get a unique random ID. If generating for multiple workspaces in one run, track used IDs and avoid duplicates.

## Change handoff mapping (optional)

When another skill invokes `/rhdh-pr-create`, it may hand off a verified change
with some of these values already resolved. They override inferred defaults; skip
discovery for any value the handoff already supplies, after validating it against
the checkout.

| Value | Used in | Description |
|-------|---------|-------------|
| File list | Steps 2, 3, 7, 8 | Paths that make up the change. The producer never stages, so these arrive unstaged; they are the change set, are excluded from the baseline, and are staged with the build-generated files at the Step 8 gate. |
| Change summary | Steps 6, 9 | Summary used for the changeset text and commit subject. |
| Issue source | Steps 1.5, 9, 10, 11 | `jira` or `github` — determines which issue-specific logic to follow |
| `jira_key` | Steps 1.5, 4, 9, 10, 11 | Pre-resolved Jira issue key (skip Step 1.5 detection). Jira only. |
| `jira_url` | Steps 9, 10, 11 | Full Jira browse URL. Jira only. |
| `jira_summary` | Step 10 | Issue summary for the PR body `## Fixed` section. Jira only. |
| `github_issue_number` | Steps 1.5, 10, 11 | GitHub issue number. GitHub only. |
| `github_issue_url` | Steps 9, 10, 11 | Full GitHub issue URL (e.g., `https://github.com/redhat-developer/rhdh-plugins/issues/607`). GitHub only. |
| `github_issue_repo` | Steps 10, 11 | `owner/repo` (e.g., `redhat-developer/rhdh-plugins`). GitHub only. |
| `github_issue_title` | Step 10 | Issue title for the PR body `## Fixed` section. GitHub only. |
| Recordings | Step 10 | Local before and after GIF paths; this workflow uploads them via the GitHub Contents API and uses the resulting `raw.githubusercontent.com` URLs. Absent in no-e2e mode. |
| Root cause | Step 10 | Extra text inserted after the description. |
| Test plan | Step 10 | Markdown checklist for the `## Test Plan` section (e.g., `- [ ] Open menu` / `- [ ] Verify scrollbar on hover`). |

`/rhdh-plugin-bug-fix` is the primary producer. It reports the issue fields,
optional full-e2e recordings, root cause, and test plan in the conversation.

<reference_index>

## Reference Index

| Reference | Load when... |
|-----------|-------------|
| `references/repo-profiles.md` | Always — at the start of every invocation (Step 1) |
| `references/jira-input.md` | When parsing Jira input and building the Jira handoff |
| `references/github-input.md` | When resolving GitHub issue context (Step 1.5, `issue_source` = `github`) |

</reference_index>
