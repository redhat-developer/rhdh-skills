# RHDH Feature Documentation Structure Template

This template provides the standard structure for RHDH feature documentation.

## Standard RHDH Feature Documentation Sections

### 1. Title and Overview
```markdown
# [Feature Name]

## Overview

Brief description of what the feature is and why it exists.
- What problem does it solve?
- Who is it for?
- Key benefit statement
```

### 2. Goals and User Outcomes
```markdown
## Goals and User Outcomes

### For [Persona 1] (e.g., Plugin Developers)
- Outcome 1
- Outcome 2

### For [Persona 2] (e.g., Platform Operators)
- Outcome 1
- Outcome 2

### For [Persona 3] (e.g., End Users)
- Outcome 1
- Outcome 2
```

### 3. Features and Capabilities
```markdown
## Key Features and Capabilities

### Feature 1
Description and what it enables.

### Feature 2
Description and what it enables.
```

### 4. Prerequisites
```markdown
## Prerequisites

Before using this feature:

1. **Requirement 1**: Description
2. **Requirement 2**: Description
3. **Requirement 3**: Description
```

### 5. Configuration
```markdown
## Configuration

### Installation

Step-by-step installation instructions.

### Configuration Options

Detailed parameter explanations.

**Example configuration:**
\`\`\`yaml
# Actual configuration example
dynamicPlugins:
  plugins:
    - package: '@example/plugin'
      disabled: false
\`\`\`
```

### 6. Usage
```markdown
## Usage

### Basic Usage

Common scenarios with examples.

### Advanced Usage

Complex use cases.
```

### 7. Migration Guide (if applicable)
```markdown
## Migration from [Previous Version]

### Migration Checklist

- [ ] Step 1
- [ ] Step 2
- [ ] Step 3

### Breaking Changes

List any breaking changes and how to handle them.

**Before:**
\`\`\`typescript
// Old code
\`\`\`

**After:**
\`\`\`typescript
// New code
\`\`\`
```

### 8. Scope and Implementation Details
```markdown
## Scope and Implementation Details

### What's Included
- Feature A
- Feature B

### What's NOT Included (Out of Scope)
- Future feature X
- Future feature Y
```

### 9. Validation and Testing
```markdown
## Validation and Testing

### End-to-End Validation
- What was tested
- How to verify

### Test Coverage
- Unit tests
- Integration tests
- E2E tests
```

### 10. Customer Considerations
```markdown
## Customer Considerations

### For Existing Users
- What changes
- Migration timeline
- Testing recommendations

### For New Users
- Getting started guidance
- Best practices

### Upgrade Path
1. Review release notes
2. Test in non-production
3. Update configurations
4. Deploy to production
```

### 11. Troubleshooting
```markdown
## Troubleshooting

### Common Issues

**Issue**: [Problem description]
- **Cause**: Why it happens
- **Solution**: How to fix it

**Issue**: [Another problem]
- **Cause**: Root cause
- **Solution**: Resolution steps

### Getting Help
- Documentation links
- Support contact
- Community resources
```

### 12. Release Notes

**Always include a release notes section:**

```markdown
## Release Notes

**Type:** [Feature/Enhancement/Bug Fix/Deprecated functionality/Removed functionality/Known Issue/CVE/Developer Preview/Tech Preview/Release notes not required]

**Suggested Release Note:**

### [5-10 word headline]

[1-3 sentences describing what changed and why it matters to users]

[Additional notes if needed: migration steps, workarounds, etc.]
```

**Example:**
```markdown
## Release Notes

**Type:** Feature

**Suggested Release Note:**

### New Frontend System Generally Available

The New Frontend System (NFS) is now Generally Available in RHDH 2.1. All plugin APIs have graduated from alpha to stable, and plugins can be installed directly from the Extensions Catalog UI without manual YAML configuration.
```

### 13. Additional Resources
```markdown
## Additional Resources

### Related Jira Epics
- [EPIC-KEY](url) - Description

### GitHub Pull Requests
- [PR title](url) - What it implements

### Documentation Links
- Link to related docs
- Link to upstream docs

---

*This documentation was generated based on [Epic Key] and associated resources.*
```

## Section Priority

**Required Sections** (every feature doc should have):
1. Title and Overview
2. Features and Capabilities
3. Configuration
4. Troubleshooting
5. Additional Resources

**Conditional Sections** (include if applicable):
- Goals and User Outcomes (for major features)
- Prerequisites (if requirements exist)
- Migration Guide (for updates to existing features)
- Scope Details (for complex multi-epic features)
- Validation and Testing (for GA releases)

