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

export const SCHEMA_VERSION = 2;
export const STALE_AFTER_DAYS = 365;
export const DEMAND_TOP_ARTICLES = 20;
export const REFRESH_CANDIDATES = 15;
export const EMERGENT_TERMS = 10;
export const MIN_MOVEMENT_OBSERVATIONS = 5;
export const GROWING_SHARE_RATIO = 1.25;
export const DECLINING_SHARE_RATIO = 0.8;
export const CONCENTRATION_WARNING_SHARE = 0.25;
export const NEW_THEME_MIN_ARTICLES = 3;
export const MIN_TERM_ARTICLES = 3;
export const NEW_TERM_MIN_ARTICLES = 3;
export const RISING_TERM_RATIO = 2;
export const UBIQUITOUS_TERM_SHARE = 0.3;
export const UBIQUITOUS_TERM_MIN_ARTICLES = 10;

const STOPWORDS = new Set(
  `about above after again against also and any are because been before being below between both but can cannot could did does doing down during each few for from further had has have having here how into its itself just may might more most must not now off once only other out over own same should some such than that the their them then there these they this those through under until very was were what when where which while who whom why will with would your rhdh redhat even show shows showing shown use used uses using get gets getting set sets setting make makes making need needs needed way ways like want wants two three first second last missing loading slow unable stuck issue issues problem problems`.split(
    /\s+/,
  ),
);

export function normalizeComponentValue(value) {
  return String(value).trim().replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').toLowerCase();
}

