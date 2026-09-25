# Reference Migration PRs

Real-world NFS migration PRs from the `rhdh-plugins` repository. Use these as patterns when migrating similar plugins.

| Plugin | PR | What to learn | Complexity |
|--------|-----|---------------|------------|
| adoption-insights | [#2309](https://github.com/redhat-developer/rhdh-plugins/pull/2309) | Simple page plugin: Page + Nav + API blueprints | Low — good starting point |
| bulk-import | [#2247](https://github.com/redhat-developer/rhdh-plugins/pull/2247) | Page + Nav + permission-based access patterns | Low-Medium — adds permission handling |
| scorecard | [#2487](https://github.com/redhat-developer/rhdh-plugins/pull/2487) | EntityContent + HomePageWidget blueprints | Medium — multi-extension-type migration |
| orchestrator | [#2526](https://github.com/redhat-developer/rhdh-plugins/pull/2526) | EntityContent + multiple routes/pages | Medium — complex routing with entity integration |
| intelligent-assistant | [#2721](https://github.com/redhat-developer/rhdh-plugins/pull/2721) | Drawer + FAB using RHDH-specific blueprints | Medium — RHDH-specific extensions (AppDrawerContent + AppRootElement) |
| extensions | [#2527](https://github.com/redhat-developer/rhdh-plugins/pull/2527) | `compatWrapper` usage for legacy components | Medium — bridging legacy and NFS |
| homepage | [#2423](https://github.com/redhat-developer/rhdh-plugins/pull/2423) | HomePageWidgets + compatWrapper | Medium — homepage integration with legacy compat |
| quickstart | [#2842](https://github.com/redhat-developer/rhdh-plugins/pull/2842) | Drawer + GlobalHeaderMenuItem | Medium-High — RHDH drawer + header menu integration |

## How to use these

1. Find the PR closest to your plugin's extension types
2. Read the PR's file changes to see the migration pattern
3. Pay attention to:
   - How extensions are split between plugin and modules
   - How `package.json` exports are configured
   - How the dev app is set up
   - How legacy code is handled (kept vs removed)
