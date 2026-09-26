# RHDH Release Notes Guide

This guide explains how to write release notes for RHDH features and bug fixes.

## Release Note Types

### 1. Feature
**When to use:** New functionality or capabilities added to RHDH

**Format:**
```markdown
### [Feature Name]

[Brief description of what the feature does and why it's valuable]

**Example:**
### New Frontend System GA Support

The New Frontend System (NFS) is now Generally Available in RHDH 2.1. All plugin APIs have graduated from alpha to stable, and plugins can be installed directly from the Extensions Catalog UI.
```

---

### 2. Enhancement
**When to use:** Improvements to existing features

**Format:**
```markdown
### [Area/Feature Enhanced]

[Description of what improved and the benefit]

**Example:**
### Extensions Catalog Performance

Plugin discovery and filtering in the Extensions Catalog is now up to 3x faster with improved caching and lazy loading.
```

---

### 3. Bug Fix
**When to use:** Fixes to defects or incorrect behavior

**Format:**
```markdown
### [Component/Area]

Fixed an issue where [problem description]. [Brief explanation of fix if relevant].

**Example:**
### Dynamic Plugins

Fixed an issue where plugins with circular dependencies failed to load during startup. The plugin loader now properly handles dependency resolution cycles.
```

---

### 4. Deprecated Functionality
**When to use:** Features/APIs marked for future removal

**Format:**
```markdown
### [Feature/API Name]

[What's deprecated], replaced by [new approach]. Deprecated features will be removed in RHDH [version]. [Migration guidance].

**Example:**
### Old Frontend System APIs

The legacy frontend system APIs are deprecated and will be removed in RHDH 3.0. Migrate to New Frontend System (NFS) stable APIs. See the migration guide for details.
```

---

### 5. Removed Functionality
**When to use:** Features/APIs that have been removed

**Format:**
```markdown
### [Feature/API Name]

[What was removed] has been removed from RHDH. [Alternative approach or migration path].

**Example:**
### Plugin Certification Program

The Plugin Certification Program has been removed from Red Hat Developer Hub. Certification badges and metadata are no longer displayed in the Extensions Catalog. Previously certified plugins remain available and fully functional.
```

---

### 6. Known Issue
**When to use:** Identified problems that haven't been fixed yet

**Format:**
```markdown
### [Component/Area]

[Description of the issue]. **Workaround:** [Temporary solution if available].

**Example:**
### Extensions Catalog

In some environments with restrictive network policies, the Extensions Catalog may fail to load plugin metadata. **Workaround:** Configure a proxy server in the RHDH configuration.
```

---

### 7. CVEs
**When to use:** Security vulnerabilities addressed

**Format:**
```markdown
### [CVE-YYYY-XXXXX] - [Component]

**Severity:** [Critical/High/Medium/Low]

[Brief description of vulnerability and fix]

For more information, see the [CVE details](link).

**Example:**
### CVE-2024-12345 - Authentication Module

**Severity:** High

Fixed a vulnerability in the authentication module that could allow session hijacking. All RHDH instances should upgrade to version 2.1 or later.

For more information, see the CVE-2024-12345 security advisory.
```

---

### 8. Developer Preview
**When to use:** Features available for testing but not production-ready

**Format:**
```markdown
### [Feature Name] (Developer Preview)

[Description of the preview feature]. This feature is in Developer Preview and is not supported for production use. [How to enable/access].

**Example:**
### AI-Powered Template Generation (Developer Preview)

Generate software templates using AI assistance. This feature is in Developer Preview and not supported for production. Enable with the `ai.templates.enabled: true` configuration flag.
```

---

### 9. Tech Preview
**When to use:** Features available for evaluation with limited support

**Format:**
```markdown
### [Feature Name] (Tech Preview)

[Description]. This feature is in Tech Preview with limited support. [Limitations or known gaps].

**Example:**
### Multi-Cluster Support (Tech Preview)

Manage and deploy to multiple Kubernetes clusters from a single RHDH instance. This feature is in Tech Preview with limited support and does not yet support all cluster types.
```

---

### 10. Release Notes Not Required
**When to use:** Internal changes, refactoring, or updates that don't impact users

**Examples:**
- Internal code refactoring
- Test coverage improvements
- Build system updates
- Documentation corrections
- Dependency updates (unless security-related)

**No release note generated** - these changes are transparent to users.

---

## Writing Guidelines

### Voice and Tone
- **Active voice**: "Added support for..." not "Support has been added for..."
- **Present tense**: "The feature provides..." not "The feature will provide..."
- **User-focused**: Start with user benefit, not implementation details

### Length
- **Headline**: 5-10 words
- **Description**: 1-3 sentences (aim for 2)
- **Total**: 30-60 words per entry

### What to Include
✅ **Do include:**
- What changed and why it matters
- User-visible impact
- Migration steps for breaking changes
- Workarounds for known issues
- Links to detailed documentation

❌ **Don't include:**
- Implementation details
- Internal ticket numbers (unless CVE)
- Developer jargon
- Marketing fluff

### Examples

