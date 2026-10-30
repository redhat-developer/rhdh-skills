# Theme taxonomies

A taxonomy is the list of clusters the script counts articles into. Each cluster
is a name plus a case-insensitive keyword pattern, matched against the article
title, abstract, category, and component. Matching is non-exclusive, so one
article can land in several clusters and cluster counts do not sum to the
article total.

## The built-in taxonomy

`--themes` omitted uses the eight built-in clusters:

- `upgrade-plugin-reliability`
- `authentication-identity`
- `operator-openshift-deployment`
- `rbac-permissions`
- `configuration-ui`
- `observability-diagnostics`
- `support-version-clarity`
- `catalog-database-scale`

Keep it when the question is a general "what are customers hitting with RHDH"
scan. It is shaped by install, upgrade, and configuration support, which is where
most RHDH articles sit.

## No taxonomy

`--themes none` skips clustering entirely: the report carries `themes: null` and
the article list becomes the raw categorisation input.

Use it when the user wants the data and will group it themselves, or when the
question does not fit any keyword scheme. Pair it with `--format json`, because
the Markdown report only lists the top 15 recent articles while JSON carries
every article.

## A custom taxonomy

`--themes PATH` loads a JSON array:

```json
[
  { "theme": "techdocs-build", "pattern": "\\btechdocs?\\b|techdocs builder" },
  { "theme": "scaffolder-templates", "pattern": "\\bscaffolder\\b|software template" }
]
```

Rules the loader enforces:

- the file is a non-empty JSON array of objects with a non-empty `theme` and `pattern`;
- theme names are unique;
- every `pattern` compiles as a regular expression.

An unreadable file, a bad pattern, or a duplicate theme stops the run with a
message naming the entry, rather than silently producing an empty cluster.

## Proposing one

Propose the taxonomy from the article titles first, then run the script once to
apply it to both windows. Do not count clusters by hand per window — that is how
two windows end up measured differently.

Guidance for the proposal:

- Five to twelve clusters. Fewer loses signal; more turns the table into a title
  index.
- Name clusters after the customer problem, not the component that failed.
- Anchor patterns on domain nouns (`techdocs`, `scaffolder`, `rbac`), not on
  whole article titles. A pattern copied from one title fits one article and
  measures nothing.
- Keep matching non-exclusive and leave out an "other" cluster; the article
  count already tells you what did not match.

## Checking the distribution

Apply the taxonomy once and read the numbers before trusting it:

- No cluster above roughly 40% of the window. A cluster that matches more than
  a third of the articles is usually several themes wearing one name, and its
  share tells you nothing.
- No empty cluster. A pattern that matches nothing in this corpus is either
  miscast or already covered by a better cluster.
- Unmatched is small. The report prints `unmatched by taxonomy` per window; a
  large number means the taxonomy misses a real theme.
- Case totals carry a concentration warning. When one article supplies more
  than half of a cluster's `caseCount365`, the report says so; treat that total
  as one article, not as demand for the whole theme.

The matcher reads the abstract as well as the title. A stem that only ever
matches in long prose — `support`, `many`, `large`, bare `logs` — will pull in
articles that merely mention the word. When a cluster's matches are mostly
abstract-only, tighten the pattern rather than adding another cluster.

## Comparability

The recent and comparison windows must always use the same taxonomy. Theme
counts, shares, and per-day rates are only comparable across runs that used the
same one, so state which taxonomy produced a table whenever it is not the
built-in set. A run with `--themes none` has no theme table and must not be
compared against a clustered run.

## Writing the file

A taxonomy file is a file on the user's disk. Say where it will be written and
get agreement before creating it, then reuse that path for follow-up runs so the
windows stay comparable.
