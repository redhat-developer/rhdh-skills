# Package impact classifications

Labels come from `scripts/classify-cve-source.js` (`yarn why -R` against a
workspace `yarn.lock`). Combined labels join with `+` (e.g. `PLUGIN_PROD+RUNNER`).

| Label | Meaning | Customer impact |
| --- | --- | --- |
| `PLUGIN_PROD` | Reached via a published plugin's `dependencies` or `peerDependencies` (incl. direct deps of those peers) | **high** — fix/bump; never dismiss prod alerts |
| `PLUGIN_DEV` | Reached via plugin `devDependencies` / local harness / tests | local-dev — dismissable when exact; prefer bump for SBOM hygiene |
| `RUNNER` | Reached via `packages/app`, `app-legacy`, or `backend` | local-dev — dismissable when exact |
| `WORKSPACE_DEV` | Reached via workspace root `devDependencies` | local-dev — dismissable when exact; prefer bump for SBOM hygiene |
| `UNKNOWN` | Could not map; inspect `yarn why` | unknown — do not dismiss |

## Per-alert manifest hint

Dependabot alerts are per `manifest_path` (+ optional `scope`):

| `manifest_path` | scope | Alert class |
| --- | --- | --- |
| `…/packages/(app\|app-legacy\|backend)/package.json` | any | **RUNNER** — dismissable |
| `…/plugins/…/package.json` | `runtime` | **PLUGIN_PROD** — never dismiss |
| `…/plugins/…/package.json` | `development` | **PLUGIN_DEV** — dismissable when package is exact `PLUGIN_DEV` |
| `…/yarn.lock` (or other) | — | package-level dismiss only if aggregate is exactly `RUNNER`, `PLUGIN_DEV`, or `WORKSPACE_DEV` |

## Patch-status verdicts

From `scripts/check-dependabot-patch-status.js`:

| Verdict | Meaning | Action |
| --- | --- | --- |
| `RUNNER_ONLY` | Classification exactly `RUNNER` | Package-level dismiss OK |
| `PLUGIN_DEV_ONLY` | Classification exactly `PLUGIN_DEV` | Package-level dismiss OK; bump for SBOM when practical |
| `WORKSPACE_DEV_ONLY` | Classification exactly `WORKSPACE_DEV` | Package-level dismiss OK; bump for SBOM when practical |
| `PATCHED_EXCEPT_RUNNER` | No open `PLUGIN_PROD` alerts; runner alerts remain | Dismiss **RUNNER** `package.json` alerts only |
| `PLUGIN_PROD_ALERTS_REMAIN` | Still open alerts on `plugins/…` | Fix prod first |
| `LOCKFILE_ALERTS_ONLY` | Only yarn.lock alerts | Not `PATCHED_EXCEPT_RUNNER`; refresh/bump |
| `PROD_PATCHED_DEV_UNPATCHED` | Prod paths patched; lockfile still has older on dev/runner | Dev/SBOM hygiene unless `prod_resolved` unpatched |
| `UNPATCHED_IN_LOCKFILE_NO_PROD_ALERTS` | Lockfile still vulnerable; no prod alerts | Review before dismiss |
| `FULLY_PATCHED` | Lockfile meets patch level | Usually nothing to dismiss |

`safeToDismissPackageLevel: true` ⇒ package-level dismiss OK.
`safeToDismissRunnerAlerts: true` ⇒ dismiss runner manifests (also true for package-level runner-only).
