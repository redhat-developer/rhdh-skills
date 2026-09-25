# RHDH Mount Point → NFS Blueprint Mapping

RHDH's legacy dynamic plugin system used mount points in `app-config.dynamic.yaml` to place components. In NFS, these are replaced by extension blueprints. This reference maps each mount point to its NFS equivalent.

## Quick reference

| Legacy mount point | NFS Blueprint | Package |
|---|---|---|
| `dynamicRoutes` (path + importName) | `PageBlueprint` | `@backstage/frontend-plugin-api` |
| `menuItem` in dynamicRoutes | Auto-discovered from `PageBlueprint` title/icon | — |
| `entity.page.*/cards` | `EntityContentBlueprint` | `@backstage/plugin-catalog-react/alpha` |
| `home.page/cards`, `home.page/widgets` | `HomePageWidgetBlueprint` | `@backstage/plugin-home-react/alpha` |
| `application/listener` | `AppRootElementBlueprint` | `@backstage/frontend-plugin-api` |
| `application/provider` | `AppRootWrapperBlueprint` | `@backstage/plugin-app-react` |
| `application/internal/drawer-content` | `AppDrawerContentBlueprint` | `@red-hat-developer-hub/backstage-plugin-app-react/alpha` |
| `application/internal/drawer-state` | Init logic in `AppRootElementBlueprint` | `@backstage/frontend-plugin-api` |
| `global.header/*` | `GlobalHeaderMenuItemBlueprint` | `@red-hat-developer-hub/backstage-plugin-global-header/alpha` |
| `header/component`, `header/*` | `GlobalHeaderMenuItemBlueprint` | `@red-hat-developer-hub/backstage-plugin-global-header/alpha` |
| `appIcons` | `IconBundleBlueprint` (or `icon` param on `createFrontendPlugin` for single icons) | `@backstage/plugin-app-react` |
| `entity.context.menu` | `EntityContextMenuItemBlueprint` | `@backstage/plugin-catalog-react/alpha` |
| `search.page.results` | `SearchResultListItemBlueprint` | `@backstage/plugin-search-react/alpha` |
| `search.page.filters` | `SearchFilterBlueprint` | `@backstage/plugin-search-react/alpha` |
| `search.page.types` | `SearchFilterResultTypeBlueprint` | `@backstage/plugin-search-react/alpha` |
| `application/header` | `AppRootElementBlueprint` | `@backstage/frontend-plugin-api` |

## Dynamic routes → PageBlueprint

**Before (mount point):**

```yaml
dynamicRoutes:
  - path: /my-plugin
    importName: MyPluginPage
    menuItem:
      icon: myIcon
      text: My Plugin
```

**After (NFS):**

```tsx
const myPage = PageBlueprint.make({
  params: {
    path: '/my-plugin',
    title: 'My Plugin',
    icon: <RiToolsLine />,
    routeRef: rootRouteRef,
    loader: () => import('./components/MyPage').then(m => <m.NfsMyPage />),
  },
});
```

The `menuItem` config is no longer needed — nav items are auto-discovered from pages with `title` + `icon` + `routeRef`.

## Entity page mount points → EntityContentBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: entity.page.workflows/cards
    importName: OrchestratorCatalogTab
    config:
      if:
        allOf:
          - isKind: component
```

**After (NFS):**

```tsx
const entityContent = EntityContentBlueprint.make({
  name: 'workflows',
  params: {
    path: '/workflows',
    title: 'Workflows',
    filter: 'kind:component',
    loader: () => import('./components/OrchestratorCatalogTab').then(m => <m.OrchestratorCatalogTab />),
  },
});
```

Register in the plugin's `extensions` array.

## Homepage widgets → HomePageWidgetBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: home.page/cards
    importName: OnboardingSection
    config:
      layouts:
        xl: { w: 12, h: 6 }
```

**After (NFS):**

```tsx
import { HomePageWidgetBlueprint } from '@backstage/plugin-home-react/alpha';

const myWidget = HomePageWidgetBlueprint.make({
  name: 'my-widget',
  params: {
    name: 'My Widget',
    layout: {
      width: { minColumns: 4, maxColumns: 12, defaultColumns: 12 },
      height: { minRows: 2, maxRows: 12, defaultRows: 4 },
    },
    components: () => import('./components/MyWidget').then(m => ({
      Content: m.MyWidget,
    })),
  },
});
```

Note: `HomePageWidgetBlueprint` uses `components` (returning `{ Content }`) instead of `loader`.

## Drawer content → AppDrawerContentBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: application/internal/drawer-content
    importName: MyDrawerContent
```

**After (NFS):**

```tsx
import { AppDrawerContentBlueprint } from '@red-hat-developer-hub/backstage-plugin-app-react/alpha';

const myDrawer = AppDrawerContentBlueprint.make({
  name: 'my-drawer',
  params: {
    id: MY_DRAWER_ID,
    element: <MyDrawerContent />,
    resizable: true,
    defaultWidth: 400,
  },
});
```

Register in the plugin's `extensions` array.

Init logic that should persist across drawer toggles (e.g. auto-open triggers, event listeners) goes in a separate `AppRootElementBlueprint` registered via `createFrontendModule({ pluginId: 'app' })`.

## App-level listeners → AppRootElementBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: application/listener
    importName: MyFAB
```

