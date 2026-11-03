# Dependabot dismissal policy

Hard rules. Scripts enforce classification; humans/agents must still gate writes
through `/mutation-gate`.

## A. Package-level (all matching alerts for a workspace)

Safe when aggregate classification is **exactly `RUNNER`**, **exactly
`PLUGIN_DEV`**, or **exactly `WORKSPACE_DEV`**. Then you may dismiss open alerts
for that package under the workspace manifest(s) (interactive `--close`).

Mixed labels (e.g. `RUNNER+WORKSPACE_DEV`, anything with `PLUGIN_PROD`) are
**not** package-level dismissable.

Exact `PLUGIN_DEV` / `WORKSPACE_DEV` are not product/runtime vulnerabilities for
published plugins, but they can still appear in SBOMs. Prefer bumping those
dependencies when feasible; dismissal alone does not clean the SBOM.

## B. Alert-level (mixed impact — prod fixed, runner alerts remain)

When aggregate classification **includes `PLUGIN_PROD`**:

1. Still fix / bump the published plugin production path; do **not** dismiss
   `PLUGIN_PROD` alerts.
2. May dismiss only alerts whose `manifest_path` is a **RUNNER** package.json
   when prod is patched / no open PLUGIN_PROD alerts remain.
3. Pass that **exact runner manifest** to `close-dependabot-alerts.js` (not the
   workspace `yarn.lock` shortcut).
4. Never dismiss alerts for `plugins/…` when doing alert-level dismiss of a
   mixed package.

## C. Patched everywhere except runner

Use `check-dependabot-patch-status.js`. Verdict `PATCHED_EXCEPT_RUNNER` with
`safeToDismissRunnerAlerts` → dismiss runner `package.json` alerts only.

## Shared rules

1. Never dismiss `PLUGIN_PROD` or `UNKNOWN` at package level.
2. Do not dismiss unless the user (or an approved mutation-gate plan) asks to
   close alerts. Classify and recommend first.
3. Interactive confirmation is required for humans: run `--close` **without**
   `--yes`. Pass `--yes` only after `/mutation-gate` approval of that exact
   dismiss set (fullsend / non-interactive).
4. Default reason: `not_used`. Comment should cite classification, e.g.
   `runner-only in <workspace>; classification=RUNNER`.
