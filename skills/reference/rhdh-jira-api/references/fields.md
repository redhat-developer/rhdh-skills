# Fields, Labels, Links, Components & Priorities

## Custom Fields

| Field | ID | Type | Notes |
|-------|-----|------|-------|
| Team | `customfield_10001` | `atlassian-team` | **NOT JQL-filterable.** Fetch all, filter by `.name` in post-processing. Returns complex object in JSON: `{id, name, title, avatarUrl, isShared, ...}` |
| Size | `customfield_10795` | dropdown | T-shirt sizing: XS, S, M, L, XL. Returns `{value: "M"}` in JSON. |
| Story Points | `customfield_10028` | number | Primary estimation field. |
| DEV Story Points | `customfield_10506` | number | Inconsistently populated. |
| QE Story Points | `customfield_10572` | number | Inconsistently populated. |
| DOC Story Points | `customfield_10510` | number | Inconsistently populated. |
| Epic Link | `customfield_10014` | issue key | Legacy field — prefer `parent` for new hierarchy. |
| Parent Link | `customfield_10018` | issue key | Links Epic → Feature cross-project. |
| Sprint(s) | `customfield_10020` | array | Array of sprint objects with `name`, `state`, `startDate`, `endDate`. Not available via `--fields` — use `--json`. |
| Release Note Type | `customfield_10785` | dropdown | Values: Feature, Enhancement, Developer Preview, Deprecated Functionality, Removed Functionality, Release Note Not Required. |
| Release Note Text | `customfield_10783` | textarea (ADF) | Actual release note content. Should be populated when RN Type is customer-facing. |
| Acceptance Criteria | `customfield_10718` | textarea | **Almost always null.** Check description and comments instead for "Requirements", "Acceptance Criteria", or bullet-style criteria. |
| Feature Status | `customfield_10807` | dropdown | Found on RHDHPLAN Features. Values include `Proposed`. |
| Rank | `customfield_10019` | string | Lexorank ordering. Generally not needed for agent operations. |

### Custom field JQL syntax

Use `cf[ID]` syntax in JQL for custom fields:

```jql
-- Story points empty
cf[10028] is EMPTY

-- Size is set
cf[10795] is not EMPTY

-- Release Note Type missing
cf[10785] is EMPTY
```

## Standard Fields

| Field | JQL Name | Notes |
|-------|----------|-------|
| Fix Version | `fixVersion` | Version targeting. `fixVersion = '1.10.0'` |
| Affects Version | `affectedVersion` | Used in RHDHBUGS for bug version tracking. |
| Components | `component` | JQL-filterable: `component = 'Documentation'`. Not available via `--fields` — use `--json`. |
| Parent | `parent` | Native hierarchy: sub-task → parent, epic → feature. `parent = RHDHPLAN-382` |
| Security Level | `security` | Present on RHIDP/RHDHPLAN (`"Red Hat Employee"`), typically null on RHDHBUGS/RHDHSUPP. **NOT JQL-filterable** — `security is not EMPTY` returns parse error. |

## Labels

Most labels are lowercase and hyphen-separated. Labels are global to the Jira instance. **Exception:** prefer the capitalization `RHDH-Customer` when applying that label (see below).

| Label | Usage |
|-------|-------|
| `demo` | Customer-facing Features/Epics requiring a feature demo. Decided during Feature Exploration — `/rhdh-jira-refine` owns that checklist. |
| `needs-info` | Release planning — needs more information from the feature reporter (Engineering → reporter) |
| `needs-pm` | Release planning — needs product management input |
| `stretch` | Feature is a stretch goal for a release |
| `rhdh-testday` | Feature should be tested as part of release test day. Set during Feature Exploration. |
| `quality` | Continuous improvement issues. **Excluded from code freeze release queries** — use this label (not `ci`) to ensure the issue doesn't block a code freeze. |
| `rhdh-n.n-candidate` | Feature is a candidate for release n.n (e.g., `rhdh-2.1-candidate`). **Do not remove without PM approval** — removing this label can silently drop a feature from release tracking. |
| `ci-fail` | Identifies CI failures |
| `must-have` | Documentation team — must-have for release doc plan |
| `nice-to-have` | Documentation team — nice-to-have for release doc plan |
| `RHDH-Customer` | Issues from customer interactions (support cases, engagements). **Preferred capitalization.** Apply this label alone — never also apply `rhdh-customer`. Jira label search is case-insensitive, so both spellings collide in search. |
| `ga-support` | Target support level: GA (generally available) |
| `tp-support` | Target support level: Tech Preview |
| `dp-support` | Target support level: Developer Preview |

