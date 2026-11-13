// Unit tests for the skill's modules: the lib helpers (semver, yaml, match,
// support) and scoreAll's behavior. The scripts' stdout contracts are covered
// separately by cli-golden.test.mjs.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const testsDir = path.dirname(fileURLToPath(import.meta.url));
const skillDir = path.join(testsDir, '..');

const { classifyDelta, compareVersions, parseVersion, maxVersion, concreteVersion } = await import(
  path.join(skillDir, 'scripts/lib/semver.ts')
);
const { parseYaml, loadConfig, CONFIG_DEFAULTS } = await import(
  path.join(skillDir, 'scripts/lib/yaml.ts')
);
const { matchPattern, matchAny } = await import(path.join(skillDir, 'scripts/lib/match.ts'));
const { loadSupportData, resolveSupportLevel } = await import(
  path.join(skillDir, 'scripts/lib/support.ts')
);
const { scoreAll } = await import(path.join(skillDir, 'scripts/score.ts'));

describe('semver', () => {
  it('parses versions and rejects non-versions', () => {
    assert.deepEqual(parseVersion('1.2.3'), { major: 1, minor: 2, patch: 3, prerelease: [] });
    assert.deepEqual(parseVersion('v1.2.3-beta.1+build'), {
      major: 1,
      minor: 2,
      patch: 3,
      prerelease: ['beta', '1'],
    });
    assert.equal(parseVersion('not-a-version'), null);
  });

  it('classifies version deltas', () => {
    const cases = [
      // from, to, type, effectiveType, downgrade, prereleaseTarget
      ['4.17.20', '4.17.21', 'patch', 'patch', false, false],
      ['1.2.3', '2.0.0', 'major', 'major', false, false],
      ['1.2.3', '1.3.0', 'minor', 'minor', false, false],
      // below 1.0.0 semver promises nothing, so a minor reads as major
      ['0.5.1', '0.6.0', 'minor', 'major', false, false],
      ['0.5.1', '0.5.2', 'patch', 'minor', false, false],
      ['2.0.0', '2.0.0-beta.1', 'prerelease', 'prerelease', true, true],
      ['1.0.0-alpha', '1.0.0', 'prerelease', 'prerelease', false, false],
      ['3.1.0', '3.0.9', 'minor', 'minor', true, false],
      ['1.0.0', '1.0.0', 'same', 'same', false, false],
    ];
    for (const [from, to, type, effectiveType, downgrade, prereleaseTarget] of cases) {
      assert.deepEqual(
        classifyDelta(from, to),
        { type, effectiveType, downgrade, prereleaseTarget },
        `${from} -> ${to}`,
      );
    }
  });

  it('orders prereleases below their release', () => {
    assert.equal(compareVersions('1.0.0-alpha.1', '1.0.0-alpha.beta') < 0, true);
    assert.equal(compareVersions('1.0.0-rc.1', '1.0.0') < 0, true);
  });

  it('takes the semver max, not the lexicographic max', () => {
    assert.equal(maxVersion(['9.4.0', '10.1.0']), '10.1.0');
    assert.equal(maxVersion(['2.0.0', '2.1.2']), '2.1.2');
    assert.equal(concreteVersion('9.4.0, 10.1.0'), '10.1.0');
  });

  it('resolves a concrete version from a range, or nothing', () => {
    assert.equal(concreteVersion('^4.1.0'), '4.1.0');
    assert.equal(concreteVersion('workspace:*'), null);
    assert.equal(concreteVersion(null), null);
  });
});

describe('yaml', () => {
  it('parses the supported subset', () => {
    assert.deepEqual(
      parseYaml(`
# comment
a: 1
b: text with spaces
c:
  nested: true
  "quoted key": "quoted value"
list:
  - one
  - 2
  - "@scope/*"
flowMap: { x: 1, y: [a, b] }
empty: null
maps:
  - name: first
    value: 1
  - name: second
`),
      {
        a: 1,
        b: 'text with spaces',
        c: { nested: true, 'quoted key': 'quoted value' },
        list: ['one', 2, '@scope/*'],
        flowMap: { x: 1, y: ['a', 'b'] },
        empty: null,
        maps: [{ name: 'first', value: 1 }, { name: 'second' }],
      },
    );
  });

  it('rejects an unterminated flow collection', () => {
    assert.throws(() => parseYaml('a: [1, 2'), /flow collection/);
  });
});