export function loadComponentAliases(filePath) {
  const aliases = new Map();
  if (filePath === undefined) {
    return aliases;
  }

  let parsed;
  try {
    parsed = JSON.parse(readFileSync(filePath, 'utf8'));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Cannot read component alias file ${filePath}: ${message}`);
  }

  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(
      `Component alias file ${filePath} must be a JSON object of {"from": "to"} strings`,
    );
  }

  for (const [from, to] of Object.entries(parsed)) {
    if (typeof to !== 'string' || to.length === 0) {
      throw new Error(`Component alias "${from}" in ${filePath} needs a non-empty string target`);
    }
    const key = normalizeComponentValue(from);
    if (aliases.has(key) && aliases.get(key) !== to) {
      throw new Error(`Component alias file ${filePath} maps "${key}" to two different targets`);
    }
    aliases.set(key, to);
  }

  return aliases;
}

export function productsOf(doc) {
  const declared = asList(doc.standard_product);
  if (declared.length > 0) {
    return declared;
  }
  const fallback = asList(doc.product);
  return fallback.length > 0 ? fallback : ['unspecified'];
}

export function productCountOf(doc) {
  return Math.max(1, productsOf(doc).length);
}

export function casesRawOf(doc) {
  const value = Number(doc.caseCount_365 ?? 0);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function casesAttributedOf(doc) {
  return casesRawOf(doc) / productCountOf(doc);
}

export function roundTo(value, places) {
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
}

export function lastModifiedOf(doc) {
  const value = doc.lastModifiedDate;
  if (typeof value !== 'string' || !ISO_DATE_RE.test(value.slice(0, 10))) {
    return null;
  }
  return value.slice(0, 10);
}

export function ageInDays(dateIso, asOf) {
  if (dateIso === null) {
    return null;
  }
  const then = new Date(`${dateIso}T00:00:00Z`).getTime();
  const now = new Date(`${asOf}T00:00:00Z`).getTime();
  if (Number.isNaN(then) || Number.isNaN(now)) {
    return null;
  }
  return Math.round((now - then) / 86400000);
}

export function docState(doc) {
  if (typeof doc.kcsState === 'string' && doc.kcsState.length > 0) {
    return doc.kcsState;
  }
  if (typeof doc.publication_state === 'string' && doc.publication_state.length > 0) {
    return doc.publication_state;
  }
  return 'unknown';
}

function articleUrl(doc) {
  return doc.view_uri ?? `https://access.redhat.com/solutions/${doc.id}`;
}

export function tokensOf(doc) {
  const text = [doc.title, ...asList(doc.tag)].join(' ');
  const tokens = new Set();
  for (const token of text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').split(' ')) {
    if (token.length < 4 || /^\d+$/.test(token) || STOPWORDS.has(token)) {
      continue;
    }
    tokens.add(token);
  }
  return tokens;
}

function countComponents(docs, aliases = new Map()) {
  const counts = new Map();
  const rawValues = new Set();
  for (const doc of docs) {
    for (const value of asList(doc.component)) {
      rawValues.add(value);
      const folded = normalizeComponentValue(value);
      const label = aliases.get(folded) ?? folded;
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
  }
  const sorted = [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
  return {
    normalized: sorted,
    variants: { rawValues: rawValues.size, foldedValues: sorted.length },
  };
}

function countStates(docs) {
  const counts = new Map();
  for (const doc of docs) {
    const state = docState(doc);
    counts.set(state, (counts.get(state) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

function movementClass(recentCount, baselineCount, shareRatio) {
  if (recentCount === 0 && baselineCount === 0) {
    return 'insufficient';
  }
  if (baselineCount === 0) {
    return recentCount >= NEW_THEME_MIN_ARTICLES ? 'new' : 'insufficient';
  }
  if (recentCount === 0) {
    return baselineCount >= MIN_MOVEMENT_OBSERVATIONS ? 'declining' : 'insufficient';
  }
  if (recentCount < MIN_MOVEMENT_OBSERVATIONS || baselineCount < MIN_MOVEMENT_OBSERVATIONS) {
    return 'insufficient';
  }
  if (shareRatio === null) {
    return 'insufficient';
  }
  if (shareRatio >= GROWING_SHARE_RATIO) {
    return 'growing';
  }
  if (shareRatio <= DECLINING_SHARE_RATIO) {
    return 'declining';
  }
  return 'stable';
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
  --component-aliases PATH    JSON object mapping component names to canonical names
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
      '--component-aliases': 'componentAliases',
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
  args.componentAliases = loadComponentAliases(args.componentAliases);

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
    url: articleUrl(doc),
    createdDate: docCreatedDate(doc) ?? 'unknown',
    lastModifiedDate: lastModifiedOf(doc),
    kcsState: docState(doc),
    categories: asList(doc.category),
    tags: asList(doc.tag),
    components: asList(doc.component),
    products: productsOf(doc),
    productCount: productCountOf(doc),
    caseCount: doc.caseCount ?? 0,
    caseCount365: roundTo(casesRawOf(doc), 1),
    casesAttributed: roundTo(casesAttributedOf(doc), 2),
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

function summarizeWindow(docs, window, rules, aliases = new Map()) {
  const windowDocs = docs.filter((doc) => isInWindow(doc, window));
  const components = countComponents(windowDocs, aliases);

  return {
    window,
    articleCount: windowDocs.length,
    categories: countValues(windowDocs, 'category'),
    tags: countValues(windowDocs, 'tag'),
    components: countValues(windowDocs, 'component'),
    componentsNormalized: components.normalized,
    componentVariants: components.variants,
    kcsStates: countStates(windowDocs),
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
    const raw = casesRawOf(doc);
    const attributed = casesAttributedOf(doc);
    const dedicated = productCountOf(doc) === 1 ? raw : 0;
    for (const theme of themeHints(doc, rules)) {
      const current =
        themes.get(theme) ??
        {
          count: 0,
          articlesWithCases: 0,
          casesRaw: 0,
          casesAttributed: 0,
          casesDedicated: 0,
          topArticle: null,
        };
      current.count += 1;
      if (raw > 0) {
        current.articlesWithCases += 1;
      }
      current.casesRaw += raw;
      current.casesAttributed += attributed;
      current.casesDedicated += dedicated;
      if (raw > 0 && (current.topArticle === null || attributed > current.topArticle.attributed)) {
        current.topArticle = {
          id: doc.id,
          title: doc.title,
          url: articleUrl(doc),
          raw: roundTo(raw, 1),
          attributed: roundTo(attributed, 1),
          productCount: productCountOf(doc),
        };
      }
      themes.set(theme, current);
    }
  }

  return [...themes.entries()]
    .map(([theme, value]) => ({
      theme,
      count: value.count,
      articlesWithCases: value.articlesWithCases,
      casesRaw: roundTo(value.casesRaw, 1),
      casesAttributed: roundTo(value.casesAttributed, 1),
      casesDedicated: roundTo(value.casesDedicated, 1),
      caseCount365: roundTo(value.casesRaw, 1),
      maxArticleCases: value.topArticle === null ? 0 : value.topArticle.raw,
      topArticleShare:
        value.casesRaw === 0 ? 0 : roundTo((value.topArticle?.raw ?? 0) / value.casesRaw, 3),
      topArticle:
        value.topArticle === null
          ? null
          : {
              id: value.topArticle.id,
              title: value.topArticle.title,
              url: value.topArticle.url,
              casesRaw: value.topArticle.raw,
              casesAttributed: value.topArticle.attributed,
              productCount: value.topArticle.productCount,
            },
      perDay: window && window.days ? roundTo(value.count / window.days, 3) : null,
      share: windowDocs.length === 0 ? 0 : roundTo(value.count / windowDocs.length, 3),
    }))
    .sort((a, b) => b.count - a.count || a.theme.localeCompare(b.theme));
}

function summarizeDemand(docs, rules, aliases) {
  const withCases = docs.filter((doc) => casesRawOf(doc) > 0);
  const totalRaw = docs.reduce((sum, doc) => sum + casesRawOf(doc), 0);
  const totalAttributed = docs.reduce((sum, doc) => sum + casesAttributedOf(doc), 0);
  const ranked = [...withCases].sort(
    (a, b) => casesAttributedOf(b) - casesAttributedOf(a) || casesRawOf(b) - casesRawOf(a),
  );
  const topDoc = ranked[0] ?? null;
  const topRaw = topDoc === null ? 0 : casesRawOf(topDoc);
  const topAttributed = topDoc === null ? 0 : casesAttributedOf(topDoc);
  const components = countComponents(docs, aliases);
  const themes = rules === null ? null : countThemes(docs, { days: 365 }, rules);

  return {
    basis: 'caseCount_365 over the whole corpus; not windowed by createdDate',
    windowDays: 365,
    articleCount: docs.length,
    articlesWithCases: withCases.length,
    casesRaw: roundTo(totalRaw, 1),
    casesAttributed: roundTo(totalAttributed, 1),
    concentration: {
      topArticle:
        topDoc === null
          ? null
          : {
              id: topDoc.id,
              title: topDoc.title,
              url: articleUrl(topDoc),
              casesRaw: roundTo(topRaw, 1),
              casesAttributed: roundTo(topAttributed, 1),
              productCount: productCountOf(topDoc),
            },
      topShareRaw: totalRaw === 0 ? 0 : roundTo(topRaw / totalRaw, 3),
      topShareAttributed: totalAttributed === 0 ? 0 : roundTo(topAttributed / totalAttributed, 3),
      warned: totalRaw > 0 && topRaw / totalRaw > CONCENTRATION_WARNING_SHARE,
    },
    themes:
      themes === null
        ? null
        : [...themes].sort(
            (a, b) => b.casesAttributed - a.casesAttributed || a.theme.localeCompare(b.theme),
          ),
    components: components.normalized,
    topArticles: ranked
      .slice(0, DEMAND_TOP_ARTICLES)
      .map((doc) => ({
        id: doc.id,
        title: doc.title,
        url: articleUrl(doc),
        createdDate: docCreatedDate(doc),
        casesRaw: roundTo(casesRawOf(doc), 1),
        casesAttributed: roundTo(casesAttributedOf(doc), 1),
        productCount: productCountOf(doc),
        kcsState: docState(doc),
        themes: rules === null ? null : themeHints(doc, rules),
      })),
  };
}

function summarizeMovement(docs, recent, comparison, rules) {
  const nested = recent.start >= comparison.start && recent.end <= comparison.end;
  const baselineWindow =
    nested && recent.start > comparison.start
      ? {
          start: comparison.start,
          end: addDaysIso(recent.start, -1),
          days: daysBetweenInclusive(comparison.start, addDaysIso(recent.start, -1)),
        }
      : { start: comparison.start, end: comparison.end, days: comparison.days };

  const recentDocs = docs.filter((doc) => isInWindow(doc, recent));
  const baselineDocs = docs.filter((doc) => isInWindow(doc, baselineWindow));

  const countMap = (list) => {
    const counts = new Map();
    for (const doc of list) {
      for (const theme of themeHints(doc, rules)) {
        counts.set(theme, (counts.get(theme) ?? 0) + 1);
      }
    }
    return counts;
  };

  const recentCounts = rules === null ? new Map() : countMap(recentDocs);
  const baselineCounts = rules === null ? new Map() : countMap(baselineDocs);

  const themes =
    rules === null
      ? null
      : rules
          .map((rule) => {
            const theme = rule.theme;
            const recentCount = recentCounts.get(theme) ?? 0;
            const baselineCount = baselineCounts.get(theme) ?? 0;
            const recentPerDay = recentCount / recent.days;
            const baselinePerDay = baselineCount / baselineWindow.days;
            const ratio = baselinePerDay === 0 ? null : recentPerDay / baselinePerDay;
            const shareRecent = recentDocs.length === 0 ? 0 : recentCount / recentDocs.length;
            const shareBaseline = baselineDocs.length === 0 ? 0 : baselineCount / baselineDocs.length;
            const shareRatio = shareBaseline === 0 ? null : shareRecent / shareBaseline;
            return {
              theme,
              recentCount,
              baselineCount,
              recentPerDay: roundTo(recentPerDay, 3),
              baselinePerDay: roundTo(baselinePerDay, 3),
              ratio: ratio === null ? null : roundTo(ratio, 2),
              shareRatio: shareRatio === null ? null : roundTo(shareRatio, 2),
              shareRecent: roundTo(shareRecent, 3),
              shareBaseline: roundTo(shareBaseline, 3),
              deltaShare: roundTo(shareRecent - shareBaseline, 3),
              class: movementClass(recentCount, baselineCount, shareRatio),
            };
          })
          .sort((a, b) => b.recentCount - a.recentCount || a.theme.localeCompare(b.theme));

  const corpusRecentPerDay = recentDocs.length / recent.days;
  const corpusBaselinePerDay = baselineDocs.length / baselineWindow.days;

  return {
    baseline: {
      window: baselineWindow,
      articleCount: baselineDocs.length,
      nested,
      minObservations: MIN_MOVEMENT_OBSERVATIONS,
    },
    corpusRateRatio:
      corpusBaselinePerDay === 0 ? null : roundTo(corpusRecentPerDay / corpusBaselinePerDay, 2),
    themes,
  };
}

function summarizeKcs(docs, asOf) {
  const candidates = docs
    .filter((doc) => casesRawOf(doc) > 0)
    .map((doc) => ({ doc, modified: lastModifiedOf(doc), age: ageInDays(lastModifiedOf(doc), asOf) }))
    .filter((item) => item.age !== null && item.age > STALE_AFTER_DAYS)
    .sort(
      (a, b) =>
        casesAttributedOf(b.doc) - casesAttributedOf(a.doc) ||
        casesRawOf(b.doc) - casesRawOf(a.doc),
    )
    .slice(0, REFRESH_CANDIDATES)
    .map((item) => ({
      id: item.doc.id,
      title: item.doc.title,
      url: articleUrl(item.doc),
      casesRaw: roundTo(casesRawOf(item.doc), 1),
      casesAttributed: roundTo(casesAttributedOf(item.doc), 1),
      productCount: productCountOf(item.doc),
      lastModifiedDate: item.modified,
      daysSinceModified: item.age,
      kcsState: docState(item.doc),
    }));

  return {
    corpus: countStates(docs),
    staleAfterDays: STALE_AFTER_DAYS,
    refreshCandidates: candidates,
  };
}

function summarizeEmergentTerms(docs, recent, baselineWindow) {
  const recentDocs = docs.filter((doc) => isInWindow(doc, recent));
  const baselineDocs = docs.filter((doc) => isInWindow(doc, baselineWindow));

  const index = (list) => {
    const terms = new Map();
    for (const doc of list) {
      for (const token of tokensOf(doc)) {
        const entry = terms.get(token) ?? { count: 0, ids: [] };
        entry.count += 1;
        if (entry.ids.length < 2) {
          entry.ids.push(doc.id);
        }
        terms.set(token, entry);
      }
    }
    return terms;
  };

  const recentTerms = index(recentDocs);
  const baselineTerms = index(baselineDocs);
  const rows = [];

  const ubiquitous =
    recentDocs.length >= UBIQUITOUS_TERM_MIN_ARTICLES
      ? Math.ceil(recentDocs.length * UBIQUITOUS_TERM_SHARE)
      : Number.POSITIVE_INFINITY;

  for (const [term, entry] of recentTerms) {
    if (entry.count >= ubiquitous) {
      continue;
    }
    const baseline = baselineTerms.get(term) ?? { count: 0, ids: [] };
    const recentPerDay = entry.count / recent.days;
    const baselinePerDay = baseline.count / baselineWindow.days;
    const ratio = baselinePerDay === 0 ? null : recentPerDay / baselinePerDay;
    let klass = null;
    if (baseline.count === 0 && entry.count >= NEW_TERM_MIN_ARTICLES) {
      klass = 'new';
    } else if (entry.count >= MIN_TERM_ARTICLES && baseline.count > 0 && ratio !== null && ratio >= RISING_TERM_RATIO) {
      klass = 'rising';
    }
    if (klass === null) {
      continue;
    }
    rows.push({
      term,
      class: klass,
      recentArticles: entry.count,
      baselineArticles: baseline.count,
      baselineWindowRatio: roundTo(baselineWindow.days / recent.days, 2),
      ratio: ratio === null ? null : roundTo(ratio, 2),
      exampleIds: entry.ids,
    });
  }

  const pick = (klass) =>
    rows
      .filter((row) => row.class === klass)
      .sort((a, b) => b.recentArticles - a.recentArticles || a.term.localeCompare(b.term))
      .slice(0, EMERGENT_TERMS);

  return {
    newTerms: pick('new'),
    risingTerms: pick('rising'),
    minArticles: MIN_TERM_ARTICLES,
  };
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

  const demand = summarizeDemand(docs, rules, args.componentAliases ?? new Map());
  const movement = summarizeMovement(docs, recent, comparison, rules);
  const kcs = summarizeKcs(docs, args.asOf);
  const emergentTerms = summarizeEmergentTerms(docs, recent, movement.baseline.window);

  return {
    schemaVersion: SCHEMA_VERSION,
    product: args.product,
    asOf: args.asOf,
    taxonomy:
      rules === null ? null : { mode: taxonomy.mode, name: taxonomy.name, themes: rules.map((rule) => rule.theme) },
    recent: summarizeWindow(docs, recent, rules, args.componentAliases ?? new Map()),
    comparison: summarizeWindow(docs, comparison, rules, args.componentAliases ?? new Map()),
    demand,
    movement,
    kcs,
    emergentTerms,
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

function formatCases(count) {
  return `${count} attributed ${count === 1 ? 'case' : 'cases'}`;
}

function formatThemeCases(item) {
  const parts = [formatCases(item.casesAttributed)];
  if (item.casesAttributed !== item.casesRaw || item.casesRaw !== item.casesDedicated) {
    parts.push(`raw ${item.casesRaw}`, `single-product ${item.casesDedicated}`);
  }
  if (item.articlesWithCases > 1 && item.casesRaw > 0 && item.topArticleShare > 0.5) {
    parts.push(`one article supplies ${formatPercent(item.topArticleShare)} of raw weight`);
  }
  return parts.join('; ');
}

function formatThemeList(themes) {
  if (themes.length === 0) {
    return '- none';
  }
  return themes
    .map(
      (item) =>
        `- ${item.theme}: ${formatArticleCount(item.count)} (${item.articlesWithCases} with cases), ${formatPercent(item.share)} of window, ${item.perDay.toFixed(2)} per day, ${formatThemeCases(item)}`,
    )
    .join('\n');
}

function formatDemandThemes(themes, limit = 8) {
  if (themes === null) {
    return '- No taxonomy applied; rank the demand article list yourself.';
  }
  if (themes.length === 0) {
    return '- none';
  }
  return themes
    .slice(0, limit)
    .map(
      (item) =>
        `- ${item.theme}: ${formatCases(item.casesAttributed)} (raw ${item.casesRaw}, single-product ${item.casesDedicated}) across ${formatArticleCount(item.count)}, ${item.articlesWithCases} with linked cases`,
    )
    .join('\n');
}

function formatConcentration(demand) {
  const c = demand.concentration;
  if (c.topArticle === null) {
    return '- No article carries a linked support case in the current corpus.';
  }
  const lines = [
    `- Largest article: [${c.topArticle.title}](${c.topArticle.url}) — ${formatCases(c.topArticle.casesAttributed)} (raw ${c.topArticle.casesRaw}), tagged to ${c.topArticle.productCount} product${c.topArticle.productCount === 1 ? '' : 's'}`,
    `- Share of raw case weight: ${formatPercent(c.topShareRaw)}; share of attributed weight: ${formatPercent(c.topShareAttributed)}`,
  ];
  if (c.warned) {
    lines.push(
      `- WARNING: a single article supplies more than ${formatPercent(CONCENTRATION_WARNING_SHARE)} of raw case weight. Treat corpus-level case totals as one article's reach, not as demand for every theme it touches.`,
    );
  }
  return lines.join('\n');
}

function formatKcs(kcs) {
  const states = kcs.corpus.map((item) => `${item.value} ${item.count}`).join(', ');
  const lines = [`- Corpus KCS state: ${states || 'unknown'}`];
  const candidates = kcs.refreshCandidates;
  if (candidates.length === 0) {
    lines.push(`- No article with linked cases has gone unedited for more than ${kcs.staleAfterDays} days.`);
    return lines.join('\n');
  }
  lines.push(
    `- Refresh candidates (linked cases, last edited more than ${kcs.staleAfterDays} days ago): ${candidates.length}`,
  );
  lines.push('');
  for (const item of candidates) {
    lines.push(
      `- [${item.title}](${item.url}) — ${formatCases(item.casesAttributed)}, last edited ${item.lastModifiedDate} (${item.daysSinceModified} days), ${item.kcsState}`,
    );
  }
  return lines.join('\n');
}

function formatMovement(movement) {
  const baseline = movement.baseline;
  const lines = [
    `- Baseline window: ${baseline.window.start} to ${baseline.window.end} (${baseline.window.days} days, ${baseline.articleCount} articles)`,
    movement.corpusRateRatio === null
      ? '- Corpus publication rate: not comparable (no baseline articles).'
      : `- Corpus publication rate: ${movement.corpusRateRatio}x the baseline. Themes are classified on share, so a corpus-wide shift does not read as a theme trend.`,
    `- A theme needs at least ${baseline.minObservations} articles in both windows before its movement is classified; below that it reads \`insufficient\`.`,
  ];
  if (movement.themes === null) {
    lines.push('- No taxonomy applied; movement is not computed.');
    return lines.join('\n');
  }
  lines.push('');
  for (const item of movement.themes) {
    const unclassified = item.class === 'insufficient';
    const rate = item.ratio === null || unclassified ? 'n/a' : `${item.ratio}x`;
    const share = item.shareRatio === null || unclassified ? 'n/a' : `${item.shareRatio}x`;
    lines.push(
      `- ${item.theme}: recent ${item.recentCount}, baseline ${item.baselineCount}, rate ${rate}, share ${share}, ${item.class}`,
    );
  }
  return lines.join('\n');
}

function formatTerms(emergentTerms) {
  const render = (rows, withBaselineLength) =>
    rows.length === 0
      ? '- none'
      : rows
          .map((row) => {
            const stem = `- ${row.term}: ${row.recentArticles} recent article${row.recentArticles === 1 ? '' : 's'}`;
            return withBaselineLength
              ? `${stem}, ${row.baselineArticles} in a baseline ${row.baselineWindowRatio}x as long`
              : `${stem} (baseline ${row.baselineArticles})`;
          })
          .join('\n');
  return `### New terms

${render(emergentTerms.newTerms, false)}

### Rising terms

${render(emergentTerms.risingTerms, true)}`;
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
  '- Linked support-case totals are article-level caseCount_365 values summed across matching articles; they are not unique cases.';

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
  lines.push(
    '- The demand view weights the whole corpus by `caseCount_365`, a fixed trailing-365-day count published by Red Hat. It cannot be re-windowed, so a quarterly case-volume answer is not derivable from KB data.',
  );
  lines.push(
    '- Attributed cases divide each article\'s `caseCount_365` by the number of products it is tagged to; single-product cases exclude multi-product articles entirely.',
  );
  if (report.demand.concentration.warned) {
    lines.push(
      '- One article dominates the corpus case weight; see Corpus concentration before quoting any case total.',
    );
  }
  return lines.join('\n');
}

function formatWindowCaveat(report) {
  const recent = report.recent.window;
  const comparison = report.comparison.window;
  const nested = recent.start >= comparison.start && recent.end <= comparison.end;
  if (!nested) {
    return '- The recent and comparison windows are not nested; use per-day rates and window shares rather than raw counts alone.';
  }

  const lines = [
    '- The recent window is a subset of the comparison window; use per-day rates and shares rather than raw counts alone.',
  ];
  if (recent.end < comparison.end) {
    const gapStart = addDaysIso(recent.end, 1);
    const gapDays = daysBetweenInclusive(gapStart, comparison.end);
    lines.push(
      `- The recent window ends on ${recent.end} but the comparison window runs to ${comparison.end}: ${gapStart} to ${comparison.end} (${gapDays} days) counts toward the comparison total while sitting in neither the recent window nor the movement baseline. Pass \`--comparison-until ${recent.end}\` to align them.`,
    );
  }
  return lines.join('\n');
}

export function renderMarkdown(report) {
  const recent = report.recent;
  const comparison = report.comparison;
  const demand = report.demand;
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

## Demand (trailing 365 days, case-weighted)

- Basis: ${demand.basis}
- Articles with linked cases: ${demand.articlesWithCases} of ${demand.articleCount}
- Attributed cases: ${demand.casesAttributed} (raw ${demand.casesRaw})
- Theme signals:

${formatDemandThemes(demand.themes)}

## Corpus concentration

${formatConcentration(demand)}

## KCS health and refresh candidates

${formatKcs(report.kcs)}

## Theme movement (recent vs prior baseline)

${formatMovement(report.movement)}

## Recent categories

${formatCountList(recent.categories)}

## Comparison categories

${formatCountList(comparison.categories)}

## Recent tags

${formatCountList(recent.tags)}

## Comparison tags

${formatCountList(comparison.tags)}

## Recent components

${formatCountList(recent.componentsNormalized)}

## Comparison components

${formatCountList(comparison.componentsNormalized)}

${themeSections}## Emerging vocabulary

${formatTerms(report.emergentTerms)}

${articleHeading}

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
