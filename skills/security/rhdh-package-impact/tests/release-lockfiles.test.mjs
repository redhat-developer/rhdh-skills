import assert from 'node:assert/strict';
import { dirname, resolve } from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

const scripts = resolve(dirname(fileURLToPath(import.meta.url)), '../scripts');

const {
  LAYOUT_PLUGINS,
  LAYOUT_RHDH_CORE,
  filterAlertsForPackageDiscovery,
  isCoreWorkspaceToken,
  matchAlertManifest,
  parseWorkspaceInput,
} = await import(resolve(scripts, 'repo-layout.js'));
const { prTitle } = await import(resolve(scripts, 'format-bump-pr.js'));
const {
  DUAL_LOCKFILE_RELEASE,
  extractReleaseBase,
  wantsDualLockfileBump,
} = await import(resolve(scripts, 'release-1.10-dual-lockfile.js'));
const { leftoverVersions, versionIsPatched } = await import(
  resolve(scripts, 'cve-version-status.js')
);

function makeSemver() {
  const coerce = v => {
    const m = String(v).match(/^(\d+)\.(\d+)\.(\d+)/);
    return m ? { version: `${m[1]}.${m[2]}.${m[3]}` } : null;
  };
  const parts = v => coerce(v).version.split('.').map(Number);
  const gte = (a, b) => {
    const pa = parts(a);
    const pb = parts(b);
    for (let i = 0; i < 3; i += 1) {
      if (pa[i] > pb[i]) return true;
      if (pa[i] < pb[i]) return false;
    }
    return true;
  };
  return {
    coerce,
    gte,
    major: v => parts(v)[0],
    satisfies(v, range) {
      const m = String(range).match(/>=(\d+\.\d+\.\d+)\s+<(\d+\.\d+\.\d+)/);
      if (!m || !coerce(v)) return false;
      return gte(coerce(v).version, m[1]) && !gte(coerce(v).version, m[2]);
    },
  };
}

describe('release-1.10 dual-lockfile gate (REMOVE WHEN EOL)', () => {
  it('enables only for rhdh-core product on release-1.10', () => {
    assert.equal(DUAL_LOCKFILE_RELEASE, 'release-1.10');
    assert.equal(
      wantsDualLockfileBump({
        layoutKind: LAYOUT_RHDH_CORE,
        scope: 'product',
        base: 'release-1.10',
      }),
      true,
    );
    assert.equal(
      wantsDualLockfileBump({
        layoutKind: LAYOUT_RHDH_CORE,
        scope: 'product',
        base: 'chore/rhdh-cve-bumps-release-1.10',
      }),
      true,
    );
  });

  it('stays off for main, release-2.1, and plugins monorepos', () => {
    assert.equal(
      wantsDualLockfileBump({
        layoutKind: LAYOUT_RHDH_CORE,
        scope: 'product',
        base: 'main',
      }),
      false,
    );
    assert.equal(
      wantsDualLockfileBump({
        layoutKind: LAYOUT_RHDH_CORE,
        scope: 'product',
        base: 'release-2.1',
      }),
      false,
    );
    assert.equal(
      wantsDualLockfileBump({
        layoutKind: LAYOUT_PLUGINS,
        scope: 'workspace',
        base: 'release-1.10',
      }),
      false,
    );
  });

  it('extracts release base from Fullsend chore branches', () => {
    assert.equal(extractReleaseBase('release-1.10'), 'release-1.10');
    assert.equal(
      extractReleaseBase('chore/rhdh-cve-bumps-release-1.10'),
      'release-1.10',
    );
    assert.equal(extractReleaseBase('main'), null);
  });

  it('has no dynamic-plugins workspace token', () => {
    assert.equal(isCoreWorkspaceToken('dynamic-plugins'), false);
    assert.throws(
      () => parseWorkspaceInput(LAYOUT_RHDH_CORE, 'dynamic-plugins'),
      /no workspaces\/dynamic-plugins/,
    );
  });

  it('product discovery includes dynamic-plugins alerts only when dual', () => {
    const layout = {
      kind: LAYOUT_RHDH_CORE,
      workspace: 'rhdh',
      scope: 'product',
      exactManifest: null,
      alertPrefix: null,
    };
    const alerts = [
      { dependency: { package: { name: 'root-pkg' }, manifest_path: 'yarn.lock' } },
      {
        dependency: {
          package: { name: 'dp-pkg' },
          manifest_path: 'dynamic-plugins/yarn.lock',
        },
      },
    ];
    assert.equal(matchAlertManifest(layout, 'dynamic-plugins/yarn.lock'), false);
    assert.deepEqual(
      filterAlertsForPackageDiscovery(alerts, layout, { dualLockfile: false }).map(
        a => a.dependency.package.name,
      ),
      ['root-pkg'],
    );
    assert.deepEqual(
      filterAlertsForPackageDiscovery(alerts, layout, { dualLockfile: true }).map(
        a => a.dependency.package.name,
      ),
      ['root-pkg', 'dp-pkg'],
    );
  });
});

describe('release PR titles', () => {
  it('prefixes release-1.10 without a dynamic-plugins token title', () => {
    assert.equal(
      prTitle('rhdh', LAYOUT_RHDH_CORE, 'release-1.10'),
      '[release-1.10] fix(deps): bump yarn.lock packages for Dependabot CVEs',
    );
    assert.equal(
      prTitle('rhdh', LAYOUT_RHDH_CORE, 'main'),
      'fix(deps): bump yarn.lock packages for Dependabot CVEs',
    );
  });
});

describe('version-line awareness', () => {
  it('scores patch status by resolved version + advisory range', () => {
    const semver = makeSemver();
    const alerts = [
      { vulnerableRange: '>=5.0.0 <5.6.1', firstPatched: '5.6.1' },
    ];
    assert.equal(
      versionIsPatched(
        semver,
        '3.8.10',
        alerts[0].vulnerableRange,
        alerts[0].firstPatched,
      ).patched,
      true,
    );
    assert.deepEqual(leftoverVersions(semver, alerts, ['3.8.10']), []);
    assert.deepEqual(leftoverVersions(semver, alerts, ['5.0.0', '3.8.10']), [
      '5.0.0',
    ]);
  });
});
