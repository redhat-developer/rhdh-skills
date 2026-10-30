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

## Useful fields

Treat these fields as optional because Red Hat can change the public response.
The script accepts either string or array shapes for `category`, `component`,
and `tag`:

- `id`
- `title`
- `view_uri`
- `createdDate`
- `lastModifiedDate`
- `category`
- `component`
- `tag`
- `standard_product`
- `issue`
- `caseCount`
- `caseCount_365`

The analysis filters on the `YYYY-MM-DD` prefix of `createdDate`. Theme
matching reads `title`, `issue` (the abstract), `category`, and `component`, so
broad stems match abstract prose; `--include-abstracts` only controls whether an
abstract is echoed in the output, never whether it is matched.

## Runtime

`scripts/analyze-kb.mjs` is the committed, dependency-free runtime artifact. Do
not add a dependency or build step at skill runtime.
