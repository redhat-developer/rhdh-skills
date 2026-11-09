# Interpreting RHDH KB theme analysis

## Authoring versus demand

The report answers two different questions and never mixes them.

- **Authoring** is the `recent` and `comparison` views. They filter on
  `createdDate`, so they measure how many articles support published in a
  window, not how much pain customers reported.
- **Demand** is the `demand` view. It ignores `createdDate` and weights the whole
  corpus by `caseCount_365`.

Read the authoring view for publishing cadence and taxonomy coverage. Read the
demand view for what customers are hitting. A quarterly answer is an authoring
answer; the demand view is always annual.

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

## Case-weight arithmetic

Three case numbers appear per theme and per demand article, and they are not
interchangeable:

- `casesRaw` — the plain sum of `caseCount_365`;
- `casesAttributed` — the sum after each article is divided by the number of
  products it is tagged to. Use this one;
- `casesDedicated` — the sum over single-product articles only.

A generic article tagged to nine products used to read as nine times the demand
of a product-specific one. Attribution removes that distortion without throwing
the shared article away.

`demand.concentration` names the largest article and its share of raw and
attributed weight. When `warned` is true, at least a quarter of the corpus case
weight is one article: say so before quoting any total, and never present that
article's reach as demand for every theme it touches.

Do not classify growth by eye. `movement.themes` already carries `class`,
`ratio`, and `deltaShare` for every theme, computed against the baseline window:

- `new` — no baseline articles, at least three recent ones;
- `growing` — recent share at least 1.25× the baseline share;
- `declining` — recent share at most 0.8× the baseline share;
- `stable` — anything between;
- `insufficient` — fewer than five articles on either side, or no baseline.

Classes read **share**, not absolute rate. `movement.corpusRateRatio` states how
much the whole corpus sped up or slowed down between the windows; when it is far
from 1.0, every theme's absolute rate moves with it, and a rate-based reading
would report one corpus-wide shift as a trend in eight themes. Each row still
carries `ratio` so the absolute movement is visible, but the class answers the
narrower question: did this theme gain or lose ground relative to everything
else published in the same window.

The baseline is *not* the comparison window. It is the comparison window minus
the recent window, so a theme is never compared against a period that contains
itself. `movement.baseline.window` carries the exact dates; quote them.

Report an `insufficient` theme as unclassified. Never print a percentage or a
ratio for one, and never upgrade a 2-against-0 result into "emerging".

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
- `caseCount_365` is a fixed trailing-year count. Nothing shorter than a year
  can be stated about case volume.
- Attributed cases are an estimate that assumes an article's cases split evenly
  across its tagged products.
- Emergent terms are word frequencies, not themes. A term is `new` only with
  three recent articles and no baseline use, and `rising` only with three recent
  articles and twice the baseline rate. Those are floors, not evidence; raise a
  term only when it maps onto an article set you can cite.
