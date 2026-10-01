# RHDH Feature Documentation Generator - Usage Examples

This document provides real-world examples of using the skill for different scenarios.

---

## Example 1: Create New Feature Documentation

**Scenario:** You need to document a brand new GA feature.

### User Prompt
```
I need to document this new feature for RHDH 2.1: 
https://redhat.atlassian.net/browse/RHDHPLAN-1187

Please generate comprehensive documentation including installation, 
configuration, and usage examples.
```

### What the Skill Does

1. **Fetches Epic Details**
   - Title: "GA support for the New Frontend System (NFS) in RHDH 2.1"
   - Description: Feature overview, goals, requirements, acceptance criteria
   - Status: In Progress

2. **Discovers Child Epics** (6 found)
   - RHDHPLAN-192: Base RHDH frontend on upstream NFS
   - RHIDP-13380: Graduate plugins from alpha to stable (25 children)
   - RHIDP-14164: Migrate Red Hat plugins to NFS (13 children)
   - RHIDP-14425: Documentation requirements (2 children)
   - RHIDP-14855: NFS enhancements and refactoring (4 children)
   - RHIDP-15286: E2E test migration (25 children)

3. **Finds GitHub PRs** (7 PRs from child epics)

4. **Checks Existing RHDH Docs**
   - Searches RHDH 1.10 docs for NFS content
   - Determines this is a new feature (not in 1.10)

5. **Generates Release Notes**
   ```markdown
   **Type:** Feature
   
   **Suggested Release Note:**
   
   ### New Frontend System Generally Available
   
   The New Frontend System (NFS) is now Generally Available in RHDH 2.1. 
   All plugin APIs have graduated from alpha to stable, and plugins can be 
   installed directly from the Extensions Catalog UI without manual YAML 
   configuration.
   ```

6. **Creates Documentation** (13KB markdown)
   - Overview and goals by persona
   - Key features (graduated APIs, NFS catalog, UI installation, translations)
   - Migration guide with before/after code examples
   - Configuration and prerequisites
   - Scope breakdown (what's included, what's out of scope)
   - Validation and testing details
   - Troubleshooting FAQs
   - Links to all 6 child epics and 7 PRs

### Generated Files

```
./rhdh-feature-docs-output/
├── RHDHPLAN-1187-new-frontend-system-ga.md          (13KB)
├── RHDHPLAN-1187-release-notes.md                   (1KB)
└── RHDHPLAN-1187-summary.md                         (5KB)
```

### Key Outputs

**Main Documentation Highlights:**
- ✅ 12 major sections
- ✅ Code examples for migration (alpha → stable imports)
- ✅ Persona-based goals (developers, operators, end users)
- ✅ Specific plugin names (global-header, quickstart, scorecard, etc.)
- ✅ 20+ test workspaces listed
- ✅ Comprehensive troubleshooting

**Release Notes:**
- ✅ Type: Feature
- ✅ Clear headline
- ✅ User benefit focus

**Summary:**
- ✅ 6 child epics analyzed
- ✅ 80+ child issues discovered
- ✅ 7 PRs found
- ✅ Gaps identified (no existing docs to merge with)

---

## Example 2: Update Existing RHDH Documentation

**Scenario:** You need to update existing RHDH docs with changes from a feature that removes functionality.

### User Prompt
```
We need to update the RHDH docs for this epic: 
https://redhat.atlassian.net/browse/RHDHPLAN-1235

Can you check what's in the current RHDH 1.10 docs about the Plugin 
Certification Program and create a plan for what needs to be updated 
or removed?
```

### What the Skill Does

1. **Fetches Epic Details**
   - Title: "Remove the 'Plugin Certification Program' from Red Hat Developer Hub"
   - Description: Sunset program, remove badges, clean up metadata
   - Type: Feature removal

2. **Discovers Child Issues** (3 found)
   - RHIDP-14163: Engineering implementation (remove UI, metadata cleanup)
   - RHDHPLAN-1378: Verification and demo
   - RHIDP-14426: Documentation updates

3. **Checks Existing RHDH Docs**
   - Fetches RHDH 1.10 documentation structure
   - Identifies sections that mention plugins/extensions/certification

