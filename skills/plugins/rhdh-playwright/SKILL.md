---
name: rhdh-playwright
description: >-
  Use when navigating, testing, or verifying a RHDH instance via
  playwright-cli. Covers guest login, sidebar navigation, catalog browsing,
  entity page inspection, tab verification, and plugin exploration. Trigger on
  "check RHDH", "verify catalog entity", "entity should have tab",
  "navigate RHDH", or any RHDH UI testing task.
compatibility: "playwright-cli on PATH."
allowed-tools: Bash(playwright-cli:*)
---

# Play RHDH

Automate RHDH UI navigation and verification using `playwright-cli` (NOT the Playwright MCP).

## Quick Start

Run `command -v playwright-cli` before opening the browser. If it is missing,
stop and report that the local `playwright-cli` prerequisite is unavailable.

```bash
# Always use --browser chromium
playwright-cli open <RHDH_URL> --browser chromium
```

The URL is never hardcoded — the user provides it (or it comes from context like CLAUDE.md).

## Authentication — Guest Login

After opening a RHDH instance, check whether a login page appeared. If the page title contains "Sign In" or "Log in", or the snapshot shows sign-in buttons, log in as guest:

```bash
# Take a snapshot to check for login
playwright-cli snapshot

# If a login page is detected, look for a guest sign-in option:
#   - Button or link matching: "Enter" (on guest sign-in provider card)
#   - Or a "Guest" / "Sign in as Guest" button
# Click it:
playwright-cli click "<ref>"      # ref of the guest sign-in button
```

RHDH login pages typically show provider cards. The guest provider shows a title like "Guest" with an "Enter" button. Click the "Enter" button on the guest card.

After login, verify navigation succeeded by checking that the sidebar appeared:

```bash
playwright-cli snapshot --depth 3
# Confirm: navigation "sidebar nav" is present
```

## Sidebar Navigation

The sidebar uses `navigation "sidebar nav"` containing links. Navigate by clicking the link with the target label.

| Destination | Selector pattern |
|---|---|
| Home | `link "Home"` |
| Catalog | `link "Catalog"` |
| APIs | `link "APIs"` |
| Docs | `link "Docs"` |
| Create | `link "Create"` |
| Explore | `link "Explore"` |
| Settings | `link "Settings"` |
| Notifications | `link "Notifications"` |
| Search | `button "Search"` |

Additional sidebar items (plugins) appear below a separator. Their labels match their menu name (e.g., `link "Tech Radar"`).

```bash
# Navigate to a sidebar item
playwright-cli click "getByRole('navigation', { name: 'sidebar nav' }).getByRole('link', { name: 'Catalog' })"
```

## Catalog Page

After navigating to the catalog, the page shows filters and a table of entities.

### Filters

| Filter | Element type | Locator |
|---|---|---|
| Kind | button (shows current value) | `button "Component"` (or current kind) |
| Type | button | `button "all"` (or current type) |
| Owner | combobox + textbox | `textbox "Owner"` |
| Lifecycle | combobox + textbox | `textbox "Lifecycle"` |
| Tags | combobox + textbox | `textbox "Tags"` |

To filter by Kind, click the Kind button and select from the dropdown:

```bash
playwright-cli click "getByRole('button', { name: 'Component' })"
playwright-cli snapshot   # find the desired kind option
playwright-cli click "<ref>"  # click the desired kind
```

### Search the Catalog

```bash
playwright-cli fill "getByRole('textbox', { name: 'Search' })" "my-entity"
```

### Catalog Table

The entity table has columns: Name, System, Owner, Type, Lifecycle, Description, Tags, Actions.

Entity names in the table are links. Their URL pattern is: `/catalog/{namespace}/{kind}/{name}`

```bash
# Click an entity by name
playwright-cli click "getByRole('link', { name: 'artist-lookup' })"
```

### Personal vs All

The catalog has a menu toggle between "Personal" (Owned / Starred) and "RHDH" (All):

```bash
# Switch to "All" entities
playwright-cli click "getByRole('menuitem', { name: /All/ })"
```

