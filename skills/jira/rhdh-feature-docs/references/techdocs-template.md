# TechDocs Template Reference

This document provides templates for generating Backstage TechDocs structure.

## mkdocs.yml Template

```yaml
site_name: {Plugin Name from Epic Title}
site_description: {Brief description from epic Feature Overview}
repo_url: https://github.com/{org}/{repo}
edit_uri: edit/main/{relative-path-to-docs}

plugins:
  - techdocs-core

nav:
  - Home: index.md
  - Installation: installation.md
  - Configuration: configuration.md
  - Usage: usage.md
  # Add additional pages based on content generated
  # Example for comprehensive docs:
  # - API Reference: api.md
  # - Development: development.md
  # - Troubleshooting: troubleshooting.md
  # - Migration: migration.md

theme:
  name: material
  font: false
```

---

## docs/index.md Template

```markdown
# {Epic Title}

{Epic Feature Overview - first paragraph}

## Overview

{Expanded feature overview from epic description}

## Key Features

{Map from epic Goals section - bullet list of main capabilities}

- Feature 1: {Description}
- Feature 2: {Description}
- Feature 3: {Description}

## Use Cases

{Map from epic User Stories}

- **Use Case 1**: {User story description}
- **Use Case 2**: {User story description}

## Quick Start

{If epic has getting started / prerequisites}

1. Step 1
2. Step 2
3. Step 3

## Screenshots

{If epic mentions UI elements or has screenshots}

![Feature Screenshot](images/feature-name.png)

## Additional Resources

- [Jira Epic]({jira-url})
- [GitHub PRs]({pr-urls if available})
- [Related Documentation]({related-docs if mentioned})
```

---

## docs/installation.md Template

```markdown
# Installation

This guide covers how to install and set up {Plugin Name}.

## Prerequisites

{Map from epic Prerequisites section}

- Requirement 1
- Requirement 2
- Requirement 3

## Dependencies

{Map from epic Dependencies section}

```yaml
# From package.json or epic requirements
dependencies:
  - dependency-1: ^version
  - dependency-2: ^version
```

## Installation Methods

### Dynamic Plugin Installation

{If epic mentions dynamic plugin support}

1. Install the plugin:
   ```bash
   npm install @redhat-developer/{plugin-name}
   ```

2. Add to app-config.yaml:
   ```yaml
   dynamicPlugins:
     plugins:
       - package: '@redhat-developer/{plugin-name}'
         disabled: false
   ```

### Static Plugin Installation

{If epic mentions static installation}

1. Add to your Backstage app:
   ```bash
   yarn add @redhat-developer/{plugin-name}
   ```

2. Import in your app:
   ```typescript
   // In packages/app/src/App.tsx
   import { {PluginName}Page } from '@redhat-developer/{plugin-name}';
   ```

## Verification

{If epic has acceptance criteria or verification steps}

1. Start Backstage: `yarn dev`
2. Navigate to {URL}
3. Verify {expected behavior}
```

---

## docs/configuration.md Template

```markdown
# Configuration

Configure {Plugin Name} in your Backstage instance.

## Configuration Options

{Map from epic Configuration requirements section}

### Basic Configuration

Add to your `app-config.yaml`:

```yaml
{plugin-name}:
  # {Configuration option description from epic}
  option1: value1
  option2: value2
```

### Advanced Configuration

{If epic has advanced config}

```yaml
{plugin-name}:
  advanced:
    setting1: value1
    setting2: value2
```

## Environment Variables

{If epic mentions environment variables}

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `VAR_NAME` | {Description} | Yes/No | {Default value} |

## Configuration Examples

{If epic has examples}

### Example 1: {Scenario}

```yaml
{Example YAML}
```

### Example 2: {Scenario}

```yaml
{Example YAML}
```

## Validation

{If epic mentions config validation}

To validate your configuration:

```bash
{Validation command or steps}
```
```

---

## docs/usage.md Template

```markdown
# Usage Guide

Learn how to use {Plugin Name} in your workflows.

## Basic Usage

{Map from epic User Stories / Expected User Experience}

### Task 1: {Common Task}

{Step-by-step guide from epic workflows}

1. Step 1
2. Step 2
3. Step 3

**Example:**
```yaml
{Example if available}
```

### Task 2: {Common Task}

1. Step 1
2. Step 2

## User Workflows

{Map from epic workflows / user experience section}

### Workflow 1: {Workflow Name}

{Description and steps}

### Workflow 2: {Workflow Name}

{Description and steps}

## UI Guide

{If epic describes UI elements}

### Main Interface

{Description of main UI components}

### Navigation

{How to navigate the feature}

## Best Practices

{If epic has best practices or recommendations}

- Best practice 1
- Best practice 2
- Best practice 3
```

---

## docs/api.md Template (Conditional - if epic mentions APIs)

