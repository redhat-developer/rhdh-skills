import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { describe, it } from 'node:test';

import {
  ABSTRACT_LIMIT,
  DEFAULT_COMPARISON_DAYS,
  DEFAULT_RECENT_DAYS,
  buildQuery,
  fetchKbDocs,
  isInWindow,
  parseArgs,
  renderMarkdown,
  resolveWindows,
  summarize,
  themeHints,
} from '../scripts/analyze-kb.mjs';

describe('parseArgs defaults', () => {
  it('uses RHDH, Markdown, 90 days, and 365 days', () => {
    const args = parseArgs(['--as-of', '2026-10-30']);
    assert.equal(args.product, 'Red Hat Developer Hub');
    assert.equal(args.format, 'markdown');
    assert.equal(args.recentDays, undefined);
    assert.equal(args.comparisonDays, undefined);
    assert.equal(DEFAULT_RECENT_DAYS, 90);
    assert.equal(DEFAULT_COMPARISON_DAYS, 365);
  });

  it('accepts JSON output', () => {
    assert.equal(parseArgs(['--as-of', '2026-10-30', '--format', 'json']).format, 'json');
  });
});

describe('resolveWindows', () => {
  it('creates inclusive rolling windows', () => {
    const args = parseArgs(['--as-of', '2026-10-30']);
    const windows = resolveWindows(args);
    assert.deepEqual(windows.recent, {
      start: '2026-08-02',
      end: '2026-10-30',
      days: 90,
    });
    assert.deepEqual(windows.comparison, {
      start: '2025-10-31',
      end: '2026-10-30',
      days: 365,
    });
  });

  it('supports custom day lengths', () => {
    const args = parseArgs([
      '--as-of',
      '2026-10-30',
      '--recent-days',
      '30',
      '--comparison-days',
      '180',
    ]);
    const windows = resolveWindows(args);
    assert.equal(windows.recent.start, '2026-10-01');
    assert.equal(windows.recent.days, 30);
    assert.equal(windows.comparison.start, '2026-05-04');
    assert.equal(windows.comparison.days, 180);
  });

  it('supports explicit calendar windows', () => {
    const args = parseArgs([
      '--as-of',
      '2026-10-30',
      '--recent-since',
      '2026-07-01',
      '--recent-until',
      '2026-09-30',
      '--comparison-since',
      '2025-01-01',
      '--comparison-until',
      '2025-12-31',
    ]);
    const windows = resolveWindows(args);
    assert.deepEqual(windows.recent, {
      start: '2026-07-01',
      end: '2026-09-30',
      days: 92,
    });
    assert.deepEqual(windows.comparison, {
      start: '2025-01-01',
      end: '2025-12-31',
      days: 365,
    });
  });

  it('rejects conflicting day and date options', () => {
    assert.throws(
      () => parseArgs(['--as-of', '2026-10-30', '--recent-days', '30', '--recent-since', '2026-07-01']),
      /cannot be combined/,
    );
    assert.throws(
      () => parseArgs(['--as-of', '2026-10-30', '--comparison-days', '365', '--comparison-since', '2025-01-01']),
      /cannot be combined/,
    );
  });

  it('requires a start when an end is supplied', () => {
    assert.throws(
      () => parseArgs(['--as-of', '2026-10-30', '--recent-until', '2026-09-30']),
      /requires/,
    );
  });
});

describe('buildQuery', () => {
  it('encodes the product filter and Solr local params', () => {
    const url = buildQuery('Red Hat Developer Hub', 20, 100);
    assert.equal(url.origin, 'https://access.redhat.com');
    assert.equal(url.pathname, '/hydra/rest/search/platform/kbase');
    assert.equal(url.searchParams.get('start'), '20');
    assert.equal(url.searchParams.get('rows'), '100');
    assert.ok(url.searchParams.getAll('fq').includes('-id:Other'));
    assert.ok(url.searchParams.getAll('fq').includes('documentKind:(Solution Article)'));
    assert.ok(
      url.searchParams
        .getAll('fq')
        .includes('{!tag=productFilter}standard_product:"Red Hat Developer Hub"'),
    );
    assert.ok(url.searchParams.getAll('facet.field').includes('{!ex=productFilter}standard_product'));
  });
});