4. **Generates Release Notes**
   ```markdown
   **Type:** Removed functionality
   
   **Suggested Release Note:**
   
   ### Plugin Certification Program Removed
   
   The Plugin Certification Program has been removed from Red Hat Developer Hub. 
   Certification badges and metadata are no longer displayed in the Extensions 
   Catalog. Previously certified plugins (Dynatrace, IBM API Connect) remain 
   available and fully functional.
   ```

5. **Creates Documentation Update Plan** (12KB)
   - **7 sections to update:**
     1. Plugin Installation Guide - Remove certification screenshots
     2. Dynamic Plugins Usage - Remove "certified" criteria
     3. Plugin Reference - Remove certification columns
     4. Plugin Development Guide - Remove certification process
     5. Extensions Catalog Guide - Remove filter/sort instructions
     6. Getting Started - Update screenshots
     7. Release Notes - Add removal announcement
   
   - **~10 screenshots to replace**
   - **Metadata schema updates** (remove `certified` field)
   - **Before/after examples** for each section

6. **Identifies What Changes**
   ```markdown
   ### Plugin Installation Guide
   
   **REMOVE:**
   - Screenshots showing certification badges
   - "Filter by certified" instructions
   - "Prioritize certified plugins" recommendations
   
   **UPDATE:**
   - All Extensions Catalog screenshots (no badges)
   - Plugin selection criteria:
     BEFORE: "prioritize certified plugins"
     AFTER: "prioritize actively maintained, well-documented plugins"
   ```

### Generated Files

```
./rhdh-feature-docs-output/
├── RHDHPLAN-1235-remove-plugin-certification-program.md    (9KB)
├── RHDHPLAN-1235-documentation-update-plan.md              (12KB) ⭐
├── RHDHPLAN-1235-release-notes.md                          (1KB)
└── RHDHPLAN-1235-summary.md                                (4KB)
```

### Key Outputs

**Feature Documentation** (9KB):
- What's being removed and why
- Impact by user persona (admins, plugin authors, end users)
- Partner communication (Dynatrace, IBM API Connect)
- Technical scope (UI, metadata, docs)
- Backward compatibility assurance
- Troubleshooting FAQs

**Documentation Update Plan** (12KB) ⭐ **UNIQUE FOR UPDATE SCENARIOS:**
- ✅ **7 specific RHDH doc sections** to update with exact locations
- ✅ **Before/after examples** for each change
- ✅ **Screenshot requirements** (which ones to replace)
- ✅ **Metadata schema changes** (tables to update)
- ✅ **Implementation order** (what to update first)
- ✅ **Quality checklist** (search for "certif" = 0 results)
- ✅ **Coordination needs** (engineering, partners, release team)
- ✅ **Post-update validation** steps

**Example Update Guidance:**
```markdown
### Section: Extend > Installing and viewing plugins

**File:** `extending-rhdh/plugins-installation.adoc`

**REMOVE:**
- Line ~45: "certified plugins are indicated with a certification badge"
- Screenshot: `images/extend/plugins-catalog-certified-badge.png`
- Section: "Filtering by Certification Status"

**UPDATE:**
- Line ~67: Replace "When selecting plugins, prioritize certified plugins" 
  with "When selecting plugins, prioritize plugins that are actively 
  maintained and well-documented"

**ADD:**
- Nothing (this is a removal)
```

**Release Notes:**
- ✅ Type: Removed functionality
- ✅ Notes what's removed
- ✅ Clarifies partners still supported

**Summary:**
- ✅ 3 child issues analyzed
- ✅ Decision document linked
- ✅ Repository identified (rhdh-plugin-export-overlays)
- ✅ Gap noted: No PRs linked yet (implementation in progress)

---

## Example 3: Feature Owner First-Pass Documentation

**Scenario:** You're the epic owner and need quick documentation for stakeholder review.

### User Prompt
```
I'm the owner of RHDHPLAN-1187 (New Frontend System GA) and need to 
create documentation in my first pass. Can you generate docs based on 
the epic? I'll refine it later with engineering input.
```

### What the Skill Does

1. **Fetches Epic Only**
   - Gets main epic description
   - Notes child epics exist but doesn't deep-dive
   - Focuses on epic-level content

2. **Generates Lightweight Documentation** (6.5KB)
   - Feature overview from epic description
   - Goals and requirements from acceptance criteria
   - Notes what's missing (child epic details, PRs)

