## Purpose

Reference of all RHDH-related repositories, what each one is used for, and how they relate to each other. Use this when navigating between projects or understanding the overall RHDH ecosystem.

## Repository Map

### rhdh

- **Upstream:** <https://github.com/redhat-developer/rhdh>
- **Description:** The main Red Hat Developer Hub application. Enterprise Internal Developer Portal built on Backstage. Formerly `janus-idp/backstage-showcase`.
- **Tech stack:** Node.js 22, TypeScript, React, Yarn 4, Turbo monorepo
- **Key concepts:**
  - **Scalprum dynamic loading:** Frontend plugins are loaded at runtime via [Scalprum](https://github.com/scalprum/scaffolding) (federated module loader), not compiled into the app. `packages/app/` renders `<ScalprumRoot>` which fetches plugin manifests from `/api/scalprum/plugins` served by `@internal/plugin-scalprum-backend`.
  - **`app-next`:** Parallel frontend using Backstage's standard Module Federation (`@backstage/frontend-dynamic-feature-loader`). Started with `APP_CONFIG_app_packageName=app-next ENABLE_STANDARD_MODULE_FEDERATION=true`.
  - **Dynamic plugin wrappers:** `dynamic-plugins/wrappers/` contains ~48 thin wrapper packages. Frontend wrappers use `--in-place` (produce `dist-scalprum/`), backend wrappers use `--embed-package` (self-contained `dist-dynamic/`). This is a **separate Yarn workspace** with its own `yarn.lock`.
  - **Layered config:** `app-config.yaml` (base dev) -> `app-config.dynamic-plugins.yaml` (frontend plugin UI integration: mount points, routes, menu items, icons, route bindings) -> `app-config.production.yaml` (production overlay). `dynamic-plugins.default.yaml` is **generated** (do not edit manually) from `default.packages.yaml`.
  - **Service override mechanism:** Each default service factory in `packages/backend/src/defaultServiceFactories.ts` can be disabled via `ENABLE_{SERVICE_ID}_OVERRIDE=true` env var to let a dynamic plugin provide its own.
  - **Branching:** `main` for active development; `release-1.x` for maintained releases; `dependencies/backstage-latest` for tracking upstream.
- **Key paths:** `packages/app/` (frontend), `packages/backend/` (backend), `plugins/` (internal `@internal/*` plugins), `dynamic-plugins/wrappers/` (wrapper packages), `app-config.dynamic-plugins.yaml` (UI integration config), `default.packages.yaml` (master plugin manifest), `backstage.json` (upstream version tracking), `build/containerfiles/Containerfile` (main app image base)

### rhdh-downstream

- **Upstream:** <https://gitlab.cee.redhat.com/rhidp/rhdh>
- **Description:** Downstream (productized) build of RHDH. Internal GitLab repository that produces the official Red Hat-supported container images published to `registry.redhat.io`. Syncs from the upstream `redhat-developer/rhdh` GitHub repo and applies Red Hat-specific patches, branding, and build configuration for Konflux/Brew pipelines.
- **Note:** Requires Red Hat VPN / internal network access.
- **Key paths:** `build/scripts/` (base image maintenance: `getLatestImageTags.sh`, `updateBaseImages.sh`)

### rhdh-cli

- **Upstream:** <https://github.com/redhat-developer/rhdh-cli>
- **Description:** CLI tool for developing, packaging, and distributing dynamic plugins for RHDH. Successor to `@janus-idp/cli`. Published as `@red-hat-developer-hub/cli` on npm. Extends/wraps `@backstage/cli`.
- **Tech stack:** Node.js 22, TypeScript, Webpack, esbuild, Commander.js, Yarn 3
- **Key concepts:**
  - **`plugin export`:** Detects plugin role from `package.json`, routes to backend or frontend export. Backend: creates `dist-dynamic/` via `productionPack()`, moves `@backstage/*` to `peerDependencies`, embeds `-common`/`-node` siblings, runs `yarn install --production`, validates entry points (`BackendFeature`/`BackendFeatureFactory` default export). Frontend: generates Scalprum assets in `dist-scalprum/` via `DynamicRemotePlugin` from `@openshift/dynamic-plugin-sdk-webpack`, plus optional Module Federation assets.
  - **`plugin package`:** Packages exported plugins as OCI container images or directories. Discovers plugins in monorepos, runs export, stages into temp dir, builds `FROM scratch` container with `io.backstage.dynamic-packages` annotation, or copies to `--export-to` directory.
  - **Embedded packages:** `--embed-package` bundles related packages into `dist-dynamic/embedded/`. Auto-detects `-common` and `-node` siblings. Versions suffixed with `+embedded`.
  - **Shared packages:** All `@backstage/*` packages are shared by default (moved to `peerDependencies`). Customizable via `--shared-package` with support for `!` exclusion and `/regex/` patterns.
  - **Versioning:** Major.minor synced with RHDH releases (CLI 1.8.x works with RHDH 1.8.z). Patch incremented independently.
  - **Branching:** `main` for active development; `release-1.x` for maintenance.
- **Key paths:** `src/commands/export-dynamic-plugin/` (export logic), `src/commands/package-dynamic-plugins/` (packaging), `src/lib/bundler/scalprumConfig.ts` (webpack config), `src/lib/schema/collect.ts` (config schema), `bin/rhdh-cli` (entry point)

### rhdh-local

- **Upstream:** <https://github.com/redhat-developer/rhdh-local>
- **Description:** Docker Compose-based local development and testing environment for RHDH. The fastest way to run RHDH locally without a Kubernetes cluster. Not for production use.
- **Tech stack:** Docker/Podman Compose, PostgreSQL (optional), Bash scripts
- **Key concepts:**
  - **Two-container architecture:** `install-dynamic-plugins` init container installs plugins into a shared `dynamic-plugins-root` volume, then `rhdh` main container starts the Backstage backend. Port `7007` for UI, port `9229` for Node.js debugger.
  - **Override-based config:** Users never edit defaults; they create git-ignored override files. `default.env` -> `.env`, `app-config.yaml` -> `app-config.local.yaml`, `dynamic-plugins.yaml` -> `dynamic-plugins.override.yaml`, `users.yaml` -> `users.override.yaml`.
  - **Four plugin sources:** (1) Local directory via `local-plugins/`, (2) OCI image via `oci://`, (3) tarball URL, (4) pre-bundled in RHDH image (`./dynamic-plugins/dist/`).
  - **Frontend hot-reload:** Use `compose-dynamic-plugins-root.yaml` override to bind-mount `./dynamic-plugins-root` as host directory, then run `npx @red-hat-developer-hub/cli plugin export --dev --dynamic-plugins-root <path>`. Re-export and refresh browser — no container restart needed.
  - **In-memory SQLite by default.** PostgreSQL can be opted into by uncommenting sections in `compose.yaml`.
  - **Branching:** `main` for active development; `release-1.x` for maintained releases.
- **Key paths:** `compose.yaml` (main compose), `configs/app-config/` (app configuration), `configs/dynamic-plugins/` (plugin configuration), `local-plugins/` (local plugin binaries), `docs/` (built-in TechDocs)

### rhdh-operator

- **Upstream:** <https://github.com/redhat-developer/rhdh-operator>
- **Description:** Kubernetes Operator for automated installation, configuration, and lifecycle management of RHDH instances on Kubernetes and OpenShift. CRD group is `rhdh.redhat.com`, primary CR kind is `Backstage` (API version `v1alpha5`).
- **Tech stack:** Go, Kubernetes client libraries, Ginkgo/Gomega testing, OpenShift API integration, kustomize
- **Key concepts:**
  - **Backstage CR spec:** `application` (appConfig configMaps, dynamicPluginsConfigMapName, extraFiles, extraEnvs, route), `database` (enableLocalDb, authSecretName), `deployment` (patch via kustomize merge2, kind: Deployment or StatefulSet), `monitoring` (ServiceMonitor toggle).
  - **Reconciliation flow:** Get CR -> preprocess spec (read ConfigMaps/Secrets, compute SHA-256 hash) -> init object model (Phase 1: load default config, Phase 2: overlay rawRuntimeConfig, Phase 3: apply CR spec) -> apply plugin dependencies -> server-side apply all objects -> clean up disabled features -> update status conditions.
  - **Auto-refresh:** External ConfigMaps/Secrets are labeled `rhdh.redhat.com/ext-config-sync=true` and watched. Config hash stored as `rhdh.redhat.com/ext-config-hash` pod annotation; hash change triggers rolling restart.
  - **PostgreSQL provisioning:** When `enableLocalDb: true` (default), creates a Secret (random password), StatefulSet (PostgreSQL 15, 1Gi PVC), and Service. Secret is immutable after creation.
  - **Platform detection:** Auto-detects OpenShift/EKS/AKS/GKE/vanilla K8s at startup. OpenShift gets Route + ClusterIP; K8s gets NodePort + fsGroup. Platform overrides use `.k8s` file suffix.
  - **Profiles:** `rhdh` (primary, default), `backstage.io` (community), `external` (no default config). Most `make` commands accept `PROFILE=`.
  - **Branching:** `main` for active development; `release-1.x` for maintained releases.
- **Key paths:** `api/v1alpha5/backstage_types.go` (CRD types), `internal/controller/` (reconciler), `pkg/model/` (runtime object model), `config/profile/rhdh/default-config/` (default manifests), `examples/rhdh-cr.yaml` (comprehensive example CR), `Dockerfile` (operator image base), `.rhdh/docker/Dockerfile`

### rhdh-chart

- **Upstream:** <https://github.com/redhat-developer/rhdh-chart>
- **Description:** Helm chart for deploying RHDH on Kubernetes and OpenShift. Alternative deployment method to the operator. The chart is a **wrapper** around the upstream Backstage Helm chart (pulled as subchart with alias `upstream`).
- **Tech stack:** Helm 3, Kubernetes/OpenShift YAML manifests, chart-testing, KinD
- **Key concepts:**
  - **Subchart architecture:** Upstream Backstage chart aliased as `upstream` in `Chart.yaml`. All upstream values accessible under `upstream:` key. Bitnami `common` chart also included.
  - **Dynamic plugins via Helm:** `global.dynamic.includes` (default: `dynamic-plugins.default.yaml`) + `global.dynamic.plugins` (user additions). Init container `install-dynamic-plugins` installs into 5Gi ephemeral PVC. Supports OCI plugins, npm tarballs, and pre-bundled plugins.
  - **Route vs Ingress:** OpenShift Route enabled by default (`route.enabled: true`) with edge TLS. For vanilla K8s, set `route.enabled: false` + `upstream.ingress.enabled: true`.
  - **Backend auth:** `global.auth.backend.enabled: true` (default) auto-generates a secret for service-to-service auth.
  - **Branching:** `main` for active development; `release-1.x` for maintained releases; `gh-pages` for published chart index.
- **Key paths:** `charts/backstage/` (primary chart), `charts/backstage/values.yaml` (main values), `charts/backstage/templates/` (custom templates)

### rhdh-test-instance

- **Upstream:** <https://github.com/redhat-developer/rhdh-test-instance>
- **Description:** Automated test environment provisioner for RHDH. Provides Makefile targets and deployment scripts for standing up RHDH instances on OpenShift clusters via either operator or Helm chart. Also integrates with Prow CI to provision ephemeral clusters via PR slash commands.
- **Tech stack:** Bash, Make, OpenShift CLI, Helm, Prow CI
- **Key concepts:**
  - **Prow CI provisioning:** Comment `/test deploy operator 1.9 4h` or `/test deploy helm 1.9 4h` on a PR to have Prow provision an ephemeral OpenShift cluster with RHDH deployed, Keycloak configured, and credentials posted back to the PR. Duration is the cluster TTL.
  - **Makefile targets:** `make install-operator VERSION=1.9` (install operator CRD + controller), `make deploy-operator VERSION=1.9` (deploy Backstage CR), `make deploy-helm VERSION=1.9` (deploy via Helm chart), `make undeploy-*` (teardown).
  - **deploy.sh:** Core deployment script supporting `operator` and `helm` modes. Handles Keycloak deployment, app-config generation, dynamic plugins configuration, and cluster router detection.
  - **Environment configuration:** `.env` file for secrets (Keycloak credentials, GitHub tokens). `config/` directory for app-config and dynamic plugin YAML.
- **Key paths:** `deploy.sh` (main deployment script), `Makefile` (convenience targets), `helm/deploy.sh` (Helm-specific logic), `config/` (app-config and plugin configuration), `.env.example` (environment template)

### rhdh-loadtest

- **Upstream:** <https://github.com/redhat-developer/rhdh-loadtest>
- **Description:** Container images, Helm charts, ArgoCD resources, and synthetic catalog entities for load testing RHDH at scale. Supports deployments with up to 200 dynamic frontend plugins and 50k catalog entities.
- **Tech stack:** Helm, ArgoCD, Make, YAML, K6, OpenShift
- **Key concepts:**
  - **Synthetic catalog entities:** Pre-built YAML files for 10/100/1,000/10,000 components, groups, systems, APIs, and templates. Referenced via URL in `catalog.locations`.
  - **Multi-version testing:** Available version targets: `rhdh-17`, `rhdh-18`, `rhdh-19`, `rhdh-110`, `rhdh-110-nfs`, `rhdh-next`.
  - **Deployment modes:** Helm (`make install-all`) or ArgoCD (`oc apply -f argocd/`). Each version has its own Helm chart under `helm/`.
  - **Load generator:** Containerized load generator under `load-generator/`.
- **Key paths:** `catalog/` (synthetic entity YAML files), `helm/` (per-version Helm charts), `argocd/` (ArgoCD app definitions), `load-generator/` (load test runner)

### rhdh-e2e-test-utils

- **Upstream:** <https://github.com/redhat-developer/rhdh-e2e-test-utils>
- **Description:** Shared test utilities library for RHDH end-to-end tests. Provides reusable helpers, fixtures, and page objects for Playwright-based E2E testing across RHDH repositories.
- **Tech stack:** Node.js, TypeScript, Yarn 4, Playwright, Node built-in test runner (`node:test`)
- **Key paths:** `src/` (source code), `docs/` (package and overlay testing documentation)

### rhdh-must-gather

- **Upstream:** <https://github.com/redhat-developer/rhdh-must-gather>
- **Description:** Diagnostic data collection tool for RHDH deployments on Kubernetes and OpenShift. Collects RHDH-specific logs, configurations, and resources to help support teams troubleshoot issues. Published as `quay.io/rhdh-community/rhdh-must-gather`.
- **Tech stack:** Bash, Podman/Docker, OpenShift CLI, Helm (Kubernetes mode)
- **Key concepts:**
  - **Multi-platform:** Works on both OpenShift (`oc adm must-gather`) and vanilla Kubernetes (via Helm chart from `rhdh-chart`).
  - **Multi-deployment:** Supports both Helm and Operator-managed RHDH instances.
  - **Focused collection:** Gathers only RHDH-specific data (logs, configs, resources), not full cluster state.
  - **Heap dump support:** Optional heap dump collection with `--set gather.heapDump.enabled=true`.
- **Key paths:** `collection-scripts/` (data gathering scripts), `docs/` (data-collected reference, disconnected environments, heap dumps)

### rhdh-plugin-export-overlays

- **Upstream:** <https://github.com/redhat-developer/rhdh-plugin-export-overlays>
- **Description:** Metadata and automation hub for packaging community Backstage plugins as dynamic plugins for RHDH. Contains workspace definitions that point to upstream plugin repos and uses overlays/patches to customize them for dynamic loading. Automated workflows publish OCI container images to `ghcr.io`.
- **Tech stack:** GitHub Actions, YAML/JSON configuration, OCI container images, Bash scripting
- **Key concepts:**
  - **Workspaces:** Each `workspaces/<name>/` directory defines a group of related plugins with `source.json` (upstream repo/commit) and `plugins-list.yaml` (plugins to export)
  - **Overlays:** Replace/add entire files in plugin source before building (`plugins/<name>/overlay/`)
  - **Patches:** Apply line-by-line diffs at workspace level (`patches/*.patch`)
  - **OCI tags:** `bs_<backstage_version>__<plugin_version>` (e.g., `bs_1.45.3__2.4.3`)
  - **Branching:** `main` for next RHDH release; `release-x.y` branches for specific releases
- **Companion repo:** Works closely with `rhdh-plugin-export-utils`

### rhdh-plugin-export-utils

- **Upstream:** <https://github.com/redhat-developer/rhdh-plugin-export-utils>
- **Description:** Collection of reusable GitHub Actions and callable workflows for exporting, packaging, and validating Backstage plugins as dynamic plugins for RHDH. Primary consumer is `rhdh-plugin-export-overlays`.
- **Tech stack:** GitHub Actions (composite actions), Bash scripting, TypeScript (validate-metadata)
- **Key concepts:**
  - **`override-sources` action:** Applies workspace-level patches then per-plugin source overlays.
  - **`export-dynamic` action:** Iterates `plugins-list.yaml`, runs CLI export per plugin, optionally packages as OCI image. Supports skip-if-unchanged via `last-publish-commit`.
  - **`validate-metadata` action:** Validates `metadata/*.yaml` files against `plugins-list.yaml` and `package.json`.
  - **`update-overlay` action:** Proposes overlay workspace PRs via GitHub API for auto-discovered plugin versions.
  - **Callable workflows:** `export-dynamic.yaml` (single-workspace pipeline), `export-workspaces-as-dynamic.yaml` (multi-workspace orchestrator), `update-plugins-repo-refs.yaml` (npm discovery), `check-backstage-compatibility.yaml` (compatibility report).
  - **Branching:** Single `main` branch only. All consumers reference actions at `@main`.

### rhdh-plugin-export-backstage-backstage

- **Upstream:** <https://github.com/redhat-developer/rhdh-plugin-export-backstage-backstage>
- **Description:** Exports dynamic plugins directly from the upstream `backstage/backstage` repository for use in RHDH. A GitHub Actions workflow checks out a `backstage/backstage` release tag, exports specified plugins as dynamic plugin archives (`.tgz`), and publishes them as GitHub release assets.
- **Tech stack:** GitHub Actions, Node.js, NPM packaging
- **Key concepts:**
  - **Release-aligned exports:** GitHub releases match `backstage/backstage` tags (e.g., `v1.23.4`). Each release contains `.tgz` plugin archives, `.tgz.integrity` SHA files, and optional `app-config.dynamic.yaml` for frontend wiring.
  - **Plugin list:** `plugins-list.yaml` defines which plugins to export; skipped plugins are commented with explanations.
- **Key paths:** `.github/workflows/export-dynamic.yaml` (export workflow), `plugins-list.yaml` (plugin list, on release branches)

### rhdh-plugin-catalog

- **Upstream:** <https://gitlab.cee.redhat.com/rhidp/rhdh-plugin-catalog>
- **Description:** Midstream infrastructure repository that manages building, packaging, and publishing Backstage plugins as OCI artifacts for RHDH. Syncs plugin source from `rhdh-plugin-export-overlays`, builds plugins via Konflux CI/CD, and maintains a catalog index of all available plugins. Publishes to `quay.io/rhdh/` and `registry.redhat.io/rhdh/`.
- **Tech stack:** Node.js, TypeScript, Yarn 3, Backstage CLI, Python (build scripts), Tekton/Konflux pipelines, Docker/Podman
- **Key concepts:**
  - **Workspaces:** 24 plugin workspace directories under `workspaces/`. Each is an independent monorepo with `packages/`, `plugins/`, `package.json`, `yarn.lock`, `manifest.json`, and `backstage.json`.
  - **Catalog index:** `catalog-index/index.json` is the master catalog of all plugins. Generated by `build/scripts/generateCatalogIndex.py`.
  - **Konflux pipelines:** 114 Tekton PipelineRun definitions in `.tekton/`. Each plugin has a dedicated pipeline triggered by changes to its workspace directory.
  - **Upstream sync:** `build/ci/sync-midstream.sh` syncs overlays from `rhdh-plugin-export-overlays` into `overlay-repo/`, updates `plugin_builds/` metadata, and regenerates the catalog index.
  - **Branching:** `main` for active development; `rhdh-*-rhel-9` for 1.Y release midstream; `release-2.Y` for 2.Y.
- **Key paths:** `workspaces/` (plugin source), `plugin_builds/` (build metadata), `catalog-index/` (catalog index and default configs), `.tekton/` (Konflux pipelines), `build/scripts/` (build automation scripts)

### rhdh-plugins

- **Upstream:** <https://github.com/redhat-developer/rhdh-plugins>
- **Description:** Central repository for Backstage plugins developed by Red Hat for use with RHDH. Multi-workspace monorepo modeled after `backstage/community-plugins`. Each workspace is an independent mini-monorepo with its own `yarn.lock`, release cycle, and changeset history. Publishes to `@red-hat-developer-hub` npm namespace.
- **Tech stack:** Node.js 22, TypeScript, Yarn 4 (Berry, `node-modules` linker), Backstage plugin SDK, Jest, Playwright
- **Key concepts:**
  - **Workspace independence:** Each `workspaces/<name>/` has its own `package.json` (named `@internal/<name>`, `private: true`), `yarn.lock`, `.changeset/`, and `backstage.json`. Run `yarn install` from within the workspace, not the root.
  - **Workspace structure:** `workspaces/<name>/packages/app/` (dev frontend), `packages/backend/` (dev backend), `plugins/<plugin-name>/` (publishable plugins). Plugin packages follow `-backend`, `-common`, `-node` suffix conventions.
  - **Changesets:** `yarn changeset` from workspace root. On merge to `main`, automation creates a "Version Packages" PR on `changesets-release/<workspace>/main` branch.
  - **Notable workspaces:** `bulk-import`, `intelligent-assistant` (AI assistant), `orchestrator` (SonataFlow), `homepage`, `theme`, `extensions`, `global-header`, `adoption-insights`, `scorecard`, `ai-integrations`, `translations`, `konflux`, `mcp-integrations`.
  - **Creating new workspace:** `yarn create-workspace` from repo root. Creating a plugin within a workspace: `cd workspaces/<name> && yarn new`.
  - **Branching:** `main` for active development; `1.2` for release maintenance; `changesets-release/<workspace>/main` for automated version PRs.
- **Key paths:** `workspaces/` (all plugin workspaces), `scripts/ci/` (CI helper scripts), `.github/CODEOWNERS` (per-workspace ownership)

### rhdh-plugin-certification

- **Upstream:** <https://github.com/redhat-developer/rhdh-plugin-certification>
- **Description:** Certification workflow for third-party plugins with RHDH. Partners submit a `package.yaml` via PR under `partner/<org>/<plugin>/<version>/`, and an automated CI/CD pipeline runs compatibility checks and smoke tests against RHDH.
- **Tech stack:** GitHub Actions, YAML, Helm
- **Key concepts:**
  - **PR-based certification:** Partners fork the repo, add plugin metadata under `partner/`, and submit a PR to trigger the pipeline.
  - **Automated validation:** CI runs RHDH compatibility checks and basic smoke tests.
  - **Certified plugins list:** `certified-plugins.yaml` tracks all certified plugins.
- **Key paths:** `certified-plugins.yaml` (certified plugin registry), `partner/` (partner submissions), `rhdh-helm-values.yaml` (test Helm values)

### rhdh-dynamic-plugin-factory

- **Upstream:** <https://github.com/redhat-developer/rhdh-dynamic-plugin-factory>
- **Description:** Container image and tooling for building dynamic plugins locally. Provides a pre-configured build environment with all necessary dependencies (Node.js, Yarn, Backstage CLI) so plugin authors can export and package plugins without setting up a full development environment. Used via `podman` or `docker`.
- **Tech stack:** Container (Podman/Docker), Node.js, Yarn, Backstage CLI
- **Key concepts:**
  - **Container-based builds:** Run `podman run` or `docker run` with the factory image to build plugins in an isolated environment.
  - **Used by overlay workflows:** `rhdh-plugin-export-overlays` can use the factory container for local plugin builds.
- **Key paths:** `Containerfile` (image definition)

### rhdh-skills-private-data

- **Upstream:** <https://gitlab.cee.redhat.com/rhidp/rhdh-skills-private-data>
- **Description:** Jira Rich Filter exports and operational data used by RHDH skills. Contains exported Rich Filter JSON from the "RHIDP Operational" Jira Rich Filter managed by Matt Reid and Jasper Chui.
- **Key concepts:**
  - **Rich Filter exports:** JSON exports from Jira Rich Filters that define project-scoped queries, component exclusion lists, team Cloud ID mappings, and queue definitions. Used by the `rhdh-release-status` skill to source JQL queries at runtime instead of hardcoding them.
  - **Discovery:** Located via `rhdh.config.get_repo("private-data")` — configure with `rhdh config set private-data /path`.
- **Key paths:** `jira-rich-filter/rhidp-operational-rich-filter.json` (Rich Filter export)

### backstage

- **Upstream:** <https://github.com/backstage/backstage>
- **Description:** The upstream Backstage framework — the CNCF open-source foundation that RHDH is built upon. Originally created by Spotify. Provides the core Software Catalog, Software Templates, TechDocs, Search, and the plugin system.
- **Tech stack:** Node.js, TypeScript, React, Yarn Berry, PostgreSQL
- **Key concepts:**
  - **New backend system (current standard):** `createBackendPlugin()`, `createBackendModule()`, `createServiceRef()`, `createExtensionPoint()` from `@backstage/backend-plugin-api`. Services are dependency-injected via `coreServices`.
  - **Plugin package sets:** A feature like "catalog" spans multiple packages: `-backend` (backend plugin), `-node` (extension points/shared backend types), `-react` (shared React hooks/components), `-common` (isomorphic shared code), `-backend-module-*` (backend modules).
  - **Software Catalog:** Central entity registry. Entity lifecycle: Ingestion (entity providers) -> Processing (processors validate/enrich/emit relations) -> Stitching (assemble final entity). Entity kinds: Component, API, Resource, System, Domain, User, Group, Location, Template.
  - **Release cadence:** Monthly minor releases (`v1.X.0`), patch releases as needed. Individual packages have their own semver; `@backstage/release-manifests` maps package versions to Backstage releases.
  - **Branching:** `master` (not `main`) is the default branch. No long-lived release branches — releases are tags from `master`.
- **Key paths:** `packages/` (core framework packages), `plugins/` (~155 plugin packages), `docs/` (documentation)

### red-hat-developers-documentation-rhdh

- **Upstream:** <https://github.com/redhat-developer/red-hat-developers-documentation-rhdh>
- **Description:** Upstream source for RHDH product documentation published at [docs.redhat.com](https://docs.redhat.com/en/documentation/red_hat_developer_hub/). Syncs downstream to `gitlab.cee.redhat.com/red-hat-developers-documentation/rhdh`. All content is in AsciiDoc following Red Hat modular documentation guidelines.
- **Tech stack:** AsciiDoc, Node.js (build tooling), Vale (style linting), Lychee (link checking), Podman (local builds)
- **Key concepts:**
  - **Modular docs:** Content follows Red Hat supplementary style guide and modular documentation reference.
  - **Jira integration:** PRs require an associated Jira issue (RHDHBUGS, RHIDP, or RHDHPLAN projects).
  - **Release notes:** Single-sourced from Jira, not maintained in this repo.
- **Key paths:** `artifacts/` (shared attributes and snippets), `additional-capabilities/` (capability-specific docs)

### rhdh-examples

- **Upstream:** <https://github.com/redhat-developer/rhdh-examples>
- **Description:** Reference code examples for RHDH product documentation. Contains sample plugins demonstrating catalog backend modules (GitHub org transformer, GitLab org transformer, Keycloak org transformer). For reference only — not maintained to work out of the box across releases.
- **Key paths:** `plugins/` (example plugin implementations)

### rhdh-techdocs-pipeline

- **Upstream:** <https://github.com/redhat-developer/rhdh-techdocs-pipeline>
- **Description:** GitHub Actions workflow that builds and publishes TechDocs documentation to an AWS S3 bucket for consumption by RHDH instances configured in external TechDocs builder mode.
- **Tech stack:** GitHub Actions, MkDocs (techdocs-core, minify plugins), AWS S3
- **Key concepts:**
  - **External builder mode:** Docs are pre-built and uploaded to S3, not generated at runtime by Backstage.
  - **Entity-linked docs:** Uses `backstage.io/techdocs-ref` annotation in `catalog-info.yaml` to link docs to catalog entities.
- **Key paths:** `.github/workflows/generate-and-publish-techdocs.yaml` (build/publish workflow), `mkdocs.yaml` (MkDocs config), `catalog-info.yaml` (entity definition)

### rhdh-static-content

- **Upstream:** <https://github.com/redhat-developer/rhdh-static-content>
- **Description:** Static content assets for Red Hat Developer Hub.

### rhdh-adr

- **Upstream:** <https://github.com/redhat-developer/rhdh-adr>
- **Description:** Architecture Decision Records for RHDH projects. Central repository for cross-project architectural decisions. ADR lifecycle is driven by GitHub PR state: Open = Proposed, Merged = Accepted, Closed = Rejected.
- **Key concepts:**
  - **PR-based workflow:** Write ADR using template, open PR, announce in team channel with 1-week review window, merge when consensus reached.
  - **AI-assisted drafting:** Includes Claude Code `/adr` skill guide (`ADR-AI-GUIDE.md`).
  - **Existing decisions:** Flavor-based config, plugin catalog CRD, operator plugin config processing, OLMv1 adoption, CRD version management.
- **Key paths:** `decisions/` (accepted ADRs), `ADR-TEMPLATE.md` (template), `ADR-GUIDE.md` (writing guide), `ADR-APPROVAL-GUIDELINES.md` (review process)

### rhdh-workflows

- **Upstream:** <https://github.com/redhat-developer/rhdh-workflows>
- **Description:** Collection of reusable GitHub Actions workflows for consumption by other RHDH repositories. Shared CI/CD infrastructure for the RHDH ecosystem.
- **Tech stack:** GitHub Actions, YAML

### rhdh-fullsend

- **Upstream:** <https://github.com/redhat-developer/rhdh-fullsend>
- **Description:** Custom sandbox images, deployment documentation, and the `/fullsend` Claude Code skill for the RHDH team's agent infrastructure. Extends the upstream `fullsend-code` image with corepack and yarn for JavaScript monorepo support.
- **Tech stack:** Docker/Podman, GitHub Actions, Claude Code skills
- **Key concepts:**
  - **Custom sandbox image:** `ghcr.io/redhat-developer/rhdh-fullsend-code:latest` adds `corepack enable` and pre-downloaded yarn binary to the upstream `fullsend-code` image.
  - **`/fullsend` skill:** RHDH-specific Claude Code skill for validating configs, debugging sandboxes, and building custom agents.
  - **Tags:** `latest` (production), `dev` (non-PR builds), `X.Y.Z` (immutable release), `<sha>` (debugging).
- **Key paths:** `blueprints/` (infrastructure blueprints), `docs/` (GCP infrastructure and sandbox networking), plus the repository's Fullsend agent skill

### rhdh-skills

- **Upstream:** <https://github.com/redhat-developer/rhdh-skills>
- **Description:** Composable agent-skill collection for RHDH development and operations. Published via the [Agent Skills](https://agentskills.io) open standard.
- **Tech stack:** Python (stdlib-only CLIs), Bash, Claude Code skills
- **Key concepts:**
  - **Composition:** Two human entry skills route setup and discovery; model skills compose by invoking each other by name and reading what the invoked skill reports.
  - **Skills:** Plugin and Overlay development, local testing, Prow and Konflux CI, PR review, Jira, releases, lifecycle support, and base-image maintenance.
- **Key paths:** `skills/` (all skill definitions), plus that repository's own domain glossary and architectural decision records

### rhdh-users-skill-pack

- **Upstream:** <https://github.com/redhat-developer/rhdh-users-skill-pack>
- **Description:** Agent Skills for adopting and using RHDH effectively. Aimed at RHDH end-users (vs `rhdh-skills` which targets the development team). Published via the [Agent Skills](https://agentskills.io) open standard.
- **Tech stack:** Python (stdlib-only CLIs), Bash, Claude Code skills
- **Key concepts:**
  - **`rhdh-templates`:** Interactive authoring and validation for RHDH Software Templates — templatize existing repos, create from scratch, fix common gotchas, validate locally or against a running instance.
  - **`rhdh-upgrade-helper`:** Upgrade assessment for RHDH — resolves OCI plugin references, validates tags, searches RHDHBUGS Jira for known bugs, filters breaking changes by config, computes a 0–100 Readiness Score.
  - **`skill-maker`:** Create, audit, and consolidate Agent Skills following the open standard.
- **Key paths:** `skills/rhdh-templates/` (template authoring skill), `skills/rhdh-upgrade-helper/` (upgrade assessment skill), `skills/skill-maker/` (skill creation tool)

## Ecosystem Relationships

```
backstage (upstream framework)
    |
    v
rhdh (enterprise distribution, github.com)
    |
    +---> rhdh-downstream (productized build, gitlab.cee.redhat.com)
    |         builds from rhdh, produces registry.redhat.io images
    |
    +-- rhdh-cli (plugin development tooling)
    +-- rhdh-plugins (Red Hat plugin collection)
    |
    +-- Plugin packaging & distribution:
    |   +-- rhdh-plugin-export-overlays (community plugin packaging & OCI publishing)
    |   |       uses rhdh-plugin-export-utils (reusable GitHub Actions)
    |   +-- rhdh-plugin-export-backstage-backstage (upstream backstage plugin exports)
    |   +-- rhdh-plugin-catalog (midstream plugin builds, OCI artifacts & catalog index)
    |   |       syncs from rhdh-plugin-export-overlays
    |   +-- rhdh-plugin-certification (third-party plugin certification)
    |   +-- rhdh-dynamic-plugin-factory (container for local plugin building)
    |
    +-- Deployment:
    |   +-- rhdh-operator (Kubernetes/OpenShift operator)
    |   +-- rhdh-chart (Helm chart)
    |
    +-- Testing & diagnostics:
    |   +-- rhdh-local (local dev/test environment)
    |   +-- rhdh-test-instance (automated test environment provisioning)
    |   +-- rhdh-loadtest (load testing infrastructure & synthetic catalog entities)
    |   +-- rhdh-e2e-test-utils (shared E2E test utilities)
    |   +-- rhdh-must-gather (diagnostic data collection)
    |
    +-- Documentation:
    |   +-- red-hat-developers-documentation-rhdh (product docs, docs.redhat.com)
    |   +-- rhdh-examples (reference code for docs)
    |   +-- rhdh-techdocs-pipeline (TechDocs build & publish to S3)
    |   +-- rhdh-static-content (static content assets)
    |   +-- rhdh-adr (architecture decision records)
    |
    +-- CI/CD & infrastructure:
    |   +-- rhdh-workflows (reusable GitHub Actions workflows)
    |   +-- rhdh-fullsend (agent sandbox images & /fullsend skill)
    |
    +-- Agent skills:
        +-- rhdh-skills (dev team skills — overlay, lifecycle, prow, etc.)
        +-- rhdh-users-skill-pack (user skills — templates, upgrade helper)
```

## Common Workflows

- **Plugin development:** Work in `rhdh-plugins`, use `rhdh-cli` to export/package, test with `rhdh-local`
- **Core RHDH changes:** Work in `rhdh`, reference `backstage` for upstream behavior
- **Deployment/operator changes:** Work in `rhdh-operator` or `rhdh-chart`
- **Plugin packaging:** Work in `rhdh-plugin-export-overlays` to add/update plugins as dynamic plugins; uses actions from `rhdh-plugin-export-utils`
- **Plugin certification:** Partners submit to `rhdh-plugin-certification` for third-party plugin validation
- **Midstream plugin builds:** Work in `rhdh-plugin-catalog` for Konflux pipeline management, catalog index updates, and OCI artifact publishing to Red Hat registries
- **Base image maintenance:** Invoke `/rhdh-base-images` (`--analyze` to scan, or full run with scripts from `rhdh-downstream` `build/scripts/`)
- **CI/CD actions for plugins:** Work in `rhdh-plugin-export-utils` to modify the reusable GitHub Actions
- **Load testing:** Use `rhdh-loadtest` for synthetic catalog entities and multi-version RHDH deployments
- **Diagnostics:** Run `rhdh-must-gather` on OpenShift (`oc adm must-gather`) or Kubernetes (Helm chart) to collect RHDH-specific logs and configs
- **Documentation:** Work in `red-hat-developers-documentation-rhdh` for product docs; use `rhdh-techdocs-pipeline` for TechDocs publishing
- **Architecture decisions:** Propose ADRs in `rhdh-adr` via PR workflow
