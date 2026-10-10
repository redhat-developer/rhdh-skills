# Dev App Setup

Two ways to test a plugin locally:

1. **Plugin dev mode** (`dev/index.tsx`) — lightweight, plugin-scoped, no backend.
   Use for component development and quick iteration.
2. **Full Backstage app** (`packages/app` + `packages/backend`) — complete
   environment with catalog, auth, and backend services. Use when the plugin
   needs real data, API calls, or integration testing with other plugins.

---

## Plugin Dev Mode

Each plugin has a `dev/` directory with a standalone dev harness. Start it with
`yarn start` from the plugin directory.

```tsx
// plugins/my-plugin/dev/index.tsx
import { createDevApp } from '@backstage/dev-utils';
import { getAllThemes } from '@red-hat-developer-hub/backstage-plugin-theme';
import { myPlugin, MyPage } from '../src';

createDevApp()
  .registerPlugin(myPlugin)
  .addPage({
    element: <MyPage />,
    title: 'My Plugin',
    path: '/my-plugin',
  })
  .addThemes(getAllThemes())
  .render();
```

- No backend needed — mock data or stub APIs inline
- Hot reload on source changes
- Good for: UI development, component styling, layout iteration
- Limited: no real catalog entities, no auth, no backend API calls

For NFS plugins, use the NFS dev app pattern:

```tsx
// plugins/my-plugin/dev/index.tsx
import { createApp } from '@backstage/frontend-defaults';
import myPlugin from '../src';

const app = createApp({
  features: [myPlugin],
  configLoader: async () => ({
    config: [{ data: { app: { packages: 'all' } } }],
  }),
});

export default app.createRoot();
```

---

## Full Backstage App

A complete Backstage instance in `packages/app` + `packages/backend`. Use when
the plugin needs real backend services, catalog data, or integration with other
plugins.

### createApp (NFS)

```tsx
// packages/app/src/App.tsx
import { createApp } from '@backstage/frontend-defaults';

const app = createApp({
  features: [
    // Explicitly imported plugins go here (optional with auto-discovery)
  ],
});

export default app.createRoot();
```

## Auto-Discovery with app.packages

Enable automatic plugin discovery in `app-config.yaml`:

```yaml
app:
  packages: all
```

With this set, any plugin added as a `package.json` dependency that exports an
NFS plugin is automatically detected and loaded — no manual imports needed.

**Caveat: translation modules are NOT auto-discovered.** Modules with
`pluginId: 'app'` (like translation modules) must be explicitly imported or
re-exported as a separate entry point. See "Translation Module Entry Points"
below.

## Sidebar Navigation

NFS uses `NavContentBlueprint` for sidebar layout — not manual `SidebarItem` lists.

```tsx
import { NavContentBlueprint } from '@backstage/frontend-plugin-api';

const sidebarContent = NavContentBlueprint.make({
  name: 'main-nav',
  params: {
    content: nav => (
      <>
        {nav.take('page:my-plugin')}
        {nav.take('page:catalog')}
        {nav.rest()}
      </>
    ),
  },
});
```

- `nav.take('page:xxx')` — renders a specific page's nav item in this position
- `nav.rest()` — renders all remaining nav items not explicitly placed
- Pages appear in the sidebar automatically when they have `title` and `icon`
  set on `PageBlueprint` or `createFrontendPlugin`

**SidebarItem icon prop:** Expects a component reference, not a render function.
Use `icon: RiHomeLine` (the component), not `icon: () => <RiHomeLine />`.

## Sign-In Page

For local development with guest auth:

```tsx
import { SignInPageBlueprint } from '@backstage/frontend-plugin-api';

const signInPage = SignInPageBlueprint.make({
  params: {
    provider: {
      id: 'guest',
      title: 'Guest',
      message: 'Sign in as guest',
    },
  },
});
```

Add to the app's features.

## Default Route

Configure which page loads at `/` in `app-config.yaml`:

```yaml
app:
  routes:
    root: /my-plugin
```

Or redirect from root:

```yaml
app:
  routes:
    bindings:
      - path: /
        redirect: /my-plugin
```

## Catalog Locations (file: paths)

```yaml
catalog:
  locations:
    - type: file
      target: ../../workspaces/my-workspace/catalog-info.yaml
```

**Critical:** `file:` paths resolve relative to the backend package CWD
(`packages/backend/`), NOT the workspace root or the config file location.
A path like `../../workspaces/boost/catalog-info.yaml` resolves from
`packages/backend/`, not from the repo root.

This catches people when entities don't appear in the catalog — the path is
correct relative to the repo root but wrong relative to where the backend runs.

## Translation Module Entry Points

Translation modules (`createFrontendModule` with `pluginId: 'app'`) are NOT
auto-discovered by `app.packages: all`. They need their own entry point:

```tsx
// src/translations.ts
export { translationsModule as default } from './plugin';
```

```json
// package.json exports
{
  "exports": {
    ".": "./src/index.ts",
    "./translations": "./src/translations.ts",
    "./package.json": "./package.json"
  }
}
```

Then either import explicitly in the app's features or ensure the translations
entry point is listed as a discoverable export.

## Reference Workspaces

Real dev app examples in rhdh-plugins:

- `workspaces/orchestrator/packages/app/` — full NFS app with sidebar, auth, catalog
- `workspaces/homepage/packages/app/` — simpler NFS app setup
- `workspaces/intelligent-assistant/packages/app/` — NFS with AI-specific extensions