**After (NFS):**

```tsx
import { AppRootElementBlueprint } from '@backstage/frontend-plugin-api';

const myElement = AppRootElementBlueprint.make({
  name: 'my-fab',
  params: {
    element: <MyFAB />,
  },
});
```

## App-level providers → AppRootWrapperBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: application/provider
    importName: MyProvider
```

**After (NFS):**

```tsx
import { AppRootWrapperBlueprint } from '@backstage/plugin-app-react';

const myWrapper = AppRootWrapperBlueprint.make({
  name: 'my-provider',
  params: {
    component: ({ children }) => (
      <MyProvider>{children}</MyProvider>
    ),
  },
});
```

Register via `createFrontendModule({ pluginId: 'app' })`.

## Global header items → GlobalHeaderMenuItemBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: global.header/help
    importName: MyHelpMenuItem
```

**After (NFS):**

```tsx
import { GlobalHeaderMenuItemBlueprint } from '@red-hat-developer-hub/backstage-plugin-global-header/alpha';

const myMenuItem = GlobalHeaderMenuItemBlueprint.make({
  name: 'my-help-item',
  params: {
    target: 'help',
    component: MyHelpMenuItem,
    priority: 50,
  },
});
```

The `target` param maps to the header section: `help`, `profile`, `create`, etc. Use `priority` to control ordering.

## Entity context menu → EntityContextMenuItemBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: entity.context.menu
    importName: SimpleDialog
    config:
      props:
        title: Open Dialog
        icon: dialogIcon
```

**After (NFS):**

```tsx
import { EntityContextMenuItemBlueprint } from '@backstage/plugin-catalog-react/alpha';

const myMenuItem = EntityContextMenuItemBlueprint.make({
  name: 'my-action',
  params: {
    icon: <DialogIcon />,
    useProps() {
      return {
        title: 'Open Dialog',
        onClick: () => { /* handle action */ },
      };
    },
  },
});
```

The `useProps` hook can call other React hooks and returns `{ title, onClick }` or `{ title, href }` plus optional `disabled`.

## Search page results → SearchResultListItemBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: search.page.results
    importName: MySearchResultItem
```

**After (NFS):**

```tsx
import { SearchResultListItemBlueprint } from '@backstage/plugin-search-react/alpha';

const mySearchItem = SearchResultListItemBlueprint.make({
  params: {
    predicate: result => result.type === 'my-type',
    component: async () => {
      const { MyResultItem } = await import('./MyResultItem');
      return props => <MyResultItem {...props} />;
    },
  },
});
```

## Search page filters → SearchFilterBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: search.page.filters
    importName: MySearchFilter
```

**After (NFS):**

```tsx
import { SearchFilterBlueprint } from '@backstage/plugin-search-react/alpha';

const myFilter = SearchFilterBlueprint.make({
  params: {
    loader: async () => {
      const { MySearchFilter } = await import('./MySearchFilter');
      return props => <MySearchFilter {...props} />;
    },
  },
});
```

## Search page types → SearchFilterResultTypeBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: search.page.types
    importName: MySearchType
```

**After (NFS):**

```tsx
import { SearchFilterResultTypeBlueprint } from '@backstage/plugin-search-react/alpha';

const myType = SearchFilterResultTypeBlueprint.make({
  params: {
    value: 'my-type',
    name: 'My Type',
    icon: <MyTypeIcon />,
  },
});
```

## Application header → AppRootElementBlueprint

**Before (mount point):**

```yaml
mountPoints:
  - mountPoint: application/header
    importName: GlobalHeader
    config:
      position: above-main-content
```

**After (NFS):**

```tsx
import { AppRootElementBlueprint } from '@backstage/frontend-plugin-api';

const myHeader = AppRootElementBlueprint.make({
  name: 'my-header',
  params: {
    loader: async () => {
      const { GlobalHeader } = await import('./GlobalHeader');
      return <GlobalHeader />;
    },
  },
});
```

RHDH's global header plugin is being migrated to extension blueprints in `rhdh-plugins`. The `position: above-main-content` concept is app-layout-specific — verify layout behavior when migrating.

## Real migration examples

| Plugin | Mount points used | NFS blueprints | PR |
|--------|------------------|----------------|-----|
| intelligent-assistant | `application/listener`, `application/internal/drawer-content` | `AppRootWrapperBlueprint` (FAB), `AppDrawerContentBlueprint`, `PageBlueprint` | [#2721](https://github.com/redhat-developer/rhdh-plugins/pull/2721) |
| quickstart | `application/provider`, `application/internal/drawer-state`, `global.header/help` | `AppDrawerContentBlueprint`, `GlobalHeaderMenuItemBlueprint`, `AppRootElementBlueprint` | [#2842](https://github.com/redhat-developer/rhdh-plugins/pull/2842) |
| homepage | `home.page/cards` | `HomePageWidgetBlueprint` | [#2423](https://github.com/redhat-developer/rhdh-plugins/pull/2423) |
| orchestrator | `entity.page.workflows/cards` | `EntityContentBlueprint` | [#2526](https://github.com/redhat-developer/rhdh-plugins/pull/2526) |
