---
name: rhdh-feature-docs
description: Generate actual RHDH documentation content (AsciiDoc) for features by analyzing Jira tickets, PRs, and existing docs. Produces ready-to-use documentation files following RHDH docs repository structure, or identifies specific updates needed to existing documentation. Use when a user provides a Jira feature link and wants documentation content generated or updated.
compatibility:
  requires:
    - acli (Atlassian CLI) installed and authenticated
    - git (for cloning RHDH docs repository)
    - GitHub CLI (gh) for fetching PR details (optional)
    - Python 3.7+ (standard library only, no external packages needed)
---

# RHDH Feature Documentation Generator

This skill generates **actual documentation content** for Red Hat Developer Hub (RHDH) features in AsciiDoc format, following the RHDH documentation repository structure. It analyzes Jira features, linked PRs, and existing documentation to produce ready-to-use documentation files or specific updates to existing docs.

## When to Use This Skill

Use this skill when:
- A user provides a Jira feature/issue link from `redhat.atlassian.net` and wants **documentation content generated**
- Someone asks to "document this feature" or "write docs for" an RHDH feature
- You need to **generate actual documentation updates** to existing RHDH docs (not just analysis)
- A feature owner wants **ready-to-use AsciiDoc documentation** for their feature
- Documentation team needs **actual documentation content** following RHDH structure

**What this skill produces:**
- ✅ **Actual AsciiDoc documentation files** ready for RHDH docs repository
- ✅ **Specific updates/diffs** to existing documentation (what to change, where)
- ✅ **Release notes content** (ready to publish)
- ✅ **TechDocs content** (mkdocs.yml + markdown files for Backstage plugins)

**What this skill does NOT produce:**
- ❌ Meta-documents about documentation planning
- ❌ Project management documents about doc work
- ❌ Analysis reports without actionable documentation content

## Prerequisites

### Required Tools

1. **acli (Atlassian CLI)**
   - Download from: https://bobswift.atlassian.net/wiki/spaces/ACLI/overview
   - Verify installation: `acli --version`

2. **Jira Authentication**
   - Create API token: https://id.atlassian.com/manage-profile/security/api-tokens
   - Authenticate acli:
     ```bash
     acli jira auth login --site redhat.atlassian.net --email <your-email> --token
     ```
   - Verify: `acli jira project list --recent 1`

3. **Validation**
   - Run the setup script to verify everything is configured:
     ```bash
     python3 "$SKILL/scripts/setup_acli.py"
     ```
   - All checks should pass before using the skill

For detailed installation, authentication, OS-keyring, and troubleshooting steps,
read `references/acli-setup.md`.

### Optional Tools

- `gh` CLI for enhanced GitHub PR analysis
- Python 3.7+ available on `PATH` (the `jira_acli.py`, `fetch_rhdh_docs.py`, and `setup_acli.py` scripts use only the standard library)

## Output Modes

The skill generates **actual documentation content** in different formats based on the request:

### 1. RHDH Product Documentation (Default - AsciiDoc)
**User says:** "Document this feature", "Write docs for RHDHPLAN-1234", "Generate documentation for this"  

**What you generate:**
- **NEW feature:** Complete AsciiDoc documentation following RHDH structure
  - Master file (assembly)
  - Concept modules (con-*.adoc)
  - Procedure modules (proc-*.adoc)
  - Reference modules (ref-*.adoc)
  - Proper attributes, cross-references, includes
  
- **EXISTING feature:** Specific updates to existing docs
  - Which files to update
  - Exact sections to add/modify (with AsciiDoc content)
  - New modules to create (full content)
  - Updated cross-references

**Output format:** Ready-to-commit AsciiDoc files following RHDH docs repo structure

### 2. Release Notes Content
**User says:** "Generate release notes for...", "What's the release note for...", "Write release notes for RHDHPLAN-1234"  

**What you generate:**
- Release note type classification (Feature, Enhancement, Bug Fix, etc.)
- User-facing title (5-10 words)
- Description (1-3 paragraphs, ready to publish)
- Action required section (if applicable)
- Migration/upgrade notes (for breaking changes)

**Output format:** Markdown or AsciiDoc release notes content (ready to paste into release notes file)

### 3. TechDocs (Backstage Plugin Documentation - Markdown)
**User says:** "Generate tech docs for...", "Create techdocs for...", "Generate backstage docs for..."  

**First ask for the existing plugin TechDocs directory** (see Step 0). If it
exists, **update** those docs for this feature. If it does not exist, **create**
TechDocs for the whole plugin the feature builds on — not just this feature.

