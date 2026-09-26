# RHDH Documentation Structure Reference

This document maps where different types of content belong in the RHDH documentation.

## RHDH Documentation Organization

Base URL: `https://docs.redhat.com/en/documentation/red_hat_developer_hub/{version}`

### Main Sections

#### 1. **Discover**
**Content Type:** Overview, introductory content
- About Red Hat Developer Hub
- What's New / Release Notes
- Preview features

**When to add here:**
- High-level feature overviews
- "What is..." explanations
- Feature comparisons

#### 2. **Get Started**
**Content Type:** Initial setup and onboarding
- Setting up your first RHDH instance
- Navigating RHDH on your first day
- Quick start guides

**When to add here:**
- First-time user experiences
- Basic configuration for getting started
- Introductory tutorials

#### 3. **Install**
**Content Type:** Installation procedures
- Installing on OpenShift Container Platform
- Installing on Kubernetes (AKS, EKS, GKE)
- Air-gapped installations

**When to add here:**
- Platform-specific installation steps
- Deployment architecture guidance
- Infrastructure prerequisites

#### 4. **Upgrade**
**Content Type:** Upgrade procedures
- Upgrading RHDH instances
- Migration guides between versions

**When to add here:**
- Version upgrade procedures
- Breaking change migrations
- Compatibility matrices

#### 5. **Configure**
**Content Type:** Configuration and customization
- Configuring RHDH
- Customizing RHDH
- TechDocs configuration

**When to add here:**
- Post-installation configuration
- Feature enablement
- Customization options
- Theme and appearance changes

#### 6. **Control Access**
**Content Type:** Authentication and authorization
- Authentication providers
- RBAC configuration
- Permission management

**When to add here:**
- Auth provider integration
- Role-based access control
- Security configuration

#### 7. **Integrate**
**Content Type:** External integrations
- Git provider integration
- CI/CD integration
- Third-party tool connections

**When to add here:**
- External service connections
- API integrations
- OAuth/SSO setup

#### 8. **Develop**
**Content Type:** Developer workflows
- Software development workflows
- Template usage
- TechDocs authoring

**When to add here:**
- Developer-facing features
- Scaffolding templates
- Documentation authoring
- Development best practices

#### 9. **Observability**
**Content Type:** Monitoring and analytics
- Adoption Insights
- Audit logs
- Monitoring and logging
- Telemetry

**When to add here:**
- Metrics and analytics
- Logging configuration
- Audit tracking
- Performance monitoring

#### 10. **Extend**
**Content Type:** Plugin and extension management
- Orchestrator
- Dynamic plugin development
- Installing plugins
- Using plugins
- Plugin reference
- Plugin configuration

**When to add here:**
- Plugin installation guides
- Plugin development
- Extensions Catalog usage
- Custom plugin creation

#### 11. **Reference**
**Content Type:** Technical specifications
- Helm Chart configuration
- API references
- Configuration schemas

**When to add here:**
- Complete parameter lists
- API documentation
- Schema definitions
- CLI reference

---

## Feature Documentation Placement Guide

### New Feature (GA)

1. **Release announcement** → `Discover > What's New`
2. **Feature overview** → `Discover` or relevant section introduction
3. **Configuration guide** → `Configure` or feature-specific section
4. **Usage guide** → `Develop` or `Extend` (depending on audience)
5. **Reference material** → `Reference`

### Plugin-Related Features

- **Plugin installation** → `Extend > Installing and viewing plugins`
- **Plugin development** → `Extend > Develop and deploy dynamic plugins`
- **Plugin configuration** → `Extend > Configuring dynamic plugins`
- **Plugin reference** → `Extend > Dynamic plugins reference`

### Integration Features

- **Integration setup** → `Integrate > [Integration name]`
- **Integration configuration** → `Configure` or `Integrate`
- **Integration troubleshooting** → Within integration guide

### Developer Tools

- **Tool overview** → `Develop > Streamline software development`
- **Tool usage** → `Develop` with specific tool subsection
- **Tool configuration** → `Configure` or within tool guide

### Security/Access Features

- **Auth provider** → `Control access > Authentication`
- **RBAC changes** → `Control access > Authorization`
- **Permission models** → `Control access > Authorization`

---

## Common Documentation Patterns

### Pattern 1: New Plugin Support

**Files to update:**
1. `Extend > Installing and viewing plugins` - Add installation instructions
2. `Extend > Using dynamic plugins` - Add usage examples
3. `Extend > Dynamic plugins reference` - Add reference entry
4. `Discover > What's New` - Announce availability

### Pattern 2: Configuration Change

**Files to update:**
1. `Configure > Configuring RHDH` - Update configuration guide
2. `Reference > Helm Chart configuration` - Update parameter reference
3. `Discover > What's New` - Note the change

