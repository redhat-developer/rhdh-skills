# Plugin catalog fields

Load this file when a column is empty, support is Unknown, or the user asks where a value comes from.

## Overlay repo

Data is read from [rhdh-plugin-export-overlays](https://github.com/redhat-developer/rhdh-plugin-export-overlays) at the mapped git ref for the requested RHDH version. Prefer a local checkout:

- `--repo PATH` or `RHDH_OVERLAY_REPO` (see `../SKILL.md` → **Overlay repo**)
- Without a local path: temp sparse clone from GitHub

The script never `git checkout`s your tree; it uses `git cat-file` at the ref (or `--workdir` for on-disk files).

Source files: `catalog-entities/extensions/plugins/<file>.yaml` with `kind: Plugin`.

| Output column | YAML path | Notes |
|---------------|-----------|--------|
| Title | `metadata.title` | Fallback: `metadata.name` |
| Support | `spec.support.level` | Nested object; also accept scalar `spec.support`. Legacy `production` → Generally Available |
| Lifecycle | `spec.lifecycle` | e.g. `active` |
| Core OOTB | [`default.packages.yaml`](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/default.packages.yaml) | Match `spec.packageName` to `packages.enabled` / `packages.disabled`. **enabled OOTB** = core package shipped enabled; **disabled OOTB** = core but needs configuration. Empty → not in the core list. |
| Author | `spec.author` | Empty → `—` |
| Provider | `spec.support.provider` | Nested support object only. Scalar `spec.support` has no provider |
| Publisher | `spec.publisher` | Empty → `—` |
| Plugin YAML | `metadata.annotations["extensions.backstage.io/pre-installed"]` | `true` / `"true"` → **pre-installed**; missing or anything else → **custom**. This is the YAML annotation, not whether the plugin is enabled. |

## Default catalog (`all.yaml`)

[all.yaml](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/catalog-entities/extensions/plugins/all.yaml) is `kind: Location`. Primary grouping uses `spec.targets`:

| Group | Meaning |
|-------|---------|
| **Included in the Catalog** | Filename appears in `all.yaml` `spec.targets` (default-install catalog for that overlay ref) |
| **Packaged, but Not in Catalog** | A Plugin YAML exists under `plugins/` but is not listed in `all.yaml` |

Skip [1-boilerplate.yaml.sample](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/catalog-entities/extensions/plugins/1-boilerplate.yaml.sample). Do not emit a row for `all.yaml`.

## Diff (`--diff FROM TO`)

Match by `metadata.name` (fallback YAML filename). Compared fields: `spec.support.level` (normalized, including scalar `spec.support` and legacy `production`) and `spec.lifecycle` (case-insensitive). New identities are **Newly added**; identities only in FROM are **Removed**. Catalog membership and pre-installed annotation are shown on added/removed rows but are not change categories.

Display order: catalog group first, then support level (decreasing), then title alphabetically.

## Support levels

| YAML value | Display | Filter aliases |
|------------|---------|----------------|
| `generally-available` | Generally Available | `ga`, `GA`, `generally available`, `production` (legacy) |
| `tech-preview` | Tech Preview | `tp`, `tech preview` |
| `dev-preview` | Developer Preview | `dp`, `dev preview`, `developer preview` |
| `community` | Community | `community` |
| missing / anything else | Unknown | `unknown` |
