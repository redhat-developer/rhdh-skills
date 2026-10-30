#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const DEFAULT_PRODUCT = 'Red Hat Developer Hub';
export const DEFAULT_RECENT_DAYS = 90;
export const DEFAULT_COMPARISON_DAYS = 365;
export const KB_ENDPOINT = 'https://access.redhat.com/hydra/rest/search/platform/kbase';
export const MAX_RESULTS = 10000;
export const PAGE_SIZE = 100;
export const REQUEST_TIMEOUT_MS = 30000;

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const BUILT_IN_THEME_RULES = [
  {
    theme: 'upgrade-plugin-reliability',
    pattern:
      /\b(?:upgrad(?:e|es|ed|ing)|plugins?|dynamic plugins?|install-dynamic-plugins|catalog indexes?|orchestrators?|modules?|dependenc(?:y|ies)|plugin versions?|version resolutions?|version mismatches?|compatibility matrix)\b/i,
  },
  {
    theme: 'authentication-identity',
    pattern:
      /\b(?:authentications?|authorizations?|auth|logins?|sso|saml|oidc|jwks|entra|azure|keycloaks?|gitlabs?|githubs?|mfa|tokens?|cookies?|redirects?)\b/i,
  },
  {
    theme: 'operator-openshift-deployment',
    pattern:
      /\b(?:operators?|openshifts?|ocp|helms?|deployments?|deploys?|deployed|deploying|regist(?:ry|ries)|images?|tls|certificates?|prox(?:y|ies)|networks?|disconnected|air-gapped|pods?|init containers?|init-containers?|crashloops?|storages?|pvcs?|namespaces?)\b/i,
  },
  {
    theme: 'rbac-permissions',
    pattern:
      /\b(?:rbac|permissions?|roles?|policies?|admins?|visibility|entit(?:y|ies)|owned|access(?:es)?|groups?)\b/i,
  },
  {
    theme: 'configuration-ui',
    pattern:
      /\b(?:configs?|configurations?|customizations?|custom|yamls?|schemas?|widgets?|forms?|templates?|ui|themes?|logos?|sidebars?|menus?|localizations?)\b/i,
  },
  {
    theme: 'observability-diagnostics',
    pattern:
      /\b(?:logs?|logging|debugs?|debugging|must-gathers?|audits?|auditing|monitors?|monitoring|performances?|slows?|crash(?:es|ed|ing)?|diagnostics?|traces?|tracing)\b/i,
  },
  {
    theme: 'support-version-clarity',
    pattern:
      /\b(?:supports?|supported|supportability|subscriptions?|lifecycles?|(?:in)?compatib(?:le|ility|ilities)|fips|azure devops|local supported|product supports?)\b/i,
  },
  {
    theme: 'catalog-database-scale',
    pattern:
      /\b(?:catalogs?|databases?|postgres(?:ql)?|replicas?|(?:auto|down)?scal(?:e|es|ed|ing)|large(?:r|st)?|many|ingestions?|schedulers?|scheduling|syncs?|syncing|synced|synchronizations?)\b/i,
  },
];

function asList(value) {
  if (Array.isArray(value)) {
    return value.filter((item) => typeof item === 'string' && item.length > 0);
  }
  if (typeof value === 'string' && value.length > 0) {
    return [value];
  }
  return [];
}

export const ABSTRACT_LIMIT = 300;

const BUILT_IN_TAXONOMY = {
  mode: 'built-in',
  name: 'built-in',
  rules: BUILT_IN_THEME_RULES,
};

