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
  detectLayoutKind,
  inferKindFromRepo,
  isCoreWorkspaceToken,
  matchAlertManifest,
  parseWorkspaceInput,
  splitWorkspaceArgs,
} from './repo-layout.js';
import { identifyWhyRoot } from './yarn-why-roots.js';

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

  it('rejects plugins-monorepo workspace names', () => {
    assert.throws(
      () => parseWorkspaceInput(LAYOUT_RHDH_CORE, 'homepage'),
      /no workspaces\/homepage/,
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

  it('includes rhdh product manifests and excludes e2e/.ci', () => {
    assert.equal(matchAlertManifest(coreProduct, 'yarn.lock'), true);
    assert.equal(matchAlertManifest(coreProduct, 'package.json'), true);
    assert.equal(
      matchAlertManifest(coreProduct, 'packages/app/package.json'),
      true,
    );
    assert.equal(
      matchAlertManifest(coreProduct, 'plugins/scalprum-backend/package.json'),
      true,
    );
    assert.equal(matchAlertManifest(coreProduct, 'e2e-tests/yarn.lock'), false);
    assert.equal(matchAlertManifest(coreProduct, '.ci/yarn.lock'), false);
    assert.equal(
      matchAlertManifest(coreProduct, 'workspaces/homepage/yarn.lock'),
      false,
    );
  });

  it('keeps plugins-monorepo prefix matching', () => {
    assert.equal(
      matchAlertManifest(plugins, 'workspaces/homepage/yarn.lock'),
      true,
    );
    assert.equal(matchAlertManifest(plugins, 'yarn.lock'), false);
    assert.equal(
      matchAlertManifest(plugins, 'workspaces/boost/yarn.lock'),
      false,
    );
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
        LAYOUT_RHDH_CORE,
        'packages/backend/package.json',
        'runtime',
      ),
      'CORE_PROD',
    );
    assert.equal(
      classifyManifest(
        LAYOUT_RHDH_CORE,
        'packages/app/package.json',
        'development',
      ),
      'CORE_DEV',
    );
    assert.equal(
      classifyManifest(
        LAYOUT_RHDH_CORE,
        'plugins/scalprum-backend/package.json',
        'runtime',
      ),
      'PLUGIN_PROD',
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
    assert.deepEqual(identifyWhyRoot(coreLines[2], LAYOUT_RHDH_CORE), {
      kind: 'core',
      id: 'app-next',
    });
    assert.deepEqual(identifyWhyRoot(coreLines[3], LAYOUT_RHDH_CORE), {
      kind: 'core',
      id: 'plugin-utils',
    });
    assert.deepEqual(identifyWhyRoot(coreLines[4], LAYOUT_RHDH_CORE), {
      kind: 'plugin',
      id: 'scalprum-backend',
    });
    assert.deepEqual(identifyWhyRoot(coreLines[5], LAYOUT_RHDH_CORE), {
      kind: 'workspace',
      id: 'workspace-root',
    });
  });

  it('keeps plugins-monorepo app/backend as runner', () => {
    assert.deepEqual(identifyWhyRoot(coreLines[0], LAYOUT_PLUGINS), {
      kind: 'runner',
      id: 'app',
    });
    assert.deepEqual(identifyWhyRoot(coreLines[1], LAYOUT_PLUGINS), {
      kind: 'runner',
      id: 'backend',
    });
    assert.deepEqual(
      identifyWhyRoot(
        '├─ app-legacy@workspace:packages/app-legacy',
        LAYOUT_PLUGINS,
      ),
      { kind: 'runner', id: 'app-legacy' },
    );
  });
});