### Pattern 3: Breaking Change

**Files to update:**
1. `Upgrade > Upgrading RHDH` - Add migration steps
2. `Discover > What's New` - Highlight breaking change
3. Affected feature docs - Update configuration examples
4. Reference docs - Mark deprecated parameters

### Pattern 4: Integration Addition

**Files to create/update:**
1. Create new page under `Integrate > [Integration name]`
2. Update `Integrate` section index
3. Add to `Discover > What's New`
4. Update `Reference` if new config parameters

### Pattern 5: Feature Removal

**Files to update:**
1. `Discover > What's New` - Document removal
2. `Upgrade > Upgrading RHDH` - Migration guidance
3. Affected docs - Remove or mark as deprecated
4. Remove screenshots showing old feature

---

## Documentation File Naming Conventions

### Typical Patterns

- `installing-[platform].adoc` - Installation guides
- `configuring-[feature].adoc` - Configuration guides
- `using-[feature].adoc` - Usage guides
- `[feature]-reference.adoc` - Reference documentation
- `rhdh-[version]-release-notes.adoc` - Release notes

### Multi-Page Features

For complex features spanning multiple pages:

```
extend/
├── plugins-overview.adoc
├── plugins-installation.adoc
├── plugins-development.adoc
├── plugins-configuration.adoc
└── plugins-reference.adoc
```

---

## Cross-Referencing Guidelines

### Internal Links

Format: `link:../section/page.adoc[Link text]`

Example:
```asciidoc
For installation instructions, see 
link:../install/installing-openshift.adoc[Installing on OpenShift].
```

### External Links

Format: `link:https://example.com[Link text]`

Example:
```asciidoc
See the link:https://backstage.io/docs/plugins/[Backstage plugin documentation] 
for upstream information.
```

### Version-Specific Links

Always link to the same version of documentation:
```asciidoc
// Good
link:/documentation/red_hat_developer_hub/1.10/configure[Configuration Guide]

// Avoid
link:/documentation/red_hat_developer_hub/configure[Configuration Guide]
```

---

## Screenshot Guidelines

### When to Include Screenshots

✅ **Include screenshots for:**
- New UI features
- Complex workflows with multiple steps
- Configuration UI changes
- Visual elements (themes, layouts)

❌ **Don't screenshot:**
- Simple command-line output
- Code examples (use code blocks)
- Generic UI elements unchanged from previous versions

### Screenshot Requirements

- **Resolution**: Minimum 1280x720
- **Format**: PNG (for UI), SVG (for diagrams)
- **Callouts**: Red arrows/boxes for emphasis
- **Alt text**: Descriptive alt text for accessibility
- **Versioning**: Update screenshots when UI changes

### Screenshot Locations

Store in: `images/[section-name]/[descriptive-name].png`

Example: `images/extend/plugins-catalog-certified-badge.png`

---

## Release Notes Structure

### Format

```markdown
## Red Hat Developer Hub [Version]

Released: [Date]

### New Features

#### [Feature Name]
Description of what's new and why it matters.

### Enhancements

#### [Enhancement Area]
What improved and the benefit.

### Deprecations

#### [Deprecated Feature]
What's deprecated, timeline for removal, migration path.

### Breaking Changes

#### [Breaking Change]
What changed, impact, and how to migrate.

### Bug Fixes

- Issue description and resolution
- Issue description and resolution

### Known Issues

- Issue description and workaround (if any)
```

---

## Documentation Review Checklist

Before publishing feature documentation:

- [ ] Content placed in correct section
- [ ] All screenshots current and accurate
- [ ] Internal links working and versioned correctly
- [ ] Code examples tested and accurate
- [ ] Release notes entry added
- [ ] Cross-references to related docs included
- [ ] Troubleshooting section included (if applicable)
- [ ] Prerequisites clearly stated
- [ ] Configuration examples provided
- [ ] Accessibility (alt text, clear language)

---

## RHDH Version Mapping

Correlate RHDH versions with upstream Backstage versions:

| RHDH Version | Backstage Version | Notes |
|--------------|-------------------|-------|
| 1.10 | 1.49.1 | Current stable |
| 1.9 | 1.48.x | Previous |
| 1.8 | 1.47.x | Previous |

*Check release notes for exact version mappings*

---

## Documentation Repository Structure

```
rhdh-documentation/
├── titles/
│   ├── discover/
│   ├── get-started/
│   ├── install/
│   ├── configure/
│   ├── control-access/
│   ├── integrate/
│   ├── develop/
│   ├── observability/
│   ├── extend/
│   └── reference/
├── images/
├── modules/
└── assemblies/
```

*Actual structure may vary - check repository README*

---

This reference helps determine where new feature documentation should be placed within the RHDH documentation structure.