describe('analysis', () => {
  const docs = [
    {
      id: '1',
      title: 'GitHub login fails after upgrade',
      view_uri: 'https://access.redhat.com/solutions/1',
      createdDate: '2026-10-30T10:00:00Z',
      category: ['Troubleshoot'],
      component: ['authentication'],
      tag: ['authentication', 'rhdh'],
      caseCount_365: 7,
    },
    {
      id: '2',
      title: 'Dynamic plugin installation fails',
      view_uri: 'https://access.redhat.com/solutions/2',
      createdDate: '2026-08-02T10:00:00Z',
      category: ['Configure'],
      component: ['rhdh'],
      tag: ['rhdh_configuration'],
      caseCount_365: 3,
    },
    {
      id: '3',
      title: 'Older Keycloak login issue',
      view_uri: 'https://access.redhat.com/solutions/3',
      createdDate: '2025-10-31T10:00:00Z',
      category: ['Troubleshoot'],
      component: ['keycloak'],
      tag: ['authentication'],
      caseCount_365: 2,
    },
  ];

  it('includes both window boundaries', () => {
    const args = parseArgs(['--as-of', '2026-10-30']);
    const windows = resolveWindows(args);
    assert.equal(isInWindow(docs[0], windows.recent), true);
    assert.equal(isInWindow(docs[1], windows.recent), true);
    assert.equal(isInWindow(docs[2], windows.comparison), true);
  });

  it('emits non-exclusive theme hints and per-theme case totals', () => {
    assert.ok(themeHints(docs[0]).includes('upgrade-plugin-reliability'));
    assert.ok(themeHints(docs[0]).includes('authentication-identity'));
    assert.ok(themeHints(docs[1]).includes('upgrade-plugin-reliability'));

    const report = summarize({ docs, numFound: docs.length, truncated: false }, parseArgs(['--as-of', '2026-10-30']));
    const upgrade = report.recent.themes.find((theme) => theme.theme === 'upgrade-plugin-reliability');
    assert.equal(upgrade.count, 2);
    assert.equal(upgrade.caseCount365, 10);
  });

  it('does not match unrelated words inside theme stems', () => {
    assert.deepEqual(themeHints({ title: 'How to change the RHDH logo' }), ['configuration-ui']);
    assert.deepEqual(themeHints({ title: 'Authoring TechDocs' }), []);
    assert.deepEqual(themeHints({ title: 'Accessibility statement for RHDH' }), []);
  });

  it('matches plural and derived theme forms', () => {
    assert.ok(themeHints({ title: 'Upgrades fail' }).includes('upgrade-plugin-reliability'));
    assert.ok(themeHints({ title: 'PostgreSQL 16' }).includes('catalog-database-scale'));
    assert.ok(themeHints({ title: 'modules' }).includes('upgrade-plugin-reliability'));
    assert.ok(themeHints({ title: 'operators' }).includes('operator-openshift-deployment'));
    assert.ok(themeHints({ title: 'replicas' }).includes('catalog-database-scale'));
    assert.ok(themeHints({ title: 'namespaces' }).includes('operator-openshift-deployment'));
    assert.ok(themeHints({ title: 'configs' }).includes('configuration-ui'));
    assert.ok(themeHints({ title: 'scales' }).includes('catalog-database-scale'));
    assert.ok(themeHints({ title: 'autoscaling' }).includes('catalog-database-scale'));

    const incompatible = themeHints({ title: 'incompatible plugin' });
    assert.ok(incompatible.includes('upgrade-plugin-reliability'));
    assert.ok(incompatible.includes('support-version-clarity'));
  });

  it('accepts scalar metadata fields without counting characters', () => {
    const doc = {
      id: 'scalar',
      title: 'GitHub login fails after upgrade',
      createdDate: '2026-10-30T10:00:00Z',
      category: 'Troubleshoot',
      component: 'authentication',
      tag: 'rhdh',
      caseCount_365: 4,
    };
    const report = summarize({ docs: [doc], numFound: 1, truncated: false }, parseArgs(['--as-of', '2026-10-30']));
    assert.deepEqual(report.recent.categories, [{ value: 'Troubleshoot', count: 1 }]);
    assert.deepEqual(report.recent.components, [{ value: 'authentication', count: 1 }]);
    assert.deepEqual(report.recent.tags, [{ value: 'rhdh', count: 1 }]);
    assert.match(renderMarkdown(report), /^- Recent articles: 1$/m);
    assert.ok(renderMarkdown(report).includes('1 article,'));
  });

  it('keeps the first reported numFound when a later page omits it', async () => {
    const originalFetch = globalThis.fetch;
    const pages = [
      { response: { numFound: 3, docs: [{ id: '1', title: 'One' }] } },
      { response: { docs: [{ id: '2', title: 'Two' }] } },
      { response: { docs: [] } },
    ];
    let call = 0;
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => pages[Math.min(call++, pages.length - 1)],
    });
    try {
      const result = await fetchKbDocs('Red Hat Developer Hub');
      assert.equal(result.docs.length, 2);
      assert.equal(result.numFound, 3);
      assert.equal(result.truncated, true);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('falls back to fetched count when the API omits numFound', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({ response: { docs: [{ id: '1', title: 'Example' }] } }),
    });
    try {
      const result = await fetchKbDocs('Red Hat Developer Hub');
      assert.equal(result.numFound, 1);
      assert.equal(result.truncated, false);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('reports numFound as a floor when results are capped', () => {
    const args = parseArgs(['--as-of', '2026-10-30']);
    const report = summarize({ docs: docs.slice(0, 1), numFound: 2, truncated: true }, args);
    assert.equal(report.allTime.articleCount, 2);
    assert.equal(report.allTime.fetchedArticles, 1);
    assert.equal(report.allTime.truncated, true);
    const markdown = renderMarkdown(report);
    assert.ok(markdown.includes('≥ 2 (capped; fetched 1)'));
    assert.ok(!markdown.includes('unknown to unknown'));
  });

  it('summarizes recent and comparison windows', () => {
    const args = parseArgs(['--as-of', '2026-10-30']);
    const report = summarize({ docs, numFound: docs.length, truncated: false }, args);
    assert.equal(report.recent.articleCount, 2);
    assert.equal(report.comparison.articleCount, 3);
    assert.equal(report.allTime.articleCount, 3);
    assert.equal(report.allTime.firstCreated, '2025-10-31');
    assert.equal(report.allTime.lastCreated, '2026-10-30');
    assert.ok(renderMarkdown(report).includes('All-time articles: 3 ('));
    assert.deepEqual(
      report.recent.categories.map((item) => item.value).sort(),
      ['Configure', 'Troubleshoot'],
    );
  });

  it('labels the high-signal article list when it is truncated', () => {
    const manyDocs = Array.from({ length: 16 }, (_, index) => ({
      id: String(index + 1),
      title: `Upgrades fail ${index + 1}`,
      createdDate: '2026-10-30T10:00:00Z',
      caseCount_365: index,
    }));
    const args = parseArgs(['--as-of', '2026-10-30']);
    const markdown = renderMarkdown(
      summarize({ docs: manyDocs, numFound: manyDocs.length, truncated: false }, args),
    );
    assert.ok(
      markdown.includes(
        '## Most-linked recent articles (top 15 of 16 by linked support cases)',
      ),
    );
  });

  it('renders the core Markdown sections and linked citations', () => {
    const args = parseArgs(['--as-of', '2026-10-30']);
    const markdown = renderMarkdown(summarize({ docs, numFound: docs.length, truncated: false }, args));
    assert.ok(markdown.includes('# RHDH KB theme analysis'));
    assert.ok(markdown.includes('- Recent window: 2026-08-02 to 2026-10-30 (90 days)'));
    assert.ok(markdown.includes('- Comparison window: 2025-10-31 to 2026-10-30 (365 days)'));
    assert.ok(markdown.includes('## Heuristic theme signals — recent'));
    assert.ok(
      markdown.includes('[GitHub login fails after upgrade](https://access.redhat.com/solutions/1)'),
    );
    assert.ok(!markdown.includes('Product improvement:'));
    assert.ok(!markdown.includes('Documentation improvement:'));
    assert.ok(
      markdown.includes(
        '## Most-linked recent articles (top 2 of 2 by linked support cases)',
      ),
    );
    assert.ok(markdown.includes('## Caveats'));
    assert.ok(markdown.includes('The recent window is a subset of the comparison window'));
  });

  it('uses a non-nested caveat for disjoint custom windows', () => {
    const args = parseArgs([
      '--as-of',
      '2026-10-30',
      '--recent-since',
      '2026-07-01',
      '--recent-until',
      '2026-08-01',
      '--comparison-since',
      '2025-01-01',
      '--comparison-until',
      '2025-12-31',
    ]);
    const markdown = renderMarkdown(summarize({ docs: [], numFound: 0, truncated: false }, args));
    assert.ok(markdown.includes('The recent and comparison windows are not nested'));
    assert.ok(markdown.includes('- none'));
  });
});

describe('taxonomy', () => {
  const docs = [
    { id: '1', title: 'TechDocs build fails', createdDate: '2026-10-30T10:00:00Z', caseCount_365: 3 },
    { id: '2', title: 'Upgrade fails', createdDate: '2026-10-28T10:00:00Z', caseCount_365: 1 },
    { id: '3', title: 'Old TechDocs question', createdDate: '2025-11-01T10:00:00Z', caseCount_365: 2 },
  ];
  const argsFor = (...extra) => parseArgs(['--as-of', '2026-10-30', ...extra]);
  const reportFor = (...extra) =>
    summarize({ docs, numFound: docs.length, truncated: false }, argsFor(...extra));

  function writeTaxonomy(rules) {
    const directory = mkdtempSync(join(tmpdir(), 'rhdh-kb-taxonomy-'));
    const file = join(directory, 'taxonomy.json');
    writeFileSync(file, JSON.stringify(rules));
    return file;
  }

  it('uses the built-in taxonomy by default', () => {
    const report = reportFor();
    assert.equal(report.taxonomy.mode, 'built-in');
    assert.equal(report.taxonomy.themes.length, 8);
    assert.ok(report.recent.themes.length > 0);
    assert.ok(renderMarkdown(report).includes('## Heuristic theme signals — recent'));
  });

  it('skips clustering with --themes none', () => {
    const report = reportFor('--themes', 'none');
    assert.equal(report.taxonomy, null);
    assert.equal(report.recent.themes, null);
    assert.equal(report.comparison.themes, null);
    assert.equal(report.articles[0].themes, null);

    const markdown = renderMarkdown(report);
    assert.ok(markdown.includes('- Taxonomy: none (group the article list yourself)'));
    assert.ok(!markdown.includes('Heuristic theme signals'));
    assert.ok(markdown.includes('No taxonomy applied'));
  });

  it('applies a custom taxonomy file to both windows', () => {
    const file = writeTaxonomy([{ theme: 'techdocs', pattern: '\\btechdocs\\b' }]);
    const report = reportFor('--themes', file);

    assert.equal(report.taxonomy.mode, 'custom');
    assert.deepEqual(report.taxonomy.themes, ['techdocs']);
    assert.deepEqual(
      report.recent.themes.map((item) => [item.theme, item.count]),
      [['techdocs', 1]],
    );
    assert.deepEqual(
      report.comparison.themes.map((item) => [item.theme, item.count]),
      [['techdocs', 2]],
    );

    const markdown = renderMarkdown(report);
    assert.ok(markdown.includes('- Taxonomy: ' + basename(file)));
    assert.ok(markdown.includes('## Theme signals — recent'));
    assert.ok(!markdown.includes('Heuristic theme signals'));
  });

  it('rejects a taxonomy that is not a JSON array', () => {
    const file = writeTaxonomy({ theme: 'x' });
    assert.throws(() => parseArgs(['--themes', file]), /must be a non-empty JSON array/);
  });

  it('rejects a taxonomy entry with an unusable pattern', () => {
    const file = writeTaxonomy([{ theme: 'broken', pattern: '(' }]);
    assert.throws(() => parseArgs(['--themes', file]), /not a valid regular expression/);
  });

  it('rejects a taxonomy with duplicate theme names', () => {
    const file = writeTaxonomy([
      { theme: 'same', pattern: 'a' },
      { theme: 'same', pattern: 'b' },
    ]);
    assert.throws(() => parseArgs(['--themes', file]), /repeats the theme/);
  });

  it('reports a missing taxonomy file', () => {
    assert.throws(
      () => parseArgs(['--themes', join(tmpdir(), 'no-such-taxonomy.json')]),
      /Cannot read taxonomy file/,
    );
  });

  it('emits one article list carrying window membership', () => {
    const report = reportFor();
    assert.equal('articles' in report.recent, false);
    assert.equal('articles' in report.comparison, false);
    assert.equal(report.articles.length, 3);

    const byId = new Map(report.articles.map((article) => [article.id, article.windows]));
    assert.deepEqual(byId.get('1'), ['recent', 'comparison']);
    assert.deepEqual(byId.get('2'), ['recent', 'comparison']);
    assert.deepEqual(byId.get('3'), ['comparison']);
  });

  it('includes truncated abstracts only when asked', () => {
    const long = 'x'.repeat(ABSTRACT_LIMIT + 200);
    const withIssue = [{ id: '1', title: 't', createdDate: '2026-10-30', issue: [long] }];

    const without = summarize(
      { docs: withIssue, numFound: 1, truncated: false },
      argsFor(),
    );
    assert.equal('abstract' in without.articles[0], false);

    const included = summarize(
      { docs: withIssue, numFound: 1, truncated: false },
      argsFor('--include-abstracts'),
    );
    assert.equal(included.articles[0].abstract.length, ABSTRACT_LIMIT + 1);
    assert.ok(included.articles[0].abstract.endsWith('\u2026'));
  });
});

describe('report signals', () => {
  const args = parseArgs(['--as-of', '2026-10-30']);

  function writeTaxonomy(rules) {
    const directory = mkdtempSync(join(tmpdir(), 'rhdh-kb-signals-'));
    const file = join(directory, 'taxonomy.json');
    writeFileSync(file, JSON.stringify(rules));
    return file;
  }

  it('keeps out-of-window articles with empty window flags', () => {
    const docs = [
      { id: 'old', title: 'Legacy question', createdDate: '2024-05-01T10:00:00Z' },
      { id: 'new', title: 'Upgrade fails', createdDate: '2026-10-30T10:00:00Z' },
    ];
    const report = summarize({ docs, numFound: 2, truncated: false }, args);

    const legacy = report.articles.find((article) => article.id === 'old');
    assert.deepEqual(legacy.windows, []);
    assert.equal(report.articles.length, 2);
    assert.equal(report.allTime.articleCount, 2);
    assert.equal(report.recent.articleCount, 1);
  });

  it('counts articles the taxonomy leaves unmatched', () => {
    const docs = [
      { id: '1', title: 'TechDocs build fails', createdDate: '2026-10-30T10:00:00Z' },
      { id: '2', title: 'Upgrade fails', createdDate: '2026-10-28T10:00:00Z' },
      { id: '3', title: 'Old TechDocs question', createdDate: '2025-11-01T10:00:00Z' },
    ];
    const file = writeTaxonomy([{ theme: 'upgrades', pattern: '\\bupgrad\\w*' }]);
    const report = summarize(
      { docs, numFound: docs.length, truncated: false },
      parseArgs(['--as-of', '2026-10-30', '--themes', file]),
    );

    assert.equal(report.recent.unmatched, 1);
    assert.equal(report.comparison.unmatched, 2);
    const markdown = renderMarkdown(report);
    assert.ok(markdown.includes('- Recent unmatched by taxonomy: 1'));
    assert.ok(markdown.includes('- Comparison unmatched by taxonomy: 2'));
  });

  it('reports no unmatched section when clustering is off', () => {
    const report = summarize(
      { docs: [{ id: '1', title: 'x', createdDate: '2026-10-30' }], numFound: 1, truncated: false },
      parseArgs(['--as-of', '2026-10-30', '--themes', 'none']),
    );
    assert.equal(report.recent.unmatched, null);
    assert.ok(!renderMarkdown(report).includes('unmatched by taxonomy'));
  });

  it('flags a theme whose case total comes from one article', () => {
    const docs = [
      { id: 'spike', title: 'Upgrades hit a CVE', createdDate: '2026-10-01T10:00:00Z', caseCount_365: 90 },
      { id: 'small', title: 'Upgrade question', createdDate: '2026-10-02T10:00:00Z', caseCount_365: 1 },
    ];
    const file = writeTaxonomy([{ theme: 'upgrades', pattern: '\\bupgrad\\w*' }]);
    const report = summarize(
      { docs, numFound: 2, truncated: false },
      parseArgs(['--as-of', '2026-10-30', '--themes', file]),
    );

    const theme = report.recent.themes[0];
    assert.equal(theme.caseCount365, 91);
    assert.equal(theme.maxArticleCases, 90);
    assert.ok(theme.topArticleShare > 0.9);
    assert.ok(renderMarkdown(report).includes('one article supplies'));
  });

  it('does not flag a theme with a spread of case counts', () => {
    const docs = [
      { id: 'a', title: 'Upgrade one', createdDate: '2026-10-01T10:00:00Z', caseCount_365: 3 },
      { id: 'b', title: 'Upgrade two', createdDate: '2026-10-02T10:00:00Z', caseCount_365: 3 },
    ];
    const file = writeTaxonomy([{ theme: 'upgrades', pattern: '\\bupgrad\\w*' }]);
    const report = summarize(
      { docs, numFound: 2, truncated: false },
      parseArgs(['--as-of', '2026-10-30', '--themes', file]),
    );

    assert.ok(report.recent.themes[0].topArticleShare <= 0.5);
    assert.ok(!renderMarkdown(report).includes('one article supplies'));
  });
});