**What you generate:**
- `mkdocs.yml` configuration
- Complete Markdown documentation files:
  - `docs/index.md`
  - `docs/installation.md`
  - `docs/configuration.md`
  - `docs/usage.md`
  - Additional files as needed (api.md, troubleshooting.md, migration.md)

**Output format:** Complete TechDocs structure ready to copy to plugin repository

### 4. Documentation Update Summary (Analysis Mode)
**User says:** "What docs need updating for...", "Analyze documentation needs for...", "What documentation is required for..."  

**What you generate:**
- Which existing docs need updates (with file paths)
- What new documentation is needed
- Gaps in current documentation
- Recommended structure
- **But NO actual documentation content** - this mode is for analysis only

**Output format:** Markdown summary of documentation requirements

**Important:** Default to generating **actual documentation content** unless user specifically asks for analysis/summary only.

## Workflow

### Resolving paths

This skill's helper scripts live under its own `scripts/` directory, and its
templates under `references/`. Resolve that skill root once and reference bundled
files through it — never hard-code an install path:

```bash
SKILL="$(cd "$(dirname "$0")" && pwd)"   # or the absolute path to this skill root
python3 "$SKILL/scripts/jira_acli.py" ...
```

Generated documentation is written to a working directory in the **current
working directory** (where the user invoked the skill), not inside the skill:
`./rhdh-feature-docs-output/<ISSUE-KEY>/`. If the user names a target path, use
that instead.

### Step 0: Locate Existing TechDocs (TechDocs Mode Only)

**If user requested TechDocs generation:**

**Always ask the user for the directory of the existing TechDocs for the plugin
this feature covers**, unless they already gave a path in their request. Ask
plainly, for example: "What is the directory of the existing TechDocs for the
plugin this feature covers? If TechDocs don't exist yet, say so." The presence or
absence of that directory selects the mode:

1. **Directory provided → UPDATE mode.** TechDocs already exist for the plugin.
   - Read the existing TechDocs at that path: `mkdocs.yml`, the `docs/` tree, and
     `nav`. Understand the plugin's current structure, page set, and style.
   - Update those docs to cover this feature: extend or edit the affected pages
     (installation, configuration, usage, etc.), add pages only where the feature
     needs them, and keep the existing structure, tone, and `nav` conventions.
   - Scope the change to the feature — do not rewrite unrelated pages.

