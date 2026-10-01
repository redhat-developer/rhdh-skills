# Package metadata fields

Load this file when a column is empty, support is Unknown, or the user asks where a value comes from.

## Overlay repo

Data is read from [rhdh-plugin-export-overlays](https://github.com/redhat-developer/rhdh-plugin-export-overlays) at the mapped git ref for the requested RHDH version. Prefer a local checkout:

- `--repo PATH` or `RHDH_OVERLAY_REPO` (see `../SKILL.md` → **Overlay repo**)
- Without a local path: temp sparse clone from GitHub

The script never `git checkout`s your tree; it uses `git cat-file` at the ref (or `--workdir` for on-disk files).

## Export txt lists (`--compare-txt`)

[`rhdh-community-packages.txt`](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/rhdh-community-packages.txt) and [`rhdh-supported-packages.txt`](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/rhdh-supported-packages.txt) are workspace-path allowlists for optional vs supported exports. Run `list_packages.py` with `--compare-txt` to check alignment with Package metadata support levels on a release ref.

Source files: `workspaces/<workspace>/metadata/<file>.yaml` with `kind: Package`.

| Output column | YAML path | Notes |
|---------------|-----------|--------|
| Title | `metadata.title` | Fallback: `metadata.name`, then `spec.packageName` |
| Support | `spec.support` | Scalar (`generally-available`) **or** nested `spec.support.level` |
| Package | `spec.packageName` | npm name, including scope |
| Source | `metadata.links` item whose title is `Source Code` | Else `metadata.annotations["backstage.io/source-location"]` with a leading `url:` stripped |
| Backstage | `spec.backstage.supportedVersions` | Catalog compatibility, not `source.json` |
| Role | `spec.backstage.role` | e.g. `frontend-plugin`, `backend-plugin`, `backend-plugin-module` |
| Version | `spec.version` | Package version |
| Author | `spec.author` | |
| Lifecycle | `spec.lifecycle` | e.g. `active` |
| Core OOTB | [`default.packages.yaml`](https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/default.packages.yaml) | Match `spec.packageName` to `packages.enabled` / `packages.disabled`. **enabled OOTB** / **disabled OOTB** / `—` (not core). |
| Workspace heading | path `workspaces/<name>/metadata/` | Not `spec.partOf` |

## Diff (`--diff FROM TO`)

Match by `spec.packageName` (fallback `workspace/filename`). Compared fields: `spec.support` (normalized, including nested `.level` and legacy `production`) and `spec.lifecycle` (case-insensitive). New identities are **Newly added**; identities only in FROM are **Removed**.

## Support levels

| YAML value | Display | Filter aliases |
|------------|---------|----------------|
| `generally-available` | Generally Available | `ga`, `GA`, `generally available`, `production` (legacy 1.9) |
| `tech-preview` | Tech Preview | `tp`, `tech preview` |
| `dev-preview` | Developer Preview | `dp`, `dev preview`, `developer preview` |
| `community` | Community | `community` |
| missing / anything else | Unknown | `unknown` |

Display order (decreasing): Generally Available, Tech Preview, Developer Preview, Community, Unknown.

Examples on `main`:

- [adoption-insights/metadata](https://github.com/redhat-developer/rhdh-plugin-export-overlays/tree/main/workspaces/adoption-insights/metadata)
- [pingidentity/metadata](https://github.com/redhat-developer/rhdh-plugin-export-overlays/tree/main/workspaces/pingidentity/metadata)
- [scorecard/metadata](https://github.com/redhat-developer/rhdh-plugin-export-overlays/tree/main/workspaces/scorecard/metadata)