### Customer identity in unprotected fields (authoritative)

Do not put customer names or other customer-identifying detail in unprotected fields (summary, description, and other public/default-visibility fields).

**Preferred pattern:**

1. Reference the support ticket / case key (or similar non-identifying handle) in summary/description when needed.
2. Apply a single `RHDH-Customer` label for customer-origin work.
3. Put customer-identifying detail only in comments with appropriate restricted visibility (e.g. RH employee-only) when the project supports security levels — or keep identity out of Jira fields entirely and rely on the support-system link.

**Label rule:** Prefer one `RHDH-Customer` label. Never apply both `RHDH-Customer` and `rhdh-customer`.

This section is authoritative. `/rhdh-jira-create` enforces it before every create, and
`/rhdh-jira-refine` checks it during audits. RHDHSUPP ↔ RHDHBUGS project boundaries live in
`/rhdh-jira-create`.

## Link Types

Match by **name** in `issuelinks`, not by ID.

| Name | Use | Direction | Notes |
|------|-----|-----------|-------|
| Blocks | Yes — dependency tracking | inward: "is blocked by", outward: "blocks" | |
| Depend | Yes — dependency tracking | inward: "is depended on by", outward: "depends on" | |
| Related | Yes — feature-to-epic mapping | bidirectional | For cross-team deps, only include when target is outside RHDHPLAN/RHIDP |
| Cloners | **IGNORE** | — | Noise from cross-release cloning |
| Issue split | Informational only | — | |
| Duplicate | **IGNORE** | — | |

List all available link types with: `acli jira workitem link type`

## Components

Heavily used for filtering, routing, and freeze queries. Components affect Feature Freeze and Code Freeze scope — some components may be excluded from FF/CF.

Query by component: `project = RHIDP AND component = 'Documentation'`

Components are not available via `--fields` on search. Use `--json` to get component data.

### Component Catalog

Full list of RHDH project components with descriptions, grouped by category. Freeze exclusion flags indicate which components are excluded from Feature Freeze (FF), Code Freeze (CF), Post-CF, and Release Notes (RN) queries.

**RHDH Core:**