2. **No directory (user says it doesn't exist) → CREATE mode for the whole
   plugin.** Absence means the plugin has no TechDocs yet.
   - Generate TechDocs for the **entire plugin the feature builds on**, not just
     this one feature. Identify the plugin from the feature (Jira components,
     labels, and the plugin repos in the linked PRs from Step 3), then document
     the plugin end to end: overview, installation, configuration, usage, and
     references — with this feature included as part of that whole.
   - If the plugin is ambiguous, ask the user which plugin/repo to document.

**Output location (both modes):** generate into the skill output directory first
for review — `./rhdh-feature-docs-output/<ISSUE-KEY>/techdocs/` — then provide a
copy command targeting the user's plugin directory when they gave one. In UPDATE
mode, mirror the existing file layout so the copy overlays cleanly.

**UPDATE mode — offer to update the checkout in place.** When the path the user
gave is a local checkout of the plugin (UPDATE mode), editing the existing
`docs/` files directly is usually what they want: the changes land in the real
file layout, small edits to large pages (e.g. inserting one cross-link paragraph)
apply without overlaying the whole file, and the result is a reviewable `git diff`
in their repo. Offer this, and when they accept, apply the updated and new
TechDocs files straight into that directory instead of only staging to the review
dir. Before writing in place:

- Confirm it is a git working tree and check `git status` — the tree must be clean
  (no uncommitted changes you might clobber). If it is dirty, stop and ask.
- Confirm the checkout is on a feature branch, not `main`/`master`/a release
  branch. If it is on a protected branch, ask the user to create a branch first.
- Edit and add only the files this feature needs; never delete or rewrite
  unrelated pages, and preserve the existing structure, tone, and `nav`.
- **Do not commit and do not push.** Leave the changes staged as a working-tree
  diff for the user to review; committing is theirs to do.

Still write the same files to the review dir as a paper trail so the output is
reproducible even when applied in place.

**Store this information** - you'll need it in Step 7 for create vs update mode and copy instructions.

### Step 1: Gather Issue Information

When the user provides a Jira URL (e.g., `https://redhat.atlassian.net/browse/RHDHPLAN-1187`):

1. Extract the issue key from the URL (e.g., `RHDHPLAN-1187`)

2. Use the `jira_acli.py` script to fetch issue details:
   ```bash
   python3 "$SKILL/scripts/jira_acli.py" RHDHPLAN-1187 --children
   ```

3. This will return JSON with:
   - Issue title, description, status
   - **Issue type** (`fields.issuetype.name` - e.g., "Feature", "Epic", "Outcome")
   - All fields including custom fields
   - Child issues (with full details via JQL search)
   - Issue links

4. **Determine the correct issue type terminology:**
   
   The RHDH Jira project uses this hierarchy (from highest to lowest):
   - **Outcome** (hierarchyLevel: 3) - Strategic objectives
   - **Feature** (hierarchyLevel: 2) - Capabilities delivering business value
   - **Epic** (hierarchyLevel: 1) - Large user stories
   - **Story/Task** (hierarchyLevel: 0 or -1) - Implementation work
   
   **IMPORTANT:** Check `fields.issuetype.name` in the JSON response and use the **actual issue type** throughout your documentation. Examples:
   - If `issuetype.name` = "Feature" → Use "Feature:", "feature owner", "feature description"
   - If `issuetype.name` = "Epic" → Use "Epic:", "epic owner", "epic description"
   - If `issuetype.name` = "Outcome" → Use "Outcome:", "outcome owner", "outcome description"
   
   **Common pattern in RHDH:** Most items are **Features**, not Epics. Always verify from the JSON data.

5. Parse the JSON output and extract the key information:
   - Overview, goals, requirements from description
   - Child issues with their details
   - Status and metadata
   - Issue owner/assignee

### Step 2: Analyze Child Issue Details

If the issue has child issues (already fetched in Step 1 via `--children` flag):

1. The `jira_acli.py` script automatically discovers and enriches child issues using JQL search
2. Each child includes full details: title, description, status, linked PRs, issue type
3. Parse child issues for:
   - Implementation details
   - User stories and acceptance criteria
   - Linked GitHub PRs

**Note:** JQL search automatically discovers all children via `parent = {issue_key}` query. No manual URL construction needed.

### Step 3: Analyze Linked GitHub PRs

First **collect** the PR URLs, then fetch each PR's details.

Jira stores pull request links in two different places, so a single field dump
misses some:

- **Remote / web links** — the "Git Pull Request" panel. These are **not**
  returned by `acli workitem view`; they require the Jira REST remotelink
  endpoint.
- **Issue content** — PR URLs mentioned in the description, comments, or custom
  fields.

Use `--pull-requests` to walk the whole feature tree (the feature and its
descendants via the `parent` field) and merge both sources, deduplicated, with
where each PR was found (`web-link`, `comment`, `description`, or `field`):

```bash
python3 "$SKILL/scripts/jira_acli.py" RHDHPLAN-1187 --pull-requests
```

To inspect only the remote/web links for a single issue:

```bash
python3 "$SKILL/scripts/jira_acli.py" RHIDP-14170 --remote-links
```

The remote-link endpoint needs `JIRA_API_TOKEN` in the environment (site and
email are resolved from `acli jira auth status`, or overridden with
`JIRA_BASE_URL` / `JIRA_EMAIL`). The token is read only from the environment and
is never printed. Without it, `--pull-requests` still returns PRs found in issue
content and prints a note that web links were skipped.

> **Token safety — never print `JIRA_API_TOKEN`.** The scripts read it straight
> from the environment; you never need to display, echo, or interpolate it. To
> check whether it is set, test presence only — never expand its value:
>
> ```bash
> [ -n "$JIRA_API_TOKEN" ] && echo "token present" || echo "token missing"
> ```
>
> Do **not** use `echo "$JIRA_API_TOKEN"`, `echo "${JIRA_API_TOKEN:-no}"`, or any
> form that substitutes the value — `${VAR:-default}` and `${VAR:=default}` expand
> to the token itself when it is set. Only `${VAR:+set}` (or `-n`/`-z` tests) are
> safe. The same rule applies to any secret: never place it in a command that
> prints, in logs, in output files, or in the generated docs.

Then, for each GitHub PR URL found, analyze it for **documentation-relevant
signals only**. Do **not** read complete file contents or the full diff — that is
noise for docs work and burns context. Look at four things:

**Tooling:** the `gh` commands below are the convenient path when `gh` is
installed **and authenticated** (`gh auth status`). `gh` is optional — if it is
absent or not logged in, use the public GitHub REST/raw API over `curl` instead
(no auth needed for public repos). For a PR at
`https://github.com/<org>/<repo>/pull/<N>`:

- Description/title → `curl -s https://api.github.com/repos/<org>/<repo>/pulls/<N>` (read `title`, `body`)
- Commits → `curl -s https://api.github.com/repos/<org>/<repo>/pulls/<N>/commits`
- Changed files → `curl -s https://api.github.com/repos/<org>/<repo>/pulls/<N>/files` (each entry has `filename`, `patch`)
- A specific changed file's content → `https://raw.githubusercontent.com/<org>/<repo>/<branch>/<path>`

Filter the file list to docs/config paths yourself (the API returns all files);
the `-- '*.md'` path filters shown below are a `gh` convenience.

1. **PR description** — the summary of intent and behavior:
   ```bash
   gh pr view <pr-url> --json title,body
   ```

2. **PR commits** — commit messages for what changed and why:
   ```bash
   gh pr view <pr-url> --json commits
   ```

3. **Markdown / docs files** — the changed file list, filtered to docs:
   ```bash
   gh pr view <pr-url> --json files
   ```
   Keep only `*.md`, `*.adoc`, and `docs/` or `README` paths. For **those files
   only**, inspect the change:
   ```bash
   gh pr diff <pr-url> -- '*.md' '*.adoc'
   ```

4. **Config-related files, only if changed** — from the same file list, keep
   config paths (for example `app-config*.yaml`, `values.yaml`, `*-cr.yaml`,
   CRDs, `*.config.*`, `plugins*.yaml`). Inspect the diff for those paths only:
   ```bash
   gh pr diff <pr-url> -- 'app-config*.yaml' 'values.yaml' '*cr.yaml'
   ```
   Use these to document new or changed configuration keys, defaults, and CR
   fields.

Skip source code, tests, lockfiles, and generated files — do not open their
diffs. Extract only: what the feature does (description/commits), which docs
changed, and which configuration surface changed.

**Fold PR findings directly into the deliverables.** Do not create a separate
"PR-verified" file. The PRs are the authoritative source, so use them to write the
real content:

- Resolve TODOs with verified values. Prefer a value read from a PR over a guess
  from the Jira description; leave a `# TODO` only where **no** PR resolves the
  detail.
- When a PR contradicts the Jira description or an assumption, use the PR and note
  the correction inline where it helps a reader.
- Include a short **PR evidence** table in the generated `README.md` — one row per
  PR that informed the docs: the source issue key, the PR link, and the one-line
  fact it establishes (config key, route, attribute, RBAC name, etc.).
- Cite the exact config keys, RBAC permission names, routes, and attribute
  names/values as found in the diffs, not paraphrases.

### Step 4: Check Existing RHDH Documentation

To decide **which** RHDH documentation section a feature belongs in (Discover, Get
started, Install, Configure, Integrate, Administer, and so on), consult
`references/rhdh-docs-structure.md`.

Ask the user if this feature already has documentation or is entirely new:

- **If it's new:** Create documentation from scratch following RHDH documentation structure
- **If it exists:** Ask for the topic/title name or search keyword

To fetch existing docs from the official GitHub repository:

1. **List available documentation titles:**
   ```bash
   python3 "$SKILL/scripts/fetch_rhdh_docs.py" --list
   ```

2. **Search for documentation by keyword:**
   ```bash
   python3 "$SKILL/scripts/fetch_rhdh_docs.py" --search "plugin"
   python3 "$SKILL/scripts/fetch_rhdh_docs.py" --search "configure"
   ```

3. **Read a specific title with all its modules:**
   ```bash
   python3 "$SKILL/scripts/fetch_rhdh_docs.py" --title "extend_installing-and-viewing-plugins-in-rhdh" --with-modules
   ```

**Note:** The script fetches docs from the `release-1.10` branch by default (latest release as of 2026-09-02). Use `--branch <name>` to fetch from a different release.

This returns AsciiDoc content from the official RHDH documentation source repository, which you'll use as a foundation for updates.

### Step 5: Generate Release Notes

Before creating the full documentation, determine the appropriate release note type and generate release notes text.

**Read the release notes guide:**
```bash
cat "$SKILL/references/release-notes-guide.md"
```

**Determine Release Note Type:**

Analyze the issue to identify the release note type:

1. **Check issue title and type:**
   - "Add", "New", "Introduce" → **Feature**
   - "Improve", "Enhance", "Optimize" → **Enhancement**
   - "Fix", "Bug" → **Bug Fix**
   - "Deprecate" → **Deprecated functionality**
   - "Remove", "Sunset" → **Removed functionality**
   - "CVE-" or security labels → **CVE**
   - Preview/experimental labels → **Developer Preview** or **Tech Preview**

2. **Check issue description:**
   - Look for "Release Enablement/Demo" section for suggested release note text
   - Check "Customer Considerations" for user impact
   - Identify if it's user-facing or internal-only

3. **Default logic:**
   - User-facing changes → **Feature** or **Enhancement**
   - Internal-only changes → **Release notes not required**

**Generate Release Notes:**

Write the release note using the type-by-type templates and worked examples in
`references/release-notes-guide.md`. Match the note to the type you determined
above, and ground the description in the PR-verified behavior (Step 3).

### Step 6: Generate Actual Documentation Content

Generate **ready-to-use documentation content** in the appropriate format based on what exists and what's needed.

#### Option A: NEW Feature Documentation (AsciiDoc for RHDH docs repo)

If existing RHDH documentation search returned **no matches**, create complete new documentation following RHDH structure. For the standard section layout (overview, goals, prerequisites, procedures, reference, and so on), follow `references/doc-structure-template.md`.

For each file you list, add a repo link on the line under its heading. A NEW file
does not exist yet, so link the target directory with `tree` (not `blob`):
`🔗 create in https://github.com/redhat-developer/red-hat-developers-documentation-rhdh/tree/[branch]/[dir]`. Any existing file you also touch (for example, the book
`master.adoc` you add an `include::` to) links with `blob` to the file itself.

For the AsciiDoc module skeletons (assembly, concept, procedure, and reference
with the correct `:_mod-docs-content-type:` metadata) and the content sources for
each, see the **AsciiDoc modular documentation skeletons** section of
`references/doc-structure-template.md`. Fill them with values verified from the
linked PRs (Step 3), not placeholders.

#### Option B: UPDATE Existing Documentation

If existing docs were found, provide **specific updates**:

**Format:** (state the repo base once at the top of the output, then link every
file on the line directly under its `## File:` heading)

```markdown
Repo base: https://github.com/redhat-developer/red-hat-developers-documentation-rhdh/blob/[branch]/

## File: titles/[category]/[file-name].adoc
🔗 https://github.com/redhat-developer/red-hat-developers-documentation-rhdh/blob/[branch]/titles/[category]/[file-name].adoc

### Section to Update: "[Section Title]" (line XX)

**Change Type:** [Add new section | Update existing content | Replace section]

**Current Content:**
```asciidoc
[Existing content if updating/replacing]
```

**New/Updated Content:**
```asciidoc
[New AsciiDoc content to add or replacement content]
```

**Rationale:** [Why this update is needed based on the feature]

---

## File: modules/[category]/[module-name].adoc
🔗 https://github.com/redhat-developer/red-hat-developers-documentation-rhdh/blob/[branch]/modules/[category]/[module-name].adoc

### Section to Update: "Prerequisites" (line YY)

**Change Type:** Add new prerequisite

**Current Content:**
```asciidoc
.Prerequisites
* Existing prerequisite 1
* Existing prerequisite 2
```

**New Content:**
```asciidoc
.Prerequisites
* Existing prerequisite 1
* Existing prerequisite 2
* [New prerequisite from this feature]
```

**Rationale:** [Why needed]
```

**Provide updates for:**
1. Which files need changes (with exact paths)
2. Which sections to modify (with line numbers if possible)
3. Exact AsciiDoc content to add/change
4. New modules to create (full content)
5. New assemblies to create (if needed)
6. Updated include statements
7. New attributes to define

#### Key Principles for RHDH Documentation

1. **Follow RHDH patterns**: Match structure/style of existing similar docs
2. **Use AsciiDoc attributes**: Define and use attributes from `artifacts/attributes.adoc`
3. **Modular structure**: Separate concepts, procedures, and references
4. **Concrete examples**: Use actual code from PRs, not placeholder examples
5. **User-focused**: Write for the target persona (developer, admin, operator)
6. **Proper metadata**: Include `_mod-docs-content-type` and `_mod-docs-category`
7. **Cross-references**: Use proper AsciiDoc xref syntax
8. **Verification steps**: Include how users verify the feature works
9. **Link every referenced file to the repo**: Whenever you cite a docs file
   (for example, a `### File:` heading), add the GitHub URL on the next line so it
   is one click to open. Use the branch you fetched from (default `release-1.10`).
   - Existing file → `blob`:
     `https://github.com/redhat-developer/red-hat-developers-documentation-rhdh/blob/<branch>/<path>`
   - NEW file (does not exist yet) → link the target directory with `tree`:
     `https://github.com/redhat-developer/red-hat-developers-documentation-rhdh/tree/<branch>/<dir>`
   State the repo base once near the top of the output, then link each file.
10. **Ground content in PRs, not guesses**: When a linked PR establishes a fact
    (config key, RBAC name, route, attribute, default), use that value verbatim
    and cite the PR. Keep a `# TODO` only where no PR resolves the detail. Record
    the evidence in a short PR table in the generated `README.md`; do not emit a
    separate PR-verified file.

#### File Renaming Best Practices

**IMPORTANT:** When updating documentation for rebranding or name changes:

**Only rename files if the OLD name appears in the filename itself.**

**Example - Feature rebrand from "Lightspeed" to "Intelligent Assistant":**

✅ **YES - Rename these files:**
```
integrate_interacting-with-developer-lightspeed-for-rhdh.adoc
→ integrate_interacting-with-intelligent-assistant-for-rhdh.adoc
(filename contains "lightspeed" - rename it)
```

❌ **NO - Keep these filenames (update content only):**
```
con-chat-assistance-with.adoc
(generic filename, no brand name - keep it, just update content inside)

con-architecture-for-your-ai-backend-deployment.adoc
(generic filename - keep it, just update content inside)
```

**Why keep generic filenames:**
- More stable - won't need changing if branding changes again
- Cleaner Git history - no unnecessary renames
- Include paths stay stable across versions
- Only the content (IDs, attributes, text) is brand-specific

**What to update in files with generic names:**
- Update IDs: `[id="chat-assistance-with-lightspeed_{context}"]` → `[id="chat-assistance-with-intelligent-assistant_{context}"]`
- Update titles: `= Chat with {old-attribute}` → `= Chat with {new-attribute}`
- Update body content: Replace old attribute references with new ones
- Update image references: `old-brand-screenshot.png` → `new-brand-screenshot.png`

**Rule of thumb:** If you wouldn't have created the file with the old brand name in the filename, don't rename it.

### Step 7: Save Documentation Files

**Create output directory:**
```bash
mkdir -p ./rhdh-feature-docs-output/<ISSUE-KEY>
```

**Save generated content based on output mode:**

#### For RHDH Product Documentation (AsciiDoc):

Save complete, ready-to-use AsciiDoc files:

```
./rhdh-feature-docs-output/<ISSUE-KEY>/
├── assembly-[feature-name].adoc           # Master assembly file
├── con-[feature-concept].adoc             # Concept module(s)
├── proc-[feature-procedure].adoc          # Procedure module(s)
├── ref-[feature-reference].adoc           # Reference module(s) (if needed)
└── INTEGRATION-GUIDE.md                   # How to integrate into rhdh-docs repo
```

**The INTEGRATION-GUIDE.md should include:**
- Which directory to place files in the rhdh-docs repo
- New attributes to add to `artifacts/attributes.adoc`
- Which master title file to update (if updating existing docs)
- New include statements to add
- Build/preview instructions

**Example:**
```markdown
# Integration Guide for RHDHPLAN-1234

## Files to Copy to rhdh-docs Repository

1. Copy `assembly-intelligent-assistant-config.adoc` to:
   - `titles/integrate/assembly-intelligent-assistant-config.adoc`

2. Copy modules to:
   - `modules/integrate/con-intelligent-assistant-overview.adoc`
   - `modules/integrate/proc-configure-intelligent-assistant.adoc`

## Attributes to Add

Add to `artifacts/attributes.adoc`:
```asciidoc
:ia-brand-name: Red Hat Developer Hub intelligent assistant
:ia-short: RHDH intelligent assistant
```

## Update Master Title File

In `titles/integrate/integrate_interacting-with-intelligent-assistant-for-rhdh.adoc`, add:
```asciidoc
include::assemblies/integrate/assembly-intelligent-assistant-config.adoc[leveloffset=+1]
```

## Preview Documentation

```bash
cd rhdh-docs
make preview
# Open http://localhost:8080
```
```

#### For Release Notes:

Save release notes content:
```
./rhdh-feature-docs-output/<ISSUE-KEY>/
└── release-notes.md                       # Ready-to-paste release note
```

#### For Documentation Updates:

Save update instructions:
```
./rhdh-feature-docs-output/<ISSUE-KEY>/
└── documentation-updates.md               # Specific updates to existing docs
```

**Format:** File paths, sections to update, exact diffs/changes
   
   **For TechDocs:**
   
   Use the templates in `references/techdocs-template.md` for `mkdocs.yml` and the
   standard page set. Generate Backstage TechDocs structure in:
   ```
   ./rhdh-feature-docs-output/<ISSUE-KEY>/techdocs/
   ├── mkdocs.yml
   └── docs/
       ├── index.md
       ├── installation.md
       ├── configuration.md
       ├── usage.md
       └── [additional files based on epic content]
   ```
   
   **TechDocs Generation Steps:**
   
   a. Determine create vs update mode:
      - **If user provided target directory** in Step 0:
        - Check if `{target-path}/docs/` exists
        - If exists → **Update mode** (read existing, merge new content)
        - If doesn't exist → **Create mode** (generate fresh structure)
      - **If no target directory provided** (default):
        - **Create mode** (generate fresh structure)
        - User will copy to their plugin directory later
   
   b. Generate mkdocs.yml using the template in
      `references/techdocs-template.md` (set `site_name`, `repo_url`,
      `edit_uri`, and the `nav` from the plugin/feature context).

   c. Generate docs/index.md (always):
      - Map epic title → page title
      - Map Feature Overview → Overview section
      - Map Goals → Features/Capabilities section
      - Map User Stories → Use Cases section
      - Include quick start if available
   
   d. Generate docs/installation.md (if epic has setup/install info):
      - Map Prerequisites → Prerequisites section
      - Map Dependencies → Dependencies section
      - Map setup steps → Installation Steps
      - Include dynamic vs static plugin installation if relevant
   
   e. Generate docs/configuration.md (if epic has config details):
      - Map Configuration requirements → Configuration Options
      - Extract app-config.yaml examples
      - Map Environment variables → Environment Variables section
   
   f. Generate docs/usage.md (from user stories/workflows):
      - Map User Stories → Usage Examples
      - Map Expected User Experience → Step-by-step guides
      - Map Workflows → Common Tasks section
   
   g. Conditional files (generate only if epic content supports):
      - docs/api.md - If epic mentions APIs, extension points, interfaces
      - docs/development.md - If epic has development/contributing details
      - docs/troubleshooting.md - If epic has known issues, feature risks
      - docs/migration.md - If epic is an update/migration to existing feature
   
   h. Check catalog-info.yaml (only if target directory was provided):
      - **If target directory provided:**
        - Read `{target-path}/catalog-info.yaml` if it exists
        - Check for `backstage.io/techdocs-ref` annotation
        - If missing, note to user: "Add this to catalog-info.yaml: `backstage.io/techdocs-ref: dir:.`"
        - Don't modify catalog-info.yaml automatically (user should review)
      - **If no target directory:**
        - Skip this step - user will handle catalog-info.yaml when they copy files
   
   i. Save to skill output directory (always):
      - Files always saved to: `./rhdh-feature-docs-output/<ISSUE-KEY>/techdocs/`
      - This location is consistent for both cases (with/without target directory)
   
   j. Present to user:
      - List all files generated
      - Show directory structure
      - **If target directory provided:**
        - **UPDATE mode with a local checkout:** per Step 0, offer to apply the
          updated and new files directly into `{target-path}` instead of only
          copying. When the user accepts, first verify the tree is a clean git
          working tree on a non-`main`/non-release branch, then edit/add only the
          feature's files in place — do not commit or push. If they decline, fall
          back to the copy command below.
        - Provide specific copy command: `cp -r ./rhdh-feature-docs-output/<ISSUE-KEY>/techdocs/* {target-path}/`
        - Note if catalog-info.yaml needs updating
        - Explain update vs create mode used
      - **If no target directory (default):**
        - Show location: `./rhdh-feature-docs-output/<ISSUE-KEY>/techdocs/`
        - Provide generic copy command: `cp -r ./rhdh-feature-docs-output/<ISSUE-KEY>/techdocs/* /path/to/your/plugin/`
        - Remind user to add `backstage.io/techdocs-ref: dir:.` to catalog-info.yaml after copying
        - Note: "Copy these files to your plugin directory when ready"

   **IMPORTANT:** All files for a single Jira ticket MUST go in the same directory. This keeps documentation organized and easy to find.

3. Present the documentation to the user based on what was generated:
   - **Main documentation** - Full feature docs
   - **Release notes** - Type and text for release notes
   - **Summary** - Sources analyzed and gaps identified

4. Ask for feedback:
   - Is the structure appropriate?
   - Is the release note type correct?
   - Should any content be expanded or clarified?
   - Are there any missing sections?

5. If this is updating existing RHDH docs, identify:
   - Which sections of the existing docs should be updated
   - What new sections need to be added
   - Whether this should be a new page or integrated into an existing one

## Tips for High-Quality Documentation

**Be specific and actionable:** Use concrete examples from the PRs and epic rather than generic descriptions.

**Preserve technical accuracy:** When pulling configuration examples from PRs, use the actual code/YAML, not paraphrased versions.

**Connect to user goals:** Frame features in terms of what users can accomplish (from epic goals) rather than just technical implementation.

**Use the epic's language:** The epic description often contains carefully crafted messaging about the feature - preserve that where appropriate.

**Note gaps proactively:** If information is missing (e.g., no PRs linked, incomplete epic description), call it out and ask the user for clarification rather than making assumptions.

**Check for documentation in PRs:** Many PRs include README updates or docs/ changes that contain valuable examples and explanations - prioritize those.

**Polish the prose before presenting:** Once the release notes and any narrative
documentation (concept abstracts, overviews, descriptions) are drafted, invoke
`/prose-editing` once on that prose. It returns the same content with grammar,
tone, and clarity tightened. Preserve technical literals — attribute names,
IDs, AsciiDoc directives, code, YAML, commands, and cross-references — exactly;
prose-editing only touches the surrounding narrative, not the structured content.

## Handling Edge Cases

**No linked PRs found:** Ask the user to provide PR links manually, or document based solely on epic information (noting that implementation details are pending).

**Epic has many child items:** Ask the user which children are most important to document, or focus on completed stories first.

**acli cannot fetch an issue:** If `jira_acli.py` fails (expired auth, network, or an unknown issue key), re-run `scripts/setup_acli.py` and check `acli jira auth status`. If it still fails, ask the user to copy-paste the epic description and child issue summaries.

**Existing docs are hard to parse:** If the RHDH docs fetch returns poorly formatted content, ask the user to describe the current structure or provide a link to a similar feature's documentation as a template.

## Script Maintenance

The bundled scripts use the Python standard library only (no third-party
packages):

- `scripts/jira_acli.py` — wraps `acli` for issue, child, and PR-tree queries.
  Requires `acli` installed and authenticated; the remote/web-link PR source also
  needs `JIRA_API_TOKEN` in the environment.
- `scripts/fetch_rhdh_docs.py` — fetches existing docs from the RHDH docs GitHub
  repository over HTTPS.
- `scripts/setup_acli.py` — verifies `acli` installation and authentication.

If `acli` changes its JSON shape or flags, update `jira_acli.py` accordingly and
re-run its tests before relying on the output.

## Output Location

Generated documentation is saved to a dedicated directory per Jira ticket:
```
./rhdh-feature-docs-output/<ISSUE-KEY>/
```

**All files for a single epic go in the same directory:**
```
./rhdh-feature-docs-output/RHDHPLAN-1187/
├── RHDHPLAN-1187-new-frontend-system-ga.md      (main documentation)
├── RHDHPLAN-1187-release-notes.md               (release notes)
├── RHDHPLAN-1187-summary.md                     (analysis summary)
├── RHDHPLAN-1187-<additional-file>.md           (any other generated files)
└── techdocs/                                     (Backstage TechDocs - if generated)
    ├── mkdocs.yml
    └── docs/
        ├── index.md
        ├── installation.md
        ├── configuration.md
        ├── usage.md
        └── [additional files]
```

This organization keeps all documentation for a single Jira ticket together and makes it easy to find all related files.

## Completion

Complete when the generated documentation content exists on disk and its
location was reported to the user. Name the Jira issue key that was analyzed, the
output mode used (RHDH AsciiDoc, release notes, TechDocs, or analysis summary),
and every file written under `./rhdh-feature-docs-output/<ISSUE-KEY>/` (or the
user-supplied target path). Report which sources were actually read — Jira issue,
child issues, linked PRs, existing RHDH docs — and call out any that were missing
or unreachable rather than implying coverage the content does not have. For
update mode, the answer names the exact files and sections to change; for create
mode, it names the new files and the integration steps to land them in the
rhdh-docs repository. Never report generated content as committed or published —
this skill only produces files for the user to review and place.

---

## Example: Complete Documentation for a Feature

For complete worked, end-to-end scenarios — a full new-feature build (the OAuth
example: assembly, concept, procedure, integration guide, and release note),
documentation updates, release notes, and TechDocs — see
`references/usage-examples.md`.