```markdown
# API Reference

API documentation for {Plugin Name}.

## Extension Points

{If epic mentions extension points or APIs}

### Extension 1: {Name}

```typescript
interface ExtensionInterface {
  // {API definition from epic or PR}
  method1(): ReturnType;
  method2(param: Type): ReturnType;
}
```

## Interfaces

{If epic defines interfaces}

### Interface 1: {Name}

```typescript
interface InterfaceName {
  property1: Type;
  property2: Type;
}
```

## Hooks

{If epic mentions React hooks or extension hooks}

### useHookName

```typescript
const { data, loading, error } = useHookName(params);
```

**Parameters:**
- `param1`: {Description}
- `param2`: {Description}

**Returns:**
- `data`: {Description}
- `loading`: {Description}
- `error`: {Description}
```

---

## docs/development.md Template (Conditional - if epic has dev info)

```markdown
# Development Guide

Contribute to {Plugin Name} development.

## Local Development

{If epic mentions local development setup}

1. Clone the repository:
   ```bash
   git clone {repo-url}
   cd {plugin-path}
   ```

2. Install dependencies:
   ```bash
   yarn install
   ```

3. Start development server:
   ```bash
   yarn start
   ```

## Project Structure

{If epic describes architecture}

```
{plugin-name}/
├── src/
│   ├── components/
│   ├── hooks/
│   └── api/
├── dev/
└── package.json
```

## Contributing

{If epic has contributing guidelines}

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Testing

{If epic mentions testing requirements}

```bash
yarn test
```
```

---

## docs/troubleshooting.md Template (Conditional - if epic has issues/risks)

```markdown
# Troubleshooting

Common issues and solutions for {Plugin Name}.

## Common Issues

{Map from epic Feature Risks / Known Issues}

### Issue 1: {Issue Description}

**Symptoms:**
- {Symptom 1}
- {Symptom 2}

**Cause:**
{Explanation}

**Solution:**
```bash
{Solution steps}
```

### Issue 2: {Issue Description}

**Symptoms:**
- {Symptom}

**Solution:**
{Solution steps}

## FAQ

{Common questions from epic}

### Q: {Question}?

A: {Answer}

### Q: {Question}?

A: {Answer}

## Getting Help

{If epic mentions support channels}

- GitHub Issues: {issues-url}
- Slack Channel: {slack-channel}
- Documentation: {docs-url}
```

---

## docs/migration.md Template (Conditional - if epic is an update)

```markdown
# Migration Guide

Migrate to the latest version of {Plugin Name}.

## Migrating from {Old Version} to {New Version}

{Map from epic scope "What's new" and "What's changed"}

### Breaking Changes

{If epic mentions breaking changes}

#### Change 1: {What Changed}

**Before:**
```yaml
{Old configuration}
```

**After:**
```yaml
{New configuration}
```

**Migration steps:**
1. Step 1
2. Step 2

### New Features

{New capabilities from epic}

- Feature 1: {Description}
- Feature 2: {Description}

### Deprecated Features

{If epic deprecates anything}

| Feature | Replacement | Timeline |
|---------|-------------|----------|
| {Old feature} | {New feature} | {Removal version} |

## Step-by-Step Migration

{Detailed migration process}

1. **Backup your configuration**
   ```bash
   cp app-config.yaml app-config.yaml.backup
   ```

2. **Update dependencies**
   ```bash
   yarn upgrade @redhat-developer/{plugin-name}
   ```

3. **Update configuration**
   {Configuration changes}

4. **Test**
   {Verification steps}

## Rollback

{If migration can be rolled back}

To rollback to the previous version:

```bash
{Rollback commands}
```
```

---

## Content Mapping Guide

**From Jira Epic → TechDocs Files**

| Epic Section | TechDocs File | Mapping |
|--------------|---------------|---------|
| Epic Title | All files | Page titles, site_name |
| Feature Overview | index.md | Overview section |
| Goals | index.md | Key Features section |
| User Stories | index.md, usage.md | Use Cases, Workflows |
| Prerequisites | installation.md | Prerequisites section |
| Dependencies | installation.md | Dependencies section |
| Setup Steps | installation.md | Installation Methods |
| Configuration Requirements | configuration.md | Configuration Options |
| App-config Examples | configuration.md | Configuration Examples |
| Expected User Experience | usage.md | User Workflows |
| APIs/Extension Points | api.md | API Reference |
| Development Details | development.md | Local Development |
| Known Issues | troubleshooting.md | Common Issues |
| Feature Risks | troubleshooting.md | Troubleshooting |
| Migration/Upgrade Info | migration.md | Migration Guide |

---

## Minimal vs Standard vs Comprehensive Setup

### Minimal Setup (3 files)

Generate when epic has **limited detail**:
- mkdocs.yml
- docs/index.md
- docs/installation.md OR docs/usage.md

### Standard Setup (4-5 files)

Generate when epic has **moderate detail**:
- mkdocs.yml
- docs/index.md
- docs/installation.md
- docs/configuration.md
- docs/usage.md

### Comprehensive Setup (6+ files)

Generate when epic has **extensive detail**:
- mkdocs.yml
- docs/index.md
- docs/installation.md
- docs/configuration.md
- docs/usage.md
- docs/api.md
- docs/development.md
- docs/troubleshooting.md
- docs/migration.md

**Decision Logic:**
- If epic < 500 words → Minimal
- If epic 500-1500 words → Standard
- If epic > 1500 words OR has child stories → Comprehensive