3. **Generates Release Notes**
   ```markdown
   **Type:** Feature
   
   **Suggested Release Note:**
   
   ### New Frontend System Generally Available
   
   The New Frontend System (NFS) graduates to GA in RHDH 2.1 with stable 
   plugin APIs and Extensions Catalog UI installation support.
   ```

4. **Identifies Gaps Explicitly**
   ```markdown
   ## Information Gaps
   
   - **No child issue details fetched** - Can analyze 6 child epics for more depth
   - **No PR implementation details** - PRs not yet linked to epic
   - **Missing usage examples** - Can add once implementation is complete
   
   ## Recommended Next Steps
   
   1. Fetch child epics (RHIDP-13380, RHIDP-14164, etc.) for detailed scope
   2. Add GitHub PR links when available
   3. Include configuration examples from implementation
   4. Add screenshots of Extensions Catalog UI changes
   ```

### Generated Files

```
./rhdh-feature-docs-output/
├── RHDHPLAN-1187-new-frontend-system-ga.md     (6.5KB - lighter version)
├── RHDHPLAN-1187-release-notes.md              (1KB)
└── RHDHPLAN-1187-summary.md                    (3.8KB - highlights gaps)
```

### Key Outputs

**Main Documentation:**
- ✅ Feature overview and context
- ✅ Goals from epic
- ✅ Requirements and acceptance criteria
- ✅ Customer considerations
- ⚠️ **Explicitly notes missing details**
- ⚠️ **Recommends enhancements**

**Release Notes:**
- ✅ Type: Feature
- ✅ Concise (suitable for early review)

**Summary (emphasizes gaps):**
- ✅ Lists 6 child epics (but notes not fetched)
- ✅ Recommends fetching child details
- ✅ Suggests adding PRs when available

---

## Example 4: Bug Fix Documentation

**Scenario:** Documenting a bug fix for release notes.

### User Prompt
```
Document this bug fix: https://redhat.atlassian.net/browse/RHIDP-15678
```

### What the Skill Does

1. **Detects Issue Type**
   - Epic type: Bug
   - Title contains "Fix"
   - → Determines release note type: **Bug Fix**

2. **Fetches Bug Details**
   - What was broken
   - How it was fixed
   - Impact on users

3. **Generates Release Notes**
   ```markdown
   **Type:** Bug Fix
   
   **Suggested Release Note:**
   
   ### Dynamic Plugins Loading
   
   Fixed an issue where plugins with circular dependencies failed to load 
   during startup. The plugin loader now properly handles dependency 
   resolution cycles.
   ```

4. **Creates Brief Documentation** (2KB)
   - Problem description
   - Solution implemented
   - User impact (who was affected)
   - How to verify the fix

### Generated Files

```
./rhdh-feature-docs-output/
├── RHIDP-15678-plugin-loading-fix.md       (2KB - brief)
└── RHIDP-15678-release-notes.md            (0.5KB)
```

**Note:** Bug fixes get lighter documentation (focus on release notes).

---

## Example 5: Enhancement Documentation

**Scenario:** Performance improvement to existing feature.

### User Prompt
```
Document this enhancement: https://redhat.atlassian.net/browse/RHIDP-16234
```

### What the Skill Does

1. **Detects Enhancement Type**
   - Epic title: "Improve Extensions Catalog Performance"
   - Type: Enhancement
   - → Release note type: **Enhancement**

2. **Generates Release Notes**
   ```markdown
   **Type:** Enhancement
   
   **Suggested Release Note:**
   
   ### Extensions Catalog Performance
   
   Plugin discovery and filtering in the Extensions Catalog is now up to 3x 
   faster with improved caching and lazy loading. Large catalogs with 100+ 
   plugins load in under 2 seconds.
   ```

3. **Creates Enhancement Documentation** (4KB)
   - What improved
   - Performance metrics (before/after)
   - Configuration changes (if any)
   - User impact

---

## Comparison: New Feature vs Update Existing Docs

| Aspect | New Feature (RHDHPLAN-1187) | Update Existing (RHDHPLAN-1235) |
|--------|----------------------------|----------------------------------|
| **Epic Type** | New functionality | Removal/Cleanup |
| **RHDH Docs Check** | No existing content found | Finds existing sections to update |
| **Output Focus** | Complete new documentation | Update plan + removal guidance |
| **Unique Outputs** | Full feature docs (13KB) | Documentation update plan (12KB) |
| **Screenshots** | New screenshots needed | Replace existing screenshots |
| **Release Note Type** | Feature | Removed functionality |
| **Migration Guide** | Alpha → Stable APIs | No migration (backward compatible) |
| **Files Generated** | 3 (docs, release notes, summary) | 4 (docs, update plan, release notes, summary) |

