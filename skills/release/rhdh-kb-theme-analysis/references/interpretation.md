# Interpreting RHDH KB theme analysis

## Time windows

The default recent window is the trailing 90 days. The default comparison
window is the trailing 365 days. Both end on `--as-of` and are inclusive.

When the recent window is nested inside the comparison window, compare:

- article counts,
- each theme’s share of its window,
- each theme’s per-day rate,

not raw counts alone. A theme can look large in the annual window simply
because the window is four times longer.

For formal calendar periods, pass explicit start and end dates rather than
changing the default rolling behavior. If the windows are not nested, say so
and compare per-day rates and window shares rather than raw counts.

## Theme signals

The script emits heuristic, non-exclusive keyword clusters:

- `upgrade-plugin-reliability`
- `authentication-identity`
- `operator-openshift-deployment`
- `rbac-permissions`
- `configuration-ui`
- `observability-diagnostics`
- `support-version-clarity`
- `catalog-database-scale`

Use them as a starting point, not as official Red Hat categories. An article
can match more than one theme, so theme counts do not sum to the article total.

Those eight clusters are the built-in taxonomy. A run can instead use a custom
taxonomy (`--themes PATH`) or none at all (`--themes none`); `taxonomy.md` covers
both. When the run did not use the built-in set, say which taxonomy produced the
table, and never compare theme counts against a run that used a different one.

Prefer the objective `category`, `tag`, and `component` counts when they
conflict with a heuristic theme signal.

## Product interpretation

For each strong theme, report:

- what customers appear to be hitting;
- whether it is configuration, troubleshooting, upgrade, or support-boundary
  friction;
- the likely documentation impact;
- the likely product or roadmap impact;
- the confidence level.

Look for themes that are:

- new in the recent window,
- growing relative to the annual rate,
- persistent across both windows,
- high-touch by `caseCount_365`,
- concentrated around a release or plugin family.

## Product and documentation recommendations

End the final answer with a “Product and documentation improvement areas”
section. Connect the strongest recent themes to concrete candidate work, and
separate product improvements from documentation improvements. Frame them as
areas the team should consider funding, not as automatically committed roadmap
items.

Candidate starting points, to be adjusted against the actual article evidence.
They are keyed to the built-in clusters; with a custom taxonomy, map your
clusters onto the closest problem area rather than reusing these names:

- `upgrade-plugin-reliability`: upgrade preflight, plugin compatibility matrix,
  plugin doctor, and release-critical upgrade documentation.
- `configuration-ui`: configuration linting, guided setup, stable customization
  APIs, and task-based customization documentation.
- `observability-diagnostics`: actionable error codes, built-in diagnostics, a
  support bundle, and symptom-based troubleshooting documentation.
- `operator-openshift-deployment`: install preflight, deployment profiles,
  clearer Operator status, and an enterprise deployment guide.
- `rbac-permissions`: policy simulation, permission explainability, safer
  defaults, scale work, and one RBAC mental-model guide.
- `authentication-identity`: guided provider setup, test-connection validation,
  token lifecycle handling, and provider-specific recipes.
- `catalog-database-scale`: catalog/database status, ingestion diagnostics,
  performance work, and scale guidance.
- `support-version-clarity`: generated compatibility and lifecycle views plus an
  authoritative support matrix.

## Article citations

When naming an article in the final answer, link its title to the `url` from the
script output. Do not cite a KB article by title alone.

## Caveats

State these limitations in the final answer:

- Article count is not case volume.
- `caseCount` and `caseCount_365` are article-level support-case signals, not
  unique case counts. Theme totals sum these values across matching articles and
  can be dominated by broad, multi-product articles.
- Public KB metadata does not confirm article authorship.
- The API may include articles tagged to multiple products.
- Theme clusters are heuristic.
- A spike can reflect release activity, documentation gaps, support process
  changes, or product regressions; the KB alone does not prove causation.