| Component | Description | Excl FF | CF | Post CF | Excl RN |
|-----------|-------------|---------|----|---------|---------|
| Adoption Insights | Plugin tracking adoption metrics and usage patterns | | | | |
| AI Demo | Demo server showcasing AI capabilities in RHDH | Yes | Yes | Yes | Yes |
| AI Installer | Automated installer for AI-related RHDH components | | | | |
| ai-templates | Software templates for AI/ML workflows and model onboarding | | | | |
| ArgoCD | ArgoCD plugin integration (Roadie version migration) | | | | |
| Authentication | Static auth provider module, dynamic auth provider, service-service auth, SCM auth | | | | |
| Build | Container image builds, Konflux pipelines, and build infrastructure | Yes | | | Yes |
| Bulk Import | Bulk import of repositories and entities into the catalog | | | | |
| Catalog | Backstage software catalog (entity metadata, sources, composability) | | | | |
| Database | PostgreSQL database support, migrations, and compatibility | | | | |
| Dynamic Plugins | Dynamic plugin loading, frontend/backend plugin lifecycle | | | | |
| Dynamic Plugins Factory | Build tooling for producing dynamic plugin artifacts | | | | |
| Event Systems | Internal event bus for cross-plugin communication | | | | |
| Extensions | Extension registry, OCI plugin hosting, and catalog sources | | | | |
| FIPS | FIPS 140-2/140-3 compliance onboarding and validation testing | | | | |
| Gitlab | Gitlab integration (SCM, events, auth provider) | | | | |
| Helm Chart | Helm chart for RHDH deployment on OpenShift/Kubernetes | | | | |
| High Availability | Multi-replica and HA deployment configurations | | | | |
| Homepage | Dynamic homepage plugin and backend | | | | |
| Intelligent-Assistant | AI-powered developer assistant plugin | | | | |
| LDAP | LDAP auth provider and entity ingestion | | | | |
| Localization | i18n and RTL language support | | | | |
| LTS | Long Term Support release stream and lifecycle management | | | | |
| MCP | Model Context Protocol server and AI permissions | | | | |
| model-catalog | AI/ML model catalog plugin for browsing and discovering models | | | | |
| model-registry-bridge | Bridge plugin connecting RHDH to OpenShift AI model registry | | | | |
| msgraph/Azure | Microsoft Graph and Azure AD integration | | | | |
| Mustgather | Diagnostic data collection tool for support case troubleshooting | | | | |
| News Feed | RSS news feed plugin | | | | |
| Operator | OLM-based operator for deploying and managing RHDH on OpenShift | | | | |
| Orchestrator | Serverless workflow orchestration plugin | | | | |
| Overlay | Overlay repository for plugin packaging and export | | | | |
| Permissions | Role-based access control (RBAC) and permission policies | | | | |
| Plugin Development | Plugin SDK, development tooling, and plugin onboarding guides | | | | |
| Quay | Quay container registry plugin | | | | |
| Quickstart | Quickstart plugin for guided setup | Yes | | | |
| RHDH CLI | CLI tooling for plugin export, dependency checks, and scaffolding | | | | |
| RHDH Local | Local development environment for running RHDH on a developer machine | Yes | | | |
| rhdh-ai-external | AI related issues for other stakeholders (RHOAI, etc) | | | | |
| RHEL | RHEL-based container image build and RPM installer | | | | |
| RHOAI Bridge | Integration bridge between RHDH and Red Hat OpenShift AI | | | | |
| Scorecard | Scorecard plugin for project health assessment | | | | |
| Segment | Product telemetry collection and analytics integration | Yes | | | |
| Tekton | Plugin for viewing and managing Tekton pipelines and tasks | | | | |
| Test Framework | Shared test utilities and helpers | Yes | | | Yes |
| Test Infrastructure | Issues related to the team's testing cluster(s) and infra | Yes | | | Yes |
| Topology | Plugin to visualise Kubernetes workloads and relationships | | | | |
| UI | RHDH frontend UI shell, theming, and layout | | | | |
| UX | User experience design, research, and usability | Yes | | | |

**Backstage (upstream):**

| Component | Description | Excl FF | CF | Post CF | Excl RN |
|-----------|-------------|---------|----|---------|---------|
| Actions | Scaffolder actions for software template steps | | | | |
| Audit Log | Audit logging and verification for compliance | | | | |
| Catalog | Backstage software catalog (upstream) | | | | |
| Community Plugin | Track updates to Community Plugin repository | | | | Yes |
| Core Platform & Lifecycle | Backstage core framework, app lifecycle, and platform APIs | | | | |
| Corporate Proxy | Proxy configuration for corporate/enterprise network environments | | | | |
| Event Module | Backstage event module for plugin-to-plugin messaging | | | | |
| Github | GitHub integration (SCM, actions, auth, discovery) | | | | |
| Kubernetes | Kubernetes plugin for cluster and workload visibility | | | | |
| Notifications | Email and in-app notification plugins | | | | |
| On Behalf Of | On-behalf-of (OBO) token delegation for service-to-service auth | | | | |
| Proxy | Backstage backend proxy for forwarding API requests to external services | | | | |
| Redis | Redis caching and session store integration | | | | |
| RHDH Plugin Repo | RHDH-specific plugin repository and distribution | Yes | Yes | Yes | |
| Software Templates | Scaffolder templates for project and component creation | | | | |
| TechDocs | Technical documentation generation and rendering | | | | |
| Upstream & Community | Tracking Backstage contributions | Yes | Yes | Yes | |

**Extension Plugins:**

| Component | Description | Excl FF | CF | Post CF | Excl RN |
|-----------|-------------|---------|----|---------|---------|
| 3rd Party Plugin | Plugins for products not built by Red Hat | | | | Yes |
| 3scale | 3scale API management plugin | | | | |
| ACR | Azure Container Registry plugin | | | | |
| Keycloak Provider | Keycloak auth provider and entity ingestion | | | | |
| Nexus Repository Manager | Nexus Repository Manager plugin | | | | |
| Open Cluster Management | OCM multi-cluster management plugin | | | | |
| Regex | Regex-based entity provider plugin | | | | |
| ServiceNow | ServiceNow integration plugin | | | | |

