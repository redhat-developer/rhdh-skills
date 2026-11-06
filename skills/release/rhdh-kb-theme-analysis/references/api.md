# Red Hat KB search API

The Customer Portal KB search page is client-rendered. Do not scrape the HTML.
Use the JSON endpoint behind it:

```text
https://access.redhat.com/hydra/rest/search/platform/kbase
```

## Query shape

The script sends:

- `q=*`
- `fq=-id:Other`
- `fq=documentKind:(Solution Article)`
- `fq={!tag=productFilter}standard_product:"..."`
- `facet=true`
- `facet.mincount=1`
- `enableElevation=true`
- `f.standard_product.facet.limit=-1`
- `redhat_client=kb-search`
- `facet.field=documentKind`
- `facet.field={!ex=productFilter}standard_product`

The Solr local params in `{!ex=...}` and `{!tag=...}` must remain URL-encoded.
`URLSearchParams` handles this correctly.

## Pagination

The API reports `response.numFound` and returns documents in
`response.docs`. The script requests 100 rows per page, uses a 30-second
request timeout, and follows `start` until it has `numFound` results or reaches
the 10,000-result safety cap. If the cap truncates the result, the report
prints an “at least” count rather than presenting the fetched count as the
total.

## Fields the analysis reads

Treat these fields as optional because Red Hat can change the public response.
The script accepts either string or array shapes for `category`, `component`,
`tag`, and `standard_product`:

- `id`, `title`, `view_uri`
- `createdDate` — publication date. The authoring windows filter on its
  `YYYY-MM-DD` prefix.
- `lastModifiedDate` — last editorial change. Drives the refresh-candidate
  signal.
- `kcsState`, with `publication_state` as a fallback — `verified`, `unverified`,
  or `wip`.
- `category`, `component`, `tag`
- `standard_product` — every product the article is tagged to. More than one
  entry means the article is shared, and its case weight is divided by that
  count.
- `issue` — the abstract. The taxonomy matches against it, and it is mined for
  emergent terms.
- `caseCount` — lifetime linked cases.
- `caseCount_365` — linked cases in a fixed trailing 365 days.

## Case-count semantics

`caseCount_365` is published by Red Hat and cannot be re-windowed. A query for a
90-day range still returns the trailing-year count, so no case-volume statement
shorter than a year is derivable from this API. The demand view in the report is
annual for that reason, whatever `--as-of` says.

## Fields present but unused

`kcsRateUp` and `kcsRateDown` carry article usefulness votes, and `sbr`,
`internalTags`, and `issueTag` carry extra classification. They are sparse in
the RHDH corpus — fewer than a dozen articles carry any vote — so the report
does not read them. Revisit if the vote coverage improves.

The analysis filters on the `YYYY-MM-DD` prefix of `createdDate`. Theme
matching reads `title`, `issue` (the abstract), `category`, and `component`, so
broad stems match abstract prose; `--include-abstracts` only controls whether an
abstract is echoed in the output, never whether it is matched.

## Runtime

`scripts/analyze-kb.mjs` is the committed, dependency-free runtime artifact. Do
not add a dependency or build step at skill runtime.
