/*
 * Copyright Red Hat, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  LAYOUT_PLUGINS,
  LAYOUT_RHDH_CORE,
  classifyManifest,
  defaultBumpBranch,
  detectLayoutKind,
  filterAlertsForPackageDiscovery,
  inferKindFromRepo,
  isCoreWorkspaceToken,
  matchAlertManifest,
  parseWorkspaceInput,
  resolveDedupe,
  splitWorkspaceArgs,
} from './repo-layout.js';
import { prTitle } from './format-bump-pr.js';
import { wantsDualLockfileBump } from './release-1.10-dual-lockfile.js';
import { identifyWhyRoot } from './yarn-why-roots.js';

describe('resolveDedupe', () => {
  it('defaults to dedupe on plugins monorepos and skip on rhdh-core', () => {
    assert.equal(resolveDedupe(LAYOUT_PLUGINS), true);
    assert.equal(resolveDedupe(LAYOUT_RHDH_CORE), false);
  });

  it('lets explicit --dedupe / --no-dedupe override the layout default', () => {
    assert.equal(resolveDedupe(LAYOUT_RHDH_CORE, { wantDedupe: true }), true);
    assert.equal(resolveDedupe(LAYOUT_PLUGINS, { noDedupe: true }), false);
  });

  it('rejects both --dedupe and --no-dedupe', () => {
    assert.throws(
      () => resolveDedupe(LAYOUT_PLUGINS, { wantDedupe: true, noDedupe: true }),
      /either --dedupe or --no-dedupe/,
    );
  });
});

describe('inferKindFromRepo', () => {
  it('maps rhdh to core and plugin repos to plugins-monorepo', () => {
    assert.equal(inferKindFromRepo('redhat-developer/rhdh'), LAYOUT_RHDH_CORE);
    assert.equal(inferKindFromRepo('kim-tsao/rhdh'), LAYOUT_RHDH_CORE);
    assert.equal(
      inferKindFromRepo('redhat-developer/rhdh-plugins'),
      LAYOUT_PLUGINS,
    );
    assert.equal(
      inferKindFromRepo('redhat-developer/community-plugins'),
      LAYOUT_PLUGINS,
    );
    assert.equal(inferKindFromRepo('redhat-developer/rhdh-operator'), null);
  });
});

describe('detectLayoutKind', () => {
  it('detects the local rhdh core checkout when present', () => {
    const kind = detectLayoutKind('/Users/ktsao/RHDH/repos/RHDH/main/rhdh');
    if (kind !== null) {
      assert.equal(kind, LAYOUT_RHDH_CORE);
    }
  });
});

describe('rhdh-core workspace tokens', () => {
  it('treats rhdh / . / root as the product lockfile', () => {
    for (const token of ['rhdh', '.', 'root', '']) {
      const parsed = parseWorkspaceInput(LAYOUT_RHDH_CORE, token);
      assert.equal(parsed.workspace, 'rhdh');
      assert.equal(parsed.scope, 'product');
      assert.equal(parsed.lockfileRel, 'yarn.lock');
      assert.equal(parsed.exactManifest, null);
    }
  });

  it('does not treat a package name as a workspace token', () => {
    assert.equal(isCoreWorkspaceToken('lodash'), false);
    assert.equal(isCoreWorkspaceToken('@types/node'), false);
    const split = splitWorkspaceArgs(LAYOUT_RHDH_CORE, ['lodash', 'qs']);
    assert.equal(split.workspaceInput, 'rhdh');
    assert.deepEqual(split.packages, ['lodash', 'qs']);
  });

  it('rejects plugins-monorepo workspace names and dynamic-plugins token', () => {
    assert.throws(
      () => parseWorkspaceInput(LAYOUT_RHDH_CORE, 'homepage'),
      /no workspaces\/homepage/,
    );
    assert.equal(isCoreWorkspaceToken('dynamic-plugins'), false);
    assert.throws(
      () => parseWorkspaceInput(LAYOUT_RHDH_CORE, 'dynamic-plugins'),
      /no workspaces\/dynamic-plugins/,
    );
  });
});

describe('defaultBumpBranch / prTitle / dual-lockfile gate', () => {
  it('suffixes release bases onto bump branch names', () => {
    assert.equal(defaultBumpBranch('rhdh'), 'chore/rhdh-cve-bumps');
    assert.equal(
      defaultBumpBranch('rhdh', 'release-1.10'),
      'chore/rhdh-cve-bumps-release-1.10',
    );
  });

  it('prefixes release bases onto PR titles', () => {
    assert.equal(
      prTitle('rhdh', LAYOUT_RHDH_CORE, 'release-1.10'),
      '[release-1.10] fix(deps): bump yarn.lock packages for Dependabot CVEs',
    );
  });

  it('gates dual lockfile to release-1.10 core only', () => {
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
        base: 'release-2.1',
      }),
      false,
    );
  });
});

describe('matchAlertManifest', () => {
  const coreProduct = {
    kind: LAYOUT_RHDH_CORE,
    workspace: 'rhdh',
    scope: 'product',
    exactManifest: null,
    alertPrefix: null,
  };
  const plugins = {
    kind: LAYOUT_PLUGINS,
    workspace: 'homepage',
    scope: 'workspace',
    exactManifest: null,
    alertPrefix: 'workspaces/homepage/',
  };

  it('includes rhdh product manifests and excludes e2e/.ci/dynamic-plugins', () => {
    assert.equal(matchAlertManifest(coreProduct, 'yarn.lock'), true);
    assert.equal(matchAlertManifest(coreProduct, 'package.json'), true);
    assert.equal(
      matchAlertManifest(coreProduct, 'packages/app/package.json'),
      true,
    );
    assert.equal(matchAlertManifest(coreProduct, 'e2e-tests/yarn.lock'), false);
    assert.equal(matchAlertManifest(coreProduct, '.ci/yarn.lock'), false);
    assert.equal(
      matchAlertManifest(coreProduct, 'dynamic-plugins/yarn.lock'),
      false,
    );
  });

  it('dual discovery can include dynamic-plugins without a token', () => {
    const alerts = [
      {
        dependency: {
          package: { name: 'adm-zip' },
          manifest_path: 'dynamic-plugins/yarn.lock',
        },
      },
    ];
    assert.equal(
      filterAlertsForPackageDiscovery(alerts, coreProduct, {
        dualLockfile: false,
      }).length,
      0,
    );
    assert.equal(
      filterAlertsForPackageDiscovery(alerts, coreProduct, {
        dualLockfile: true,
      }).length,
      1,
    );
  });

  it('keeps plugins-monorepo prefix matching', () => {
    assert.equal(
      matchAlertManifest(plugins, 'workspaces/homepage/yarn.lock'),
      true,
    );
    assert.equal(matchAlertManifest(plugins, 'yarn.lock'), false);
  });
});

describe('classifyManifest', () => {
  it('labels rhdh packages/app as CORE_PROD, never RUNNER', () => {
    assert.equal(
      classifyManifest(
        LAYOUT_RHDH_CORE,
        'packages/app/package.json',
        'runtime',
      ),
      'CORE_PROD',
    );
    assert.equal(
      classifyManifest(
        LAYOUT_PLUGINS,
        'workspaces/homepage/packages/app/package.json',
        'runtime',
      ),
      'RUNNER',
    );
  });
});

describe('identifyWhyRoot', () => {
  const coreLines = [
    '├─ app@workspace:packages/app',
    '├─ backend@workspace:packages/backend',
    '├─ app-next@workspace:packages/app-next',
    '├─ @red-hat-developer-hub/plugin-utils@workspace:packages/plugin-utils',
    '├─ @internal/plugin-scalprum-backend@workspace:plugins/scalprum-backend',
    '└─ root@workspace:.',
  ];

  it('marks rhdh packages/* as core, not runner', () => {
    assert.deepEqual(identifyWhyRoot(coreLines[0], LAYOUT_RHDH_CORE), {
      kind: 'core',
      id: 'app',
    });
    assert.deepEqual(identifyWhyRoot(coreLines[1], LAYOUT_RHDH_CORE), {
      kind: 'core',
      id: 'backend',
    });
  });

  it('keeps plugins-monorepo app/backend as runner', () => {
    assert.deepEqual(identifyWhyRoot(coreLines[0], LAYOUT_PLUGINS), {
      kind: 'runner',
      id: 'app',
    });
  });
});
