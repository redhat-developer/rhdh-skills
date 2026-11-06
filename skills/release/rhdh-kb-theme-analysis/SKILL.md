---
name: rhdh-kb-theme-analysis
description: >-
  Analyzes Red Hat Customer Portal Knowledgebase Solution articles for Red Hat
  Developer Hub, compares rolling 90-day and 365-day windows, and turns public
  article metadata into support-theme, documentation, and roadmap signals. Use
  for RHDH KB trend analysis, support-theme reviews, or product friction scans.
compatibility: "Node 18+; no dependencies."
---

# RHDH KB theme analysis

Turn public Red Hat Customer Portal KB metadata into a product-facing view of
RHDH support themes. The workflow is read-only and uses the public KB search
API; it does not open, read, or modify private support cases or issue-tracker
data.

## Run

Use the bundled script:

```bash
node scripts/analyze-kb.mjs \
  --product "Red Hat Developer Hub" \
  --as-of YYYY-MM-DD \
  --format markdown
```

Defaults:

- product: `Red Hat Developer Hub`
- recent window: trailing 90 days
- comparison window: trailing 365 days
- output: Markdown

Pass explicit `--recent-since`, `--recent-until`,
`--comparison-since`, or `--comparison-until` values when the user asks for a
calendar quarter, calendar year, release window, or custom range.

Choose the taxonomy before the run:

- omitted: the built-in clusters, for a general support-theme scan;
- `--themes PATH`: a taxonomy proposed for this investigation;
- `--themes none`: no clustering, leaving the grouping to you.

Read `references/taxonomy.md` before writing a taxonomy file. Use
`--format json` when the answer needs every article rather than the top 15, and
add `--include-abstracts` when the grouping will be done from article text.

`component` is unnormalized free text. The report folds case, whitespace, and
dashes by default; pass `--component-aliases PATH` with a JSON object of
`{"from": "to"}` pairs when a question needs real synonyms merged, and say that
you did.

## Authoring and demand

The report answers two questions. The `recent` and `comparison` windows filter on
`createdDate` and measure what support published. The `demand` view ignores
`createdDate` and weights the whole corpus by `caseCount_365`. Lead with demand
when the question is about customers; lead with authoring when it is about
publishing cadence or taxonomy coverage. Case weights are annual — a quarterly
case-volume answer is not derivable from this data.

## Boundary with neighbouring skills

- Use this skill for public KB article themes and release-planning signals.
- Use `/rhdh-release-status` for open Jira work, blockers, CVEs, and release
  readiness.
- Use `/rhdh-feature-docs` to write or update documentation content.
- Use `/rhdh-platform-lifecycle` for vendor support phases and EOL dates.

## Interpretation

Read `references/interpretation.md` before turning script output into product,
documentation, or roadmap recommendations. It carries the taxonomy the run used
and the rule that both windows share one.

Read `references/api.md` only when changing the query, troubleshooting the API,
or extending the script.

## Failure mode

If the KB API is unreachable or returns a non-2xx response, report that the
public KB data could not be fetched. Do not infer themes from memory or from a
previous run. Name the endpoint status if the script provides one.

## Completion

Complete when the answer names:

- the product and run date;
- both window boundaries;
- recent and comparison article counts;
- the strongest theme signals, as `movement` classes rather than adjectives;
- the demand view, its attributed case total, and any concentration warning;
- the stale, high-touch articles worth refreshing;
- linked citations for every article named in the answer;
- a final “Product and documentation improvement areas” section that connects recent findings to candidate product and documentation work;
- the caveats from the interpretation reference.
