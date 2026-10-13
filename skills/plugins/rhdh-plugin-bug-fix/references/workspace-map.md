# Workspace Map: Issue Fields to Workspace Directories

Maps issue metadata (Jira Components, GitHub labels, issue body fields) to workspace directories in `rhdh-plugins` and `community-plugins`. Used in Step 2 to identify which workspace a bug belongs to and which repo to target.

> **Last verified:** July 2026 against `redhat-developer/rhdh-plugins` main branch. If a component is not found in the table below, the skill falls back to asking the user which workspace to target.

## Component-to-Workspace Mapping

| Jira Component | Workspace Directory | Has E2E Tests | E2E Modes |
|----------------|-------------------|---------------|-----------|
| Adoption Insights | `adoption-insights` | Yes | legacy + nfs |
| Bulk Import | `bulk-import` | Yes | legacy + nfs |
| Extensions | `extensions` | Yes | legacy + nfs |
| Homepage | `homepage` | Yes | legacy + nfs |
| Intelligent-Assistant | `intelligent-assistant` | Yes | legacy + nfs |
| Global Header | `global-header` | Yes | legacy only |
| Quickstart | `quickstart` | Yes | legacy + nfs |
| Scorecard | `scorecard` | Yes | legacy + nfs |
| Localization | ⚠️ cross-cutting — see below | Yes | unknown |
| DCM | `dcm` | Config only | n/a |
| Orchestrator | `orchestrator` | No | n/a |
| MCP | `mcp-integrations` | No | n/a |

### Cross-cutting components

Some Jira Components do not map 1:1 to a workspace. **Localization** is the primary example — it is added to issues about broken or missing translations in *any* plugin, not just the shared `translations` workspace.

When the issue has a cross-cutting component, disambiguate the actual workspace:

1. **Second Component** — if the issue has another Component alongside Localization (e.g., `Localization` + `Intelligent-Assistant`), use the second component to resolve the workspace via the table above.
2. **Issue description** — scan for plugin or workspace references (e.g., `@red-hat-developer-hub/backstage-plugin-intelligent-assistant`, `intelligent-assistant` workspace, `workspaces/intelligent-assistant/plugins/`).
3. **Only target `translations`** if the issue is about the shared i18n framework itself (e.g., `getTranslations()` utility, locale configuration, shared tooling) and no specific plugin is mentioned.
4. **Fallback** — ask the user: "The Localization component is cross-cutting. Which workspace contains the affected plugin?"

### Workspaces without Jira component mapping

These workspaces exist in `rhdh-plugins` but may not have a direct Jira Component match. If the Jira issue's Component doesn't match the table above, ask the user which workspace to target.

- `ai-integrations`, `app-defaults`, `augment`, `boost`, `cost-management`
- `install-dynamic-plugins`, `konflux`, `noop`, `repo-tools`, `theme`, `x2a`

## Runtime Discovery

After identifying the workspace directory, discover its e2e infrastructure dynamically. Do not hardcode workspace-specific details in this file.

### Step 1: Read Playwright config

```
workspaces/<dir>/playwright.config.ts
```

Extract:

- `LOCALES` array (typically `['en', 'de', 'es', 'fr', 'it', 'ja']`)
- `FRONTEND_PORT_BASE` and `BACKEND_PORT_BASE`
- `APP_MODE` support (look for `process.env.APP_MODE`)
- `startCommand` (legacy vs nfs)
- `webServer` configuration

### Step 2: Scan e2e helpers

```
workspaces/<dir>/e2e-tests/utils/
```

Common files across workspaces:

- `translations.ts` — `getTranslations()` helper for i18n-safe selectors
- `insightsHelpers.ts` / `testHelper.ts` / `helpers.ts` — workspace-specific navigation and interaction helpers
- `accessibility.ts` — accessibility testing utilities
- `localeSkip.ts` — locale-specific test skipping logic
- `events.ts` / `apiUtils.ts` — API mocking and data seeding

### Step 3: Read translation keys

```
workspaces/<dir>/plugins/*/src/translations/ref.ts
```

Contains the full translation key structure. Use these keys with `getTranslations()` to build i18n-safe Playwright selectors like `page.getByText(translations.header.dateRange.defaultLabel)`.

### Step 4: Map components to source files

```
workspaces/<dir>/plugins/*/src/components/
```

Scan the component directory tree to understand which React components render which UI elements. This mapping is used during diagnosis (Step 5) to trace from a failing Playwright selector back to the source code.

## Fuzzy Matching (rhdh-plugins)

Jira Component names don't always match workspace directory names exactly. Apply these rules:

1. Lowercase and hyphenate the component name: "Adoption Insights" → `adoption-insights`
2. Check for known aliases and cross-cutting components (e.g., "Localization" — see disambiguation rules above)
3. If no match, list all workspace directories and ask the user to pick one

---

## community-plugins Workspace Detection

`backstage/community-plugins` has 100+ workspaces that change frequently. Rather than hardcoding a static mapping, detect the workspace dynamically from the issue.

### From GitHub issues

`/rhdh-forge` resolves the workspace from a GitHub issue and reports which
strategy answered it — `label`, `body`, `title`, `package`, or `unresolved`.
Treat that name as a candidate and confirm the directory exists in the checkout;
when the strategy is `unresolved`, ask the user which workspace to target.

### From Jira issues

A Jira issue could target either repo. Use the Jira Component field to identify the workspace, then determine which repo owns it:

1. Check the Component against the rhdh-plugins mapping table above.
2. If no match in rhdh-plugins workspaces, the issue likely targets community-plugins — ask the user to confirm and specify the workspace.
3. If the Component is absent or ambiguous — ask the user: "Which repo does this issue target? (1) rhdh-plugins (2) community-plugins"

### Runtime discovery

After identifying the workspace directory in community-plugins, the same runtime discovery process applies as for rhdh-plugins:

1. Read `workspaces/<dir>/playwright.config.ts` (if present) for e2e configuration.
2. Scan `workspaces/<dir>/e2e-tests/utils/` for helper functions.
3. Read `workspaces/<dir>/plugins/*/src/` for component and translation structure.

Many community-plugins workspaces do NOT have Playwright e2e tests. When `playwright.config.ts` is absent, the skill operates in no-e2e mode (diagnose + fix + unit test verification, no video recordings).