describe('loadConfig', () => {
  it('falls back to defaults when there is no config', () => {
    const defaults = loadConfig(null);
    assert.equal(defaults.minAgeDays, CONFIG_DEFAULTS.minAgeDays);
    assert.match(defaults.configSource, /defaults/);
  });

  it('honors the "none" sentinel even when the cwd has a config file', () => {
    const none = loadConfig('none');
    assert.match(none.configSource, /none/);
    assert.equal(none.bands.high, CONFIG_DEFAULTS.bands.high);
  });

  it('loads the shipped example config without errors', () => {
    // The annotated example is what users copy into a target repo, so a key
    // rename that breaks it has to fail here rather than in their checkout.
    const example = loadConfig(path.join(skillDir, 'assets/dependency-risk.example.yaml'));
    assert.deepEqual(example.trustedPackages, ['@red-hat-developer-hub/*']);
    assert.equal(example.bands.high, 6);
  });
});

describe('match', () => {
  it('matches exact names and trailing-* globs without over-reaching', () => {
    assert.equal(matchPattern('@red-hat-developer-hub/foo', '@red-hat-developer-hub/*'), true);
    assert.equal(matchPattern('@red-hat-developer-hubx/foo', '@red-hat-developer-hub/*'), false);
    assert.equal(matchPattern('lodash', 'lodash'), true);
    assert.equal(matchPattern('lodash.merge', 'lodash'), false);
    assert.equal(matchAny('@backstage/core', ['x', '@backstage/*']), true);
  });
});

describe('support levels', () => {
  it('resolves shipped levels and leaves non-ecosystem packages alone', () => {
    const support = loadSupportData();
    assert.deepEqual(resolveSupportLevel('@red-hat-developer-hub/foo', support), {
      level: 'production',
      scoreAdjust: 0,
    });
    assert.equal(resolveSupportLevel('lodash', support).level, null);
    assert.equal(resolveSupportLevel('@backstage-community/plugin-anything', support).level, 'unknown');
  });
});

// --- scoreAll behavior -----------------------------------------------------

const defaults = loadConfig(null);
const baseMetrics = JSON.parse(
  fs.readFileSync(path.join(testsDir, 'fixtures/metrics-basic.json'), 'utf8'),
);
/** lodash in the fixture: a package with no risk signals of its own. */
const clean = baseMetrics.packages[0];
const majorDelta = { type: 'major', effectiveType: 'major', downgrade: false, prereleaseTarget: false };
const labelsOf = (p) => p.reasons.map((r) => r.label).join(' ');

describe('test confidence', () => {
  it('reports unknown coverage as unknown, not medium', () => {
    const scored = scoreAll({
      metrics: baseMetrics,
      codecov: { workspaces: [{ path: '.', coverage: null, confidence: 'unknown', source: 'none' }] },
      config: defaults,
    });
    assert.equal(scored.overall.testConfidence, 'unknown');
  });
});

describe('trusted packages', () => {
  it('keeps the real uncapped score when a trusted package adds an install script', () => {
    // A compromised trusted scope must never be hidden by the allowlist.
    const metrics = structuredClone(baseMetrics);
    metrics.packages = [
      { ...metrics.packages[1], name: '@red-hat-developer-hub/evil', trusted: true },
    ];
    const scored = scoreAll({ metrics, config: defaults });
    assert.equal(scored.packages[0].band, 'HIGH');
    assert.ok(scored.packages[0].flags.includes('trusted-but-security-signal'));
  });
});

describe('backstage opt-out', () => {
  it('ignores the manifest check entirely when backstage.enabled is false', () => {
    const scored = scoreAll({
      metrics: baseMetrics,
      backstage: { release: '1.39.0', results: [{ name: 'lodash', status: 'mismatch', expected: '9.9.9' }] },
      config: { ...defaults, backstage: { enabled: false } },
    });
    assert.equal(scored.backstageRelease, null);
    assert.ok(!scored.packages.some((p) => p.reasons.some((r) => r.label.includes('Backstage'))));
  });
});

describe('driver ranking', () => {
  it('names the band-driving package even when metrics order buries it', () => {
    // collect-metrics ranks direct packages first, so the package that forced
    // the band can sort behind the 5-driver cut unless drivers re-sort by score.
    const metrics = structuredClone(baseMetrics);
    metrics.packages = [
      ...Array.from({ length: 6 }, (_, i) => ({
        ...clean,
        name: `medium-pkg-${i}`,
        delta: majorDelta,
        osv: { fixed: [], introduced: [] },
      })),
      {
        ...clean,
        name: 'buried-transitive',
        direct: false,
        delta: majorDelta,
        osv: { fixed: [], introduced: ['GHSA-dead-beef-0000'] },
      },
    ];
    metrics.counts = { ...baseMetrics.counts, total: 7, direct: 6, major: 7, patch: 0 };

    const scored = scoreAll({ metrics, config: defaults });
    assert.equal(scored.overall.band, 'HIGH');
    assert.equal(scored.overall.drivers.length, 5);
    assert.match(scored.overall.drivers[0], /^buried-transitive:/);
    assert.match(scored.overall.recommendation, /buried-transitive/);
  });
});