**Optional Sections**:
- Usage (if configuration examples aren't sufficient)
- Customer Considerations (for breaking changes)

## Writing Guidelines

### Voice and Tone
- **Active voice**: "Configure the plugin" not "The plugin can be configured"
- **Imperative for instructions**: "Run the command" not "You should run the command"
- **Present tense**: "The feature provides" not "The feature will provide"

### Technical Accuracy
- Use exact code/YAML from PRs when available
- Verify version numbers and compatibility
- Test commands before including them

### User-Focused
- Start with user goals, not implementation details
- Explain "why" before "how"
- Use concrete examples
- Avoid jargon or explain it

### Structure
- Use clear hierarchical headings (H2, H3)
- Keep paragraphs short (2-4 sentences)
- Use lists for multiple items
- Include code blocks for all examples

## Examples from RHDH Docs

### Good Overview Example
```markdown
## Overview

The New Frontend System (NFS) in Red Hat Developer Hub (RHDH) is 
graduating from alpha to Generally Available (GA) status in RHDH 2.1. 
This milestone represents the completion of RHDH's transition to a 
modern, stable plugin architecture that provides production-grade APIs 
and improved developer experience.
```

### Good Configuration Example
```markdown
### Enabling NFS in RHDH 2.1

In RHDH 2.1, NFS is enabled by default. No additional configuration 
is required to use NFS-based plugins.
```

### Good Troubleshooting Example
```markdown
**Issue**: Plugin fails to load after migration
- **Cause**: Import path still references `/alpha`
- **Solution**: Update import to reference stable export path:
  \`\`\`typescript
  // Change from:
  import { myExtension } from '@redhat/plugin/alpha';
  // To:
  import { myExtension } from '@redhat/plugin';
  \`\`\`
```

## Anti-Patterns to Avoid

❌ **Don't**: Write generic placeholder text
```markdown
This feature provides many benefits to users.
```

✅ **Do**: Be specific
```markdown
This feature reduces plugin installation time from 15 minutes to 2 minutes.
```

❌ **Don't**: Use passive voice
```markdown
The configuration can be updated by editing the YAML file.
```

✅ **Do**: Use active voice
```markdown
Edit the YAML file to update the configuration.
```

❌ **Don't**: Assume context
```markdown
After the migration, everything should work.
```

✅ **Do**: Be explicit
```markdown
After migrating from `/alpha` imports to stable imports, all existing 
plugins continue to function without changes.
```

❌ **Don't**: Include unverified information
```markdown
This feature will probably improve performance.
```

✅ **Do**: State facts or note gaps
```markdown
**Note**: Performance benchmarks are pending and will be added in a 
future documentation update.
```

---

## AsciiDoc modular documentation skeletons

Use these skeletons when creating NEW RHDH product documentation (AsciiDoc for
the docs repository). Each module carries the correct `:_mod-docs-content-type:`
metadata. Fill them with values verified from the linked PRs, not placeholders.

**1. Create Master Assembly File** (`assembly-[feature-name].adoc`)

```asciidoc
:_mod-docs-content-type: ASSEMBLY
:_mod-docs-category: [Integrate|Extend|Administer|Get Started]

include::artifacts/attributes.adoc[]

[id="[feature-id]_{context}"]
= [Feature Title]

[role="_abstract"]
[Brief description of the feature and its purpose]

include::modules/[category]/con-[concept-name].adoc[leveloffset=+1]

include::modules/[category]/proc-[procedure-name].adoc[leveloffset=+1]

include::modules/[category]/ref-[reference-name].adoc[leveloffset=+1]
```

**2. Create Concept Module** (`con-[feature-name].adoc`)

```asciidoc
:_mod-docs-content-type: CONCEPT

[id="[concept-id]_{context}"]
= [Concept Title]

[role="_abstract"]
[Abstract explaining what this concept covers]

[Main content explaining the concept, architecture, or overview]

.Additional resources
* link:[Related documentation]
```

**3. Create Procedure Module** (`proc-[procedure-name].adoc`)

```asciidoc
:_mod-docs-content-type: PROCEDURE

[id="[procedure-id]_{context}"]
= [Procedure Title]

[role="_abstract"]
[What this procedure accomplishes]

.Prerequisites
* Prerequisite 1
* Prerequisite 2

.Procedure
. Step 1 with command or action:
+
[source,yaml]
----
# Example configuration
----
+
. Step 2
. Step 3

.Verification
* How to verify the procedure succeeded

.Additional resources
* link:[Related documentation]
```

**4. Create Reference Module** (if needed - `ref-[reference-name].adoc`)

```asciidoc
:_mod-docs-content-type: REFERENCE

[id="[reference-id]_{context}"]
= [Reference Title]

[role="_abstract"]
[What reference information is provided]

[Tables, lists, or structured reference content]

.Additional resources
* link:[Related documentation]
```

**Content Sources:**
- **Concept content**: From Jira feature overview, goals, architecture diagrams
- **Procedure steps**: From PR implementation details, configuration changes
- **Configuration examples**: From PRs (actual YAML/code, not paraphrased)
- **Reference data**: From feature requirements, API details