**Program (non-engineering):**

| Component | Description | Excl FF | CF | Post CF | Excl RN |
|-----------|-------------|---------|----|---------|---------|
| AEM Migration | Adobe Experience Manager to docs-as-code migration | Yes | Yes | Yes | Yes |
| AI | Internal team initiatives leveraging AI for productivity and tooling | Yes | Yes | Yes | Yes |
| Certification | Plugin certification process and compliance verification | Yes | | | Yes |
| Conference | Conference talk preparation, demos, and booth materials | Yes | Yes | Yes | Yes |
| Continuous Improvement | Tracks opportunities to improve team efficiency | Yes | Yes | Yes | Yes |
| Documentation | Downstream product documentation (guides, API refs, release notes) | Yes | Yes | | |
| JTBD | Jobs to Be Done - Doc team | Yes | Yes | Yes | Yes |
| Knowledge | Blogs, articles, KCS artifacts to supplement downstream docs | Yes | Yes | Yes | Yes |
| Performance | Performance and Scaling for RHDH | Yes | Yes | | |
| PQC | Post-quantum cryptography readiness and compliance | Yes | Yes | | |
| Quality | Quality Engineering for RHDH | Yes | | | |
| Release | Release engineering, version management, and GA/z-stream processes | Yes | Yes | | Yes |
| Security | Security related JIRAs & CVEs | Yes | Yes | Yes | |
| Security Tooling | Security tooling like CVE status checker | Yes | Yes | Yes | Yes |
| Serviceability | Surfacing internal diagnostics and catalog health info | Yes | | | |
| Support | Customer support case tracking and engineering follow-up | Yes | Yes | | Yes |
| Team Operations | Scrum ceremonies, team process improvements, and operational tasks | Yes | Yes | Yes | Yes |

### Component Inference

When suggesting components during issue creation or refinement:

1. **Chained from parent:** Inherit the parent Feature's or Epic's components as the starting point
2. **Standalone:** Match keywords in the summary and description against the component catalog above
3. **Validate** the proposed components exist in the target project (RHIDP vs RHDHPLAN have different component sets)
4. **Flag mismatches** — if a component doesn't exist in the target project, suggest the closest match
5. **Confirm** with the user before setting — never auto-set components without confirmation

If the issue involves documentation, set the `Documentation` component. The Doc Epic automation is a
Jira UI action (**Feature → More → Create Doc EPIC from RHDHPlan**) available only for the
`Documentation` component — prompt the user to run it; an agent cannot.

### Component Validation (live)

The component catalog above is maintained manually. Components may be added or renamed in Jira without updating this file. Run the validation script to detect drift:

```bash
python scripts/validate_components.py        # human-readable report
python scripts/validate_components.py --json  # structured output
```

The script compares this catalog against live components in RHIDP and RHDHPLAN. It reports components that exist in Jira but are missing from this file (add them), and components listed here that no longer exist in Jira (remove them).

Note: Jira may contain legacy or duplicate components that were never cleaned up. Not every Jira component needs to be in this catalog — only components that are actively used for issue routing and freeze queries.

`/rhdh-jira-refine` owns the full Feature Exploration checklist that consumes this catalog.

## Priorities

| Priority | Notes |
|----------|-------|
| Blocker | Highest. Used for critical z-stream fixes. |
| Critical | High urgency. |
| Major | Standard priority for most work. |
| Normal | Used in RHDHSUPP. Not a standard Jira default. |
| Minor | Low priority. |
| Undefined | **Most common in RHIDP** (~300 open issues). Hygiene signal — should be set. |

## Hierarchy Model

Three JQL fields for hierarchy with subtly different behavior:

| JQL Field | What It Returns | When to Use |
|-----------|----------------|-------------|
| `parent = KEY` | Native Jira hierarchy (sub-task → task, epic → feature) | **Preferred.** Use for all new queries. |
| `'Epic Link' = KEY` | Legacy field — stories linked to an epic | Use only for older data that hasn't migrated. |
| `parentEpic = KEY` | Similar to Epic Link but slightly different results | Avoid unless specifically needed. |

Safest approach: always use `parent = KEY`.