export function loadTaxonomy(filePath) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(filePath, 'utf8'));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Cannot read taxonomy file ${filePath}: ${message}`);
  }

  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error(
      `Taxonomy file ${filePath} must be a non-empty JSON array of { "theme", "pattern" } objects`,
    );
  }

  const seen = new Set();
  const rules = parsed.map((entry, index) => {
    const theme = entry?.theme;
    const pattern = entry?.pattern;
    if (typeof theme !== 'string' || theme.length === 0) {
      throw new Error(`Taxonomy entry ${index} in ${filePath} needs a non-empty "theme"`);
    }
    if (typeof pattern !== 'string' || pattern.length === 0) {
      throw new Error(`Taxonomy entry "${theme}" in ${filePath} needs a non-empty "pattern"`);
    }
    if (seen.has(theme)) {
      throw new Error(`Taxonomy file ${filePath} repeats the theme "${theme}"`);
    }
    seen.add(theme);
    try {
      return { theme, pattern: new RegExp(pattern, 'i') };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(
        `Taxonomy pattern for "${theme}" in ${filePath} is not a valid regular expression: ${message}`,
      );
    }
  });

  return { mode: 'custom', name: filePath, rules };
}

export function resolveTaxonomy(value) {
  if (value === undefined) {
    return BUILT_IN_TAXONOMY;
  }
  if (value === 'none') {
    return { mode: 'none', name: 'none', rules: null };
  }
  return loadTaxonomy(value);
}

export function usage() {
  return `Usage: analyze-kb.mjs [options]

Analyze Red Hat Customer Portal KB Solution articles.

Options:
  --product NAME              Product filter (default: "${DEFAULT_PRODUCT}")
  --as-of YYYY-MM-DD          Analysis date (default: today, local time)
  --recent-days N             Recent window length (default: ${DEFAULT_RECENT_DAYS})
  --comparison-days N         Comparison window length (default: ${DEFAULT_COMPARISON_DAYS})
  --recent-since DATE         Explicit recent window start
  --recent-until DATE         Explicit recent window end
  --comparison-since DATE     Explicit comparison window start
  --comparison-until DATE     Explicit comparison window end
  --themes PATH|none          Theme taxonomy JSON file, or "none" to skip clustering (default: built-in)
  --include-abstracts         Include a truncated abstract per article in JSON output
  --format FORMAT             Output format: markdown or json (default: markdown)
  -h, --help                  Show this help

Examples:
  analyze-kb.mjs
  analyze-kb.mjs --as-of 2026-10-30
  analyze-kb.mjs --recent-days 30 --comparison-days 180
  analyze-kb.mjs --recent-since 2026-07-01 --recent-until 2026-09-30
  analyze-kb.mjs --themes ./taxonomy.json --format json --include-abstracts
  analyze-kb.mjs --themes none --format json