## Entity Page

An entity page has:
1. **Header** — shows kind, type, entity name, and metadata (Owner, Lifecycle)
2. **Tabs** — `tablist "Tabs"` containing `tab` elements
3. **Content area** — `article` below the tabs

### Verify an Entity Exists

```bash
playwright-cli open "<RHDH_URL>/catalog/default/component/<entity-name>" --browser chromium
playwright-cli snapshot --depth 3
# Confirm: heading with entity name is present
# The page title format: "<entity-name> | <tab> | <site-title>"
```

Or search through the catalog:

```bash
playwright-cli open "<RHDH_URL>/catalog" --browser chromium
playwright-cli fill "getByRole('textbox', { name: 'Search' })" "<entity-name>"
# Check the table for a matching row
playwright-cli snapshot
```

### Read Entity Metadata

From the entity page snapshot, find:
- **Kind + Type**: `paragraph` above the heading (e.g., "component — service")
- **Owner**: under a "Owner" label, a link to the owning group
- **Lifecycle**: under a "Lifecycle" label (e.g., "experimental", "production")
- **System**: in the About card under "System" heading

### Verify a Tab Exists

```bash
playwright-cli snapshot
# Look for: tablist "Tabs" containing tab elements
# Example output:
#   tablist "Tabs":
#     tab "Overview" [selected]
#     tab "Docs"
#     tab "APIs"
#     tab "Todo"
```

Check that the expected tab name appears in the tablist. Tabs are `tab` role elements inside `tablist "Tabs"`.

```bash
# Click a specific tab
playwright-cli click "getByRole('tab', { name: 'Docs' })"
```

### About Card

The entity Overview tab contains an "About" card (`heading "About"`) with:
- Description, Owner, System, Tags, Kind, Type, Lifecycle
- Links: "View Source", "View TechDocs"

## Common Verification Patterns

### Check that a catalog entity exists

```bash
playwright-cli open "<URL>" --browser chromium
# Handle login if needed (see Authentication section)
playwright-cli goto "<URL>/catalog/default/component/<name>"
playwright-cli snapshot --depth 4
# SUCCESS: heading with entity name is visible
# FAILURE: page shows "Entity not found" or similar error
```

### Entity should have a specific tab

```bash
playwright-cli goto "<URL>/catalog/default/component/<name>"
playwright-cli snapshot --depth 4
# Find: tablist "Tabs" → check for tab "<expected-tab>"
```

### Navigate sidebar and verify page loaded

```bash
playwright-cli click "getByRole('navigation', { name: 'sidebar nav' }).getByRole('link', { name: '<Page>' })"
playwright-cli snapshot --depth 3
# Confirm heading or page content matches expected page
```

### Screenshot for evidence

```bash
playwright-cli screenshot --filename rhdh-evidence.png
# Saved to .playwright-cli/rhdh-evidence.png
```

## URL Patterns

| Resource | URL pattern |
|---|---|
| Catalog list | `/catalog` |
| Entity by kind | `/catalog/{namespace}/{kind}/{name}` |
| API docs | `/api-docs` |
| TechDocs | `/docs` |
| Create (templates) | `/create` |
| Settings | `/settings` |

Default namespace is `default`. Common kinds: `component`, `system`, `group`, `user`, `api`, `resource`, `template`, `domain`, `location`.

## Important

- **Always** use `playwright-cli`, never the Playwright MCP tools.
- **Always** pass `--browser chromium` to `playwright-cli open`.
- The URL is provided by the user or derived from context — never hardcode it.
- Logs and screenshots are automatically saved in `.playwright-cli/`.
- After each `playwright-cli` command, a snapshot is returned — use the ref IDs from it for subsequent interactions.
- Use `playwright-cli snapshot` to refresh the current page state at any time.

## Completion

Complete when the requested pages or entities have been checked, the report
names any visible alerts, warnings, errors, or missing tabs, and requested
screenshots are linked. Close the browser session after collecting the evidence.
