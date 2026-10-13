# Reference: Plugin Metadata Format

Metadata files register plugins in the RHDH Extensions Catalog.

<overview>
Two entity kinds work together:
- **Package** — represents a single npm package (frontend or backend)
- **Plugin** — user-facing catalog entry that groups packages
</overview>

<package_entity>
**Location:** `workspaces/<name>/metadata/<package>.yaml`

**Purpose:** Defines a single exportable package with its configuration.

```yaml
apiVersion: extensions.backstage.io/v1alpha1
kind: Package
metadata:
  name: <package-name>  # e.g., backstage-plugin-aws-codebuild
  title: <Display Name>
  description: <Brief description>
spec:
  packageName: <npm-package-name>  # e.g., @aws/backstage-plugin-aws-codebuild
  # Artifact reference used by dynamic plugin loading (OCI image, tgz archive, npm package, or a directory path)
  dynamicArtifact: <artifact-reference>
  version: <package-version>

  # Dynamic plugin configuration
  dynamicPluginConfig:
    frontend:
      # or backend: for backend plugins
      mountPoints:
        - id: entity-card
          importName: AwsCodeBuildCard
          config:
            layout:
              gridColumnEnd: span 4

  # Example app-config.yaml snippets
  appConfigExamples:
    - title: Basic Configuration
      content: |
        aws:
          codebuild:
            accountId: '123456789012'
            region: us-east-1
```

**Key sections:**

- `dynamicArtifact` — artifact reference used for plugin loading (OCI image, tgz archive, npm package, or a directory path)
- `dynamicPluginConfig` — how the plugin mounts in RHDH
- `appConfigExamples` — configuration snippets for users
</package_entity>

<plugin_entity>
**Location:** `catalog-entities/marketplace/plugins/<name>.yaml`

**Purpose:** User-facing catalog entry that groups related packages.

```yaml
apiVersion: extensions.backstage.io/v1alpha1
kind: Plugin
metadata:
  name: <plugin-name>  # e.g., aws-codebuild
  title: <Display Title>
  description: <Brief description for listing>
  annotations:
    extensions.backstage.io/icon: <icon-url>
spec:
  # Full markdown documentation
  description: |
    ## Overview
    <What the plugin does>

    ## Features
    - Feature 1
    - Feature 2

    ## Configuration
    <How to configure>

  # Packages included in this plugin
  packages:
    - backstage-plugin-aws-codebuild
    - backstage-plugin-aws-codebuild-backend

  # For filtering in catalog
  categories:
    - CI/CD
    - Cloud

  # Feature highlights
  highlights:
    - Build status visibility
    - Project history
    - Start/stop builds

  # Support level
  developer: AWS
  supportLevel: community
```

**Registration:**
Add to `catalog-entities/marketplace/plugins/all.yaml` (alphabetical order).
</plugin_entity>

<documentation_link>
Full annotated example: [catalog-entities/extensions/README.md](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/catalog-entities/extensions/README.md)
</documentation_link>