describe('analysis tiers', () => {
  const lightIntro = structuredClone(baseMetrics);
  lightIntro.packages = [
    {
      ...clean,
      name: 'light-tier-regression',
      direct: false,
      analyzed: 'light',
      // the light tier has no downloads/publisher/license data, but OSV is populated
      weeklyDownloads: null,
      installScriptAdded: null,
      publisherChanged: null,
      licenseChange: null,
      osv: { fixed: ['GHSA-old-fixed-0000'], introduced: ['GHSA-new-intro-0000'] },
    },
  ];
  lightIntro.counts = { ...baseMetrics.counts, total: 1, direct: 0, major: 0, patch: 1 };
  lightIntro.skipped = { removedPackages: 0, lightAnalysis: 1, notAnalyzed: 0 };

  it('forces HIGH for an introduced vulnerability on a light-tier package', () => {
    // Catching a supply-chain regression must not depend on where the package
    // happened to sort against maxPackagesDetailed.
    const scored = scoreAll({ metrics: lightIntro, config: defaults });
    assert.equal(scored.packages[0].band, 'HIGH');
    assert.ok(scored.packages[0].flags.includes('forced-high'));
    assert.equal(scored.overall.band, 'HIGH');
  });

  it('does not charge the light tier for data it never queried', () => {
    const scored = scoreAll({ metrics: lightIntro, config: defaults });
    assert.ok(!scored.packages[0].dataGaps.includes('weekly downloads unknown'));
  });

  it('still reports a null OSV result as a real gap at the light tier', () => {
    const metrics = structuredClone(lightIntro);
    metrics.packages = [{ ...metrics.packages[0], osv: null }];
    const scored = scoreAll({ metrics, config: defaults });
    assert.ok(scored.packages[0].dataGaps.includes('vulnerability data unavailable'));
  });
});

describe('introduced-vulnerability severity gating', () => {
  const withIntroduced = (id, severity) => {
    const metrics = structuredClone(baseMetrics);
    metrics.packages = [
      {
        ...clean,
        name: 'pkg-under-test',
        osv: {
          fixed: [],
          introduced: [id],
          ...(severity === null ? {} : { severities: { [id]: severity } }),
        },
      },
    ];
    metrics.counts = { ...baseMetrics.counts, total: 1, direct: 1, major: 0, patch: 1 };
    return scoreAll({ metrics, config: defaults }).packages[0];
  };

  for (const severity of ['HIGH', 'CRITICAL']) {
    it(`forces HIGH for an introduced ${severity} vulnerability`, () => {
      const p = withIntroduced('GHSA-sig-0000', severity);
      assert.equal(p.band, 'HIGH');
      assert.ok(p.flags.includes('forced-high'));
      assert.match(labelsOf(p), /INTRODUCES known vulnerabilities/);
    });
  }

  for (const severity of ['LOW', 'MODERATE']) {
    it(`drops an introduced ${severity} vulnerability entirely`, () => {
      // These dominate CVE churn on a large lockfile refresh; letting one force
      // HIGH would block merges over advisories nobody would act on.
      const p = withIntroduced('GHSA-minor-0000', severity);
      assert.notEqual(p.band, 'HIGH');
      assert.ok(!p.flags.includes('forced-high'));
      assert.equal(p.score, 0);
      assert.equal(p.reasons.length, 0);
      assert.ok(!/INTRODUCES known vulnerabilities/.test(labelsOf(p)));
    });
  }

  it('names only the significant ids when severities are mixed', () => {
    const metrics = structuredClone(baseMetrics);
    metrics.packages = [
      {
        ...clean,
        name: 'pkg-mixed',
        osv: {
          fixed: [],
          introduced: ['GHSA-crit-2222', 'GHSA-minor-2222'],
          severities: { 'GHSA-crit-2222': 'CRITICAL', 'GHSA-minor-2222': 'LOW' },
        },
      },
    ];
    metrics.counts = { ...baseMetrics.counts, total: 1, direct: 1, major: 0, patch: 1 };

    const p = scoreAll({ metrics, config: defaults }).packages[0];
    assert.equal(p.band, 'HIGH');
    assert.match(labelsOf(p), /GHSA-crit-2222 \(CRITICAL\)/);
    assert.ok(!/GHSA-minor-2222/.test(labelsOf(p)), 'low-severity id must not appear anywhere');
  });

  it('fails closed when severity could not be resolved', () => {
    // A failed lookup must never silently downgrade a real regression.
    const p = withIntroduced('GHSA-unknown-0000', null);
    assert.equal(p.band, 'HIGH');
    assert.ok(p.flags.includes('forced-high'));
    assert.match(labelsOf(p), /severity unknown/);
  });
});