---

## Command Patterns

### Basic Documentation Request
```
Document this feature: https://redhat.atlassian.net/browse/EPIC-KEY
```

### Comprehensive with Context
```
I need comprehensive documentation for RHDHPLAN-XXX including:
- Installation and configuration
- Usage examples
- Migration guidance from the old approach
- Troubleshooting tips
```

### Update Focus
```
Update the RHDH docs for epic RHDHPLAN-XXX. Check what's already in 
RHDH 1.10 docs and identify what needs to change.
```

### First Pass (Lightweight)
```
I'm the feature owner for RHDHPLAN-XXX. Create first-pass documentation 
from the epic - I'll add implementation details later.
```

### Release Notes Only
```
Generate release notes for https://redhat.atlassian.net/browse/EPIC-KEY
```

---

## Output File Summary

| Scenario | Main Docs | Update Plan | Release Notes | Summary | Total |
|----------|-----------|-------------|---------------|---------|-------|
| **New Feature** | 13KB | - | 1KB | 5KB | ~19KB |
| **Update Existing** | 9KB | 12KB | 1KB | 4KB | ~26KB |
| **First Pass** | 6.5KB | - | 1KB | 3.8KB | ~11KB |
| **Bug Fix** | 2KB | - | 0.5KB | - | ~2.5KB |
| **Enhancement** | 4KB | - | 1KB | 2KB | ~7KB |

---

## Tips for Best Results

### ✅ Do This

**Provide clear context:**
```
We're removing the Plugin Certification Program (RHDHPLAN-1235). 
Check the current RHDH docs and create an update plan.
```

**Specify what you need:**
```
Document RHDHPLAN-1187 with focus on migration guidance for plugin developers.
```

**Mention the target version:**
```
Create docs for the NFS GA feature in RHDH 2.1.
```

### ❌ Avoid This