**Good:**
```markdown
### Extensions Catalog Plugin Installation

Plugins can now be installed directly from the Extensions Catalog UI without manual YAML configuration. Browse available plugins, click Install, and configure settings through the UI.
```

**Bad:**
```markdown
### Extensions Catalog Refactoring

We've completely refactored the Extensions Catalog backend service using a new microservices architecture with improved scalability and performance. The new implementation uses Redis for caching and Kafka for event streaming, resulting in significant improvements to our technical architecture.
```
(Too technical, too long, focuses on implementation not user benefit)

---

## Release Note Type Decision Tree

```
Is this a user-facing change?
├─ No → Release notes not required
└─ Yes
    ├─ Is it a security fix?
    │   └─ Yes → CVE
    │
    ├─ Is it removing something?
    │   ├─ Removed already → Removed functionality
    │   └─ Removing soon → Deprecated functionality
    │
    ├─ Is it a bug fix?
    │   └─ Yes → Bug Fix
    │
    ├─ Is it a known problem?
    │   └─ Yes → Known Issue
    │
    ├─ Is it new functionality?
    │   ├─ Production-ready → Feature
    │   ├─ For testing only → Developer Preview
    │   └─ Limited support → Tech Preview
    │
    └─ Is it improving existing functionality?
        └─ Yes → Enhancement
```

---

## Determining Release Note Type from Epic

### From Epic Content

**Look for these indicators:**

**Feature:**
- Epic title contains: "Add", "New", "Introduce", "Support for"
- Description mentions: "new capability", "new feature"
- Acceptance criteria include new UI elements or workflows

**Enhancement:**
- Epic title contains: "Improve", "Enhance", "Optimize", "Update"
- Description mentions: "performance improvement", "better UX"
- Modifies existing functionality without adding new features

**Bug Fix:**
- Epic title contains: "Fix", "Resolve", "Bug"
- Issue type is "Bug" in Jira
- Description describes incorrect behavior

**Deprecated functionality:**
- Epic title contains: "Deprecate"
- Description mentions: "will be removed in", "deprecated in favor of"

**Removed functionality:**
- Epic title contains: "Remove", "Sunset", "Delete"
- Description confirms complete removal

**Known Issue:**
- Epic type is "Known Issue" or "Problem"
- Describes issue without providing fix

**Developer Preview / Tech Preview:**
- Epic description mentions: "preview", "experimental", "not supported"
- Labels include: "developer-preview", "tech-preview"

**CVE:**
- Epic title starts with "CVE-" or mentions security vulnerability
- Labels include: "security", "cve"

---

## Multi-Type Release Notes

Some changes may warrant multiple release note entries:

**Example:** A feature that deprecates an old API

```markdown
### New Frontend System GA Support (Feature)

The New Frontend System (NFS) is now Generally Available. All plugin APIs have graduated from alpha to stable.

### Old Frontend System APIs (Deprecated functionality)

The legacy frontend system APIs are deprecated and will be removed in RHDH 3.0. Migrate to NFS stable APIs.
```

---

## Release Notes Template

```markdown
## Red Hat Developer Hub [Version]

Released: [Date]

### New Features

#### [Feature Name]
[Description]

### Enhancements

#### [Enhancement Area]
[Description]

### Bug Fixes

#### [Component]
[Description]

### Deprecated Functionality

#### [Feature/API Name]
[Description and timeline]

### Removed Functionality

#### [Feature Name]
[Description and alternatives]

### Known Issues

#### [Component]
[Description and workaround]

### Developer Preview Features

#### [Feature Name] (Developer Preview)
[Description and how to enable]

### Tech Preview Features

#### [Feature Name] (Tech Preview)
[Description and limitations]

### Security Updates

#### [CVE-YYYY-XXXXX] - [Component]
**Severity:** [Level]
[Description]
```

---

## Automation Tips

When generating release notes from Jira epics:

1. **Check epic type/labels** first for type hints
2. **Analyze epic title** for keywords (Add, Fix, Remove, Deprecate)
3. **Review description** for user impact and benefits
4. **Check "Release Enablement/Demo" section** for release note text
5. **Look for "Customer Considerations"** for migration guidance
6. **Default to "Feature"** if unclear and user-visible
7. **Default to "Release notes not required"** if purely internal

---

## Quality Checklist

Before finalizing release notes:

- [ ] Type is appropriate for the change
- [ ] Headline is clear and concise (5-10 words)
- [ ] Description focuses on user benefit, not implementation
- [ ] Length is 30-60 words
- [ ] Breaking changes include migration steps
- [ ] Known issues include workarounds
- [ ] CVEs include severity and links
- [ ] Language is active voice and present tense
- [ ] No internal jargon or ticket numbers (except CVEs)

---

## Polishing the prose

After drafting the release note and any narrative documentation, invoke the
prose-editing skill once on that prose. It returns the same content with grammar,
tone, and clarity tightened while leaving technical literals untouched — preserve
attribute names, IDs, AsciiDoc directives, code, YAML, commands, cross-references,
and CVE identifiers exactly. Run prose-editing before presenting the result to the
user, not on the structured content around it.

---

This guide helps ensure consistent, high-quality release notes for RHDH features and fixes.