`;
}

function nextValue(argv, index, flag) {
  const nextIndex = index + 1;
  if (nextIndex >= argv.length) {
    throw new Error(`Missing value for ${flag}`);
  }
  return { value: argv[nextIndex], nextIndex };
}

export function parseArgs(argv) {
  const args = {
    product: DEFAULT_PRODUCT,
    asOf: todayIso(),
    format: 'markdown',
    help: false,
    includeAbstracts: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '-h' || arg === '--help') {
      args.help = true;
      continue;
    }
    if (arg === '--include-abstracts') {
      args.includeAbstracts = true;
      continue;
    }

    const flagsWithValues = {
      '--product': 'product',
      '--as-of': 'asOf',
      '--recent-days': 'recentDays',
      '--comparison-days': 'comparisonDays',
      '--recent-since': 'recentSince',
      '--recent-until': 'recentUntil',
      '--comparison-since': 'comparisonSince',
      '--comparison-until': 'comparisonUntil',
      '--themes': 'themes',
      '--format': 'format',
    };

    if (arg in flagsWithValues) {
      const { value, nextIndex } = nextValue(argv, i, arg);
      const key = flagsWithValues[arg];
      if (key === 'recentDays' || key === 'comparisonDays') {
        const parsed = Number(value);
        if (!Number.isInteger(parsed) || parsed <= 0) {
          throw new Error(`${arg} must be a positive integer`);
        }
        args[key] = parsed;
      } else if (key === 'format') {
        if (value !== 'json' && value !== 'markdown') {
          throw new Error(`Invalid format: ${value}. Use json or markdown.`);
        }
        args.format = value;
      } else {
        args[key] = value;
      }
      i = nextIndex;
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  validateDate(args.asOf, '--as-of');
  for (const [flag, value] of Object.entries({
    '--recent-since': args.recentSince,
    '--recent-until': args.recentUntil,
    '--comparison-since': args.comparisonSince,
    '--comparison-until': args.comparisonUntil,
  })) {
    if (value !== undefined) {
      validateDate(value, flag);
    }
  }

  if (args.recentDays !== undefined && (args.recentSince !== undefined || args.recentUntil !== undefined)) {
    throw new Error('--recent-days cannot be combined with --recent-since or --recent-until');
  }
  if (args.comparisonDays !== undefined && (args.comparisonSince !== undefined || args.comparisonUntil !== undefined)) {
    throw new Error('--comparison-days cannot be combined with --comparison-since or --comparison-until');
  }
  if (args.recentUntil !== undefined && args.recentSince === undefined) {
    throw new Error('--recent-until requires --recent-since');
  }
  if (args.comparisonUntil !== undefined && args.comparisonSince === undefined) {
    throw new Error('--comparison-until requires --comparison-since');
  }

  args.themes = resolveTaxonomy(args.themes);

  return args;
}

export function todayIso() {
  return new Date().toLocaleDateString('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

export function validateDate(value, flag) {
  if (!ISO_DATE_RE.test(value)) {
    throw new Error(`${flag} must use YYYY-MM-DD`);
  }
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value) {
    throw new Error(`${flag} is not a valid calendar date: ${value}`);
  }
}

export function addDaysIso(dateIso, days) {
  const date = new Date(`${dateIso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function daysBetweenInclusive(start, end) {
  const startTime = new Date(`${start}T00:00:00Z`).getTime();
  const endTime = new Date(`${end}T00:00:00Z`).getTime();
  return Math.round((endTime - startTime) / 86400000) + 1;
}

function resolveWindow(asOf, days, since, until, label) {
  if (since !== undefined) {
    const end = until ?? asOf;
    if (since > end) {
      throw new Error(`${label} start must not be after ${label} end`);
    }
    return { start: since, end, days: daysBetweenInclusive(since, end) };
  }

  const length = days ?? (label === 'recent' ? DEFAULT_RECENT_DAYS : DEFAULT_COMPARISON_DAYS);
  return {
    start: addDaysIso(asOf, -(length - 1)),
    end: asOf,
    days: length,
  };
}

export function resolveWindows(args) {
  return {
    recent: resolveWindow(args.asOf, args.recentDays, args.recentSince, args.recentUntil, 'recent'),
    comparison: resolveWindow(args.asOf, args.comparisonDays, args.comparisonSince, args.comparisonUntil, 'comparison'),
  };
}

export function buildQuery(product, start, rows) {
  const params = new URLSearchParams({
    q: '*',
    start: String(start),
    rows: String(rows),
    facet: 'true',
    'facet.mincount': '1',
    enableElevation: 'true',
    'f.standard_product.facet.limit': '-1',
    redhat_client: 'kb-search',
  });
  params.append('fq', '-id:Other');
  params.append('fq', 'documentKind:(Solution Article)');
  params.append('facet.field', 'documentKind');
  params.append('facet.field', '{!ex=productFilter}standard_product');
  params.append('fq', `{!tag=productFilter}standard_product:"${product}"`);

  const url = new URL(KB_ENDPOINT);
  url.search = params.toString();
  return url;
}

export async function fetchKbDocs(product) {
  const docs = [];
  let numFound;

  while (true) {
    const url = buildQuery(product, docs.length, PAGE_SIZE);
    const response = await fetch(url, {
      headers: {
        Accept: 'application/json',
        'User-Agent': 'rhdh-kb-theme-analysis/1.0',
      },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`Red Hat KB request failed: ${response.status} ${response.statusText}`);
    }

    const json = await response.json();
    const batch = Array.isArray(json.response?.docs) ? json.response.docs : [];
    docs.push(...batch);

    const responseNumFound = json.response?.numFound;
    if (responseNumFound !== undefined) {
      numFound = Number(responseNumFound);
    } else if (numFound === undefined) {
      numFound = docs.length;
    }

    if (batch.length === 0 || docs.length >= Math.min(numFound, MAX_RESULTS)) {
      break;
    }
  }

  const fetched = docs.slice(0, MAX_RESULTS);
  return {
    docs: fetched,
    numFound,
    truncated: numFound > fetched.length,
  };
}

function docCreatedDate(doc) {
  const value = doc.createdDate;
  if (typeof value !== 'string' || !ISO_DATE_RE.test(value.slice(0, 10))) {
    return null;
  }
  return value.slice(0, 10);
}

export function isInWindow(doc, window) {
  const created = docCreatedDate(doc);
  return created !== null && created >= window.start && created <= window.end;
}

function countValues(docs, field) {
  const counts = new Map();
  for (const doc of docs) {
    for (const value of asList(doc[field])) {
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

function countByPeriod(docs, period) {
  const counts = new Map();
  for (const doc of docs) {
    const created = docCreatedDate(doc);
    if (created === null) {
      continue;
    }
    const key = period === 'month' ? created.slice(0, 7) : created.slice(0, 4);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => a.value.localeCompare(b.value));
}

function docText(doc) {
  return [doc.title, ...asList(doc.issue), ...asList(doc.category), ...asList(doc.component)].join(' ');
}

export function themeHints(doc, rules = BUILT_IN_THEME_RULES) {
  const text = docText(doc);
  return rules.filter((rule) => rule.pattern.test(text)).map((rule) => rule.theme);
}

function abstractText(doc) {
  const issue = asList(doc.issue).join(' ');
  if (issue.length === 0) {
    return undefined;
  }
  if (issue.length <= ABSTRACT_LIMIT) {
    return issue;
  }
  return `${issue.slice(0, ABSTRACT_LIMIT).trimEnd()}\u2026`;
}

function articleSummary(doc, rules, includeAbstracts) {
  const summary = {
    id: doc.id,
    title: doc.title,
    url: doc.view_uri ?? `https://access.redhat.com/solutions/${doc.id}`,
    createdDate: docCreatedDate(doc) ?? 'unknown',
    categories: asList(doc.category),
    tags: asList(doc.tag),
    components: asList(doc.component),
    caseCount: doc.caseCount ?? 0,
    caseCount365: doc.caseCount_365 ?? 0,
    themes: rules === null ? null : themeHints(doc, rules),
  };
  if (includeAbstracts) {
    const abstract = abstractText(doc);
    if (abstract !== undefined) {
      summary.abstract = abstract;
    }
  }
  return summary;
}

function summarizeWindow(docs, window, rules) {
  const windowDocs = docs.filter((doc) => isInWindow(doc, window));

  return {
    window,
    articleCount: windowDocs.length,
    categories: countValues(windowDocs, 'category'),
    tags: countValues(windowDocs, 'tag'),
    components: countValues(windowDocs, 'component'),
    months: countByPeriod(windowDocs, 'month'),
    years: countByPeriod(windowDocs, 'year'),
    themes: rules === null ? null : countThemes(windowDocs, window, rules),
    unmatched:
      rules === null ? null : windowDocs.filter((doc) => themeHints(doc, rules).length === 0).length,
  };
}

function countThemes(windowDocs, window, rules) {
  const themes = new Map();

  for (const doc of windowDocs) {
    const cases = doc.caseCount_365 ?? 0;
    for (const theme of themeHints(doc, rules)) {
      const current = themes.get(theme) ?? { count: 0, caseCount365: 0, maxArticleCases: 0 };
      current.count += 1;
      current.caseCount365 += cases;
      current.maxArticleCases = Math.max(current.maxArticleCases, cases);
      themes.set(theme, current);
    }
  }

  return [...themes.entries()]
    .map(([theme, value]) => ({
      theme,
      count: value.count,
      caseCount365: value.caseCount365,
      maxArticleCases: value.maxArticleCases,
      topArticleShare: value.caseCount365 === 0 ? 0 : value.maxArticleCases / value.caseCount365,
      perDay: value.count / window.days,
      share: windowDocs.length === 0 ? 0 : value.count / windowDocs.length,
    }))
    .sort((a, b) => b.count - a.count || a.theme.localeCompare(b.theme));
}

export function summarize(fetchResult, args) {
  const { docs, numFound, truncated } = fetchResult;
  const { recent, comparison } = resolveWindows(args);
  const taxonomy = args.themes ?? BUILT_IN_TAXONOMY;
  const rules = taxonomy.rules ?? null;
  const createdDates = docs
    .map(docCreatedDate)
    .filter((date) => date !== null)
    .sort();

  const articles = [];
  for (const doc of docs) {
    const windows = [];
    if (isInWindow(doc, recent)) {
      windows.push('recent');
    }
    if (isInWindow(doc, comparison)) {
      windows.push('comparison');
    }
    articles.push({ ...articleSummary(doc, rules, args.includeAbstracts === true), windows });
  }
  articles.sort(
    (a, b) => b.createdDate.localeCompare(a.createdDate) || String(a.id).localeCompare(String(b.id)),
  );

  return {
    product: args.product,
    asOf: args.asOf,
    taxonomy:
      rules === null ? null : { mode: taxonomy.mode, name: taxonomy.name, themes: rules.map((rule) => rule.theme) },
    recent: summarizeWindow(docs, recent, rules),
    comparison: summarizeWindow(docs, comparison, rules),
    allTime: {
      articleCount: numFound,
      fetchedArticles: docs.length,
      truncated,
      firstCreated: createdDates[0] ?? null,
      lastCreated: createdDates[createdDates.length - 1] ?? null,
    },
    articles,
    source: KB_ENDPOINT,
    fetchedAt: new Date().toISOString(),
  };
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatCountList(counts, limit = 10) {
  if (counts.length === 0) {
    return '- none';
  }
  return counts
    .slice(0, limit)
    .map((item) => `- ${item.value}: ${item.count}`)
    .join('\n');
}

function formatThemeCases(item) {
  const base = `${item.caseCount365} linked support cases (365d, summed)`;
  if (item.caseCount365 > 0 && item.topArticleShare > 0.5) {
    return `${base}; one article supplies ${formatPercent(item.topArticleShare)}`;
  }
  return base;
}

function formatThemeList(themes) {
  if (themes.length === 0) {
    return '- none';
  }
  return themes
    .map(
      (item) =>
        `- ${item.theme}: ${formatArticleCount(item.count)}, ${formatPercent(item.share)} of window, ${item.perDay.toFixed(2)} per day, ${formatThemeCases(item)}`,
    )
    .join('\n');
}

function formatArticles(articles, limit = 15) {
  if (articles.length === 0) {
    return '- none';
  }
  return articles
    .slice(0, limit)
    .map(
      (article) =>
        `- ${article.createdDate} — [${article.title}](${article.url}) (linked support cases, 365d: ${article.caseCount365})`,
    )
    .join('\n');
}

function formatArticleCount(count) {
  return `${count} ${count === 1 ? 'article' : 'articles'}`;
}

function formatAllTime(report) {
  if (report.allTime.truncated) {
    return `≥ ${report.allTime.articleCount} (capped; fetched ${report.allTime.fetchedArticles})`;
  }
  return `${report.allTime.articleCount} (${report.allTime.firstCreated ?? 'unknown'} to ${report.allTime.lastCreated ?? 'unknown'})`;
}

const CASE_TOTAL_CAVEAT =
  '- Linked support-case totals are article-level caseCount_365 values summed across matching articles; they are not unique cases and may include multi-product articles.';

function caveatsFor(report) {
  const mode = report.taxonomy?.mode ?? 'none';
  const lines = [
    '- Article count is not unique support-case volume.',
    '- The public KB payload does not confirm article authorship.',
  ];

  if (mode === 'none') {
    lines.push('- Theme signals are absent because no taxonomy was applied.');
  } else {
    lines.push(
      mode === 'custom'
        ? '- Theme signals come from the supplied keyword taxonomy, not from official Red Hat categories.'
        : '- Theme signals are heuristic keyword clusters, not official Red Hat categories.',
    );
    lines.push(CASE_TOTAL_CAVEAT);
  }

  lines.push(formatWindowCaveat(report));
  return lines.join('\n');
}

function formatWindowCaveat(report) {
  const recent = report.recent.window;
  const comparison = report.comparison.window;
  const nested = recent.start >= comparison.start && recent.end <= comparison.end;
  if (nested) {
    return '- The recent window is a subset of the comparison window; use per-day rates and shares rather than raw counts alone.';
  }
  return '- The recent and comparison windows are not nested; use per-day rates and window shares rather than raw counts alone.';
}

export function renderMarkdown(report) {
  const recent = report.recent;
  const comparison = report.comparison;
  const recentArticles = report.articles.filter((article) => article.windows.includes('recent'));
  const topRecentArticles = [...recentArticles]
    .sort((a, b) => b.caseCount365 - a.caseCount365 || b.createdDate.localeCompare(a.createdDate))
    .slice(0, 15);

  const articleHeading =
    recentArticles.length > 0
      ? `## Most-linked recent articles (top ${topRecentArticles.length} of ${recentArticles.length} by linked support cases)`
      : '## Most-linked recent articles';
  const taxonomyLine =
    report.taxonomy === null
      ? '- Taxonomy: none (group the article list yourself)'
      : `- Taxonomy: ${path.basename(report.taxonomy.name)} (${report.taxonomy.themes.length} clusters)`;
  const unmatchedLines =
    report.taxonomy === null
      ? ''
      : `\n- Recent unmatched by taxonomy: ${recent.unmatched}\n- Comparison unmatched by taxonomy: ${comparison.unmatched}`;
  const taxonomyMode = report.taxonomy?.mode ?? 'none';
  const themeLabel = taxonomyMode === 'custom' ? 'Theme signals' : 'Heuristic theme signals';
  const themeSections =
    taxonomyMode === 'none'
      ? `## Theme signals

No taxonomy applied. Group the article list below yourself, using one taxonomy across both windows, and say which taxonomy you used.

`
      : `## ${themeLabel} — recent

${formatThemeList(recent.themes)}

## ${themeLabel} — comparison

${formatThemeList(comparison.themes)}

`;

  return `# RHDH KB theme analysis

- Product: ${report.product}
- Run date: ${report.asOf}
- Recent window: ${recent.window.start} to ${recent.window.end} (${recent.window.days} days)
- Comparison window: ${comparison.window.start} to ${comparison.window.end} (${comparison.window.days} days)
- All-time articles: ${formatAllTime(report)}
${taxonomyLine}

## Volume

- Recent articles: ${recent.articleCount}
- Comparison articles: ${comparison.articleCount}
- Recent daily rate: ${(recent.articleCount / recent.window.days).toFixed(2)}
- Comparison daily rate: ${(comparison.articleCount / comparison.window.days).toFixed(2)}${unmatchedLines}

## Recent categories

${formatCountList(recent.categories)}

## Comparison categories

${formatCountList(comparison.categories)}

## Recent tags

${formatCountList(recent.tags)}

## Comparison tags

${formatCountList(comparison.tags)}

## Recent components

${formatCountList(recent.components)}

## Comparison components

${formatCountList(comparison.components)}

${themeSections}${articleHeading}

${formatArticles(topRecentArticles)}

## Caveats

${caveatsFor(report)}
`;
}

async function main() {
  try {
    const args = parseArgs(process.argv.slice(2));
    if (args.help) {
      process.stdout.write(`${usage()}\n`);
      return;
    }

    const fetchResult = await fetchKbDocs(args.product);
    const report = summarize(fetchResult, args);
    if (args.format === 'json') {
      process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    } else {
      process.stdout.write(`${renderMarkdown(report)}\n`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Red Hat KB analysis failed: ${message}\n`);
    process.exitCode = 1;
  }
}

const isDirectRun =
  process.argv[1] !== undefined && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isDirectRun) {
  await main();
}