**Vague requests:**
```
Document this: <url>
```
(Skill won't know if you want updates or new docs)

**Missing epic link:**
```
Document the new frontend system
```
(Skill needs the Jira URL to fetch details)

---

This guide shows how the skill adapts to different documentation scenarios and what outputs to expect.

---

## Example 4: Complete AsciiDoc Feature Documentation (OAuth)

A full new-feature build showing every generated file for an RHDH product-doc
feature: master assembly, concept and procedure modules, the integration guide,
and the release note.

**User request:** "Document RHDHPLAN-1234 which adds OAuth configuration to RHDH"

**What you generate:**

### File 1: `assembly-oauth-configuration.adoc`
```asciidoc
:_mod-docs-content-type: ASSEMBLY
:_mod-docs-category: Administer

include::artifacts/attributes.adoc[]

[id="oauth-configuration_{context}"]
= Configuring OAuth authentication

[role="_abstract"]
Configure OAuth 2.0 authentication providers to allow users to sign in to {product} using external identity providers such as GitHub, GitLab, or Google.

include::modules/administer/con-oauth-authentication.adoc[leveloffset=+1]

include::modules/administer/proc-configure-github-oauth.adoc[leveloffset=+1]

include::modules/administer/proc-configure-gitlab-oauth.adoc[leveloffset=+1]

include::modules/administer/ref-oauth-configuration-options.adoc[leveloffset=+1]
```

### File 2: `con-oauth-authentication.adoc`
```asciidoc
:_mod-docs-content-type: CONCEPT

[id="oauth-authentication_{context}"]
= OAuth authentication in {product-very-short}

[role="_abstract"]
{product} ({product-very-short}) supports OAuth 2.0 authentication to allow users to sign in using credentials from external identity providers.

OAuth authentication enables single sign-on (SSO) and allows you to leverage existing user identities from platforms such as GitHub, GitLab, Google, and Microsoft Azure AD. When users sign in, they are redirected to the OAuth provider's login page, and upon successful authentication, returned to {product-very-short} with an authenticated session.

Benefits of OAuth authentication:

* Single sign-on across multiple applications
* Centralized user management through your identity provider
* No need to manage separate passwords for {product-very-short}
* Support for multi-factor authentication (MFA) if enabled on your provider

.Additional resources
* link:https://oauth.net/2/[OAuth 2.0 specification]
```

### File 3: `proc-configure-github-oauth.adoc`
```asciidoc
:_mod-docs-content-type: PROCEDURE

[id="configure-github-oauth_{context}"]
= Configuring GitHub OAuth authentication

[role="_abstract"]
Configure {product-very-short} to use GitHub as an OAuth 2.0 authentication provider.

.Prerequisites
* You have administrator access to your GitHub organization
* You have the `app-config.yaml` configuration file for your {product-very-short} deployment

.Procedure
. In GitHub, navigate to your organization settings and create a new OAuth application:
   .. Go to *Settings* > *Developer settings* > *OAuth Apps* > *New OAuth App*
   .. Enter the following details:
      * *Application name*: `Red Hat Developer Hub`
      * *Homepage URL*: `https://your-rhdh-instance.com`
      * *Authorization callback URL*: `https://your-rhdh-instance.com/api/auth/github/handler/frame`
   .. Click *Register application*
   .. Note the *Client ID* and generate a *Client Secret*

. Update your `app-config.yaml` file with the GitHub OAuth configuration:
+
[source,yaml]
----
auth:
  environment: production
  providers:
    github:
      production:
        clientId: ${GITHUB_CLIENT_ID}
        clientSecret: ${GITHUB_CLIENT_SECRET}
----
+
. Set the environment variables with your GitHub OAuth credentials:
+
[source,bash]
----
export GITHUB_CLIENT_ID="your-client-id"
export GITHUB_CLIENT_SECRET="your-client-secret"
----
+
. Restart {product-very-short} to apply the changes.

.Verification
. Navigate to your {product-very-short} instance
. Click *Sign In*
. Verify that the GitHub sign-in option appears
. Sign in using your GitHub credentials and verify successful authentication

.Additional resources
* link:https://docs.github.com/en/developers/apps/building-oauth-apps/creating-an-oauth-app[Creating an OAuth App on GitHub]
```

### File 4: `INTEGRATION-GUIDE.md`
```markdown
# Integration Guide for RHDHPLAN-1234 OAuth Configuration

## Files Generated

- `assembly-oauth-configuration.adoc` - Master assembly
- `con-oauth-authentication.adoc` - OAuth concept overview
- `proc-configure-github-oauth.adoc` - GitHub configuration procedure
- `proc-configure-gitlab-oauth.adoc` - GitLab configuration procedure (similar to GitHub)
- `ref-oauth-configuration-options.adoc` - Configuration reference table

## Integration Steps

### 1. Copy Files to rhdh-docs Repository

```bash
# Copy assembly to titles
cp assembly-oauth-configuration.adoc ~/rhdh-docs/titles/administer/

# Copy modules
cp con-oauth-authentication.adoc ~/rhdh-docs/modules/administer/
cp proc-configure-github-oauth.adoc ~/rhdh-docs/modules/administer/
cp proc-configure-gitlab-oauth.adoc ~/rhdh-docs/modules/administer/
cp ref-oauth-configuration-options.adoc ~/rhdh-docs/modules/administer/
```

### 2. Update Master Administration Guide

In `titles/administer/assembly-administer-rhdh.adoc`, add:

```asciidoc
include::assembly-oauth-configuration.adoc[leveloffset=+1]
```

### 3. Preview Documentation

```bash
cd ~/rhdh-docs
make preview
# Open http://localhost:8080/administer/oauth-configuration
```

### 4. Source Information

Based on:
- Jira: RHDHPLAN-1234
- PR: https://github.com/redhat-developer/rhdh/pull/5678
- Configuration examples from PR implementation
```

### File 5: `release-notes.md`
```markdown
### OAuth Authentication Support

**Type:** Feature

**Title:** OAuth 2.0 Authentication Provider Support

**Description:**
{product} now supports OAuth 2.0 authentication providers, allowing users to sign in using credentials from GitHub, GitLab, Google, and Microsoft Azure AD. This enables single sign-on (SSO) and eliminates the need to manage separate passwords for {product-very-short}.

**Action Required:**
To enable OAuth authentication, administrators must configure OAuth providers in the `app-config.yaml` file. See the OAuth configuration documentation for step-by-step instructions.
```

---

**Notice:** All files are **actual documentation content**, ready to copy into the rhdh-docs repository. No planning documents, no meta-analysis - just the documentation itself.
