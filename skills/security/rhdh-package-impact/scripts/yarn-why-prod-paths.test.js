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

import { collectPluginProdPaths } from './yarn-why-prod-paths.js';

const WHY = `
├─ @red-hat-developer-hub/backstage-plugin-orchestrator-backend@workspace:plugins/orchestrator-backend
│  ├─ @backstage/plugin-scaffolder-backend@npm:3.2.0 (via npm:^3.2.0)
│  │  └─ @backstage/backend-openapi-utils@npm:0.6.7 (via npm:^0.6.7)
│  │     └─ mockttp@npm:3.15.4 (via npm:^3.13.0)
│  │        └─ pac-proxy-agent@npm:7.1.0 (via npm:^7.0.0)
│  │           └─ basic-ftp@npm:5.0.5 (via npm:^5.0.0)
│  └─ some-dev-tool@npm:1.0.0 (via npm:^1.0.0)
│     └─ basic-ftp@npm:5.0.5 (via npm:^5.0.0)
├─ @red-hat-developer-hub/backstage-plugin-orchestrator-backend@workspace:plugins/orchestrator-backend
│  └─ real-prod-dep@npm:2.0.0 (via npm:^2.0.0)
│     └─ basic-ftp@npm:5.0.5 (via npm:^5.0.0)
`.trim();

describe('collectPluginProdPaths', () => {
  it('keeps only PLUGIN_PROD first-hop chains to the leaf', () => {
    const paths = collectPluginProdPaths({
      yarnWhyOutput: WHY,
      targetPackage: 'basic-ftp',
      runtimeDepsByPlugin: {
        'orchestrator-backend': new Set([
          '@backstage/plugin-scaffolder-backend',
          'real-prod-dep',
        ]),
      },
    });

    assert.equal(paths.length, 2);
    assert.deepEqual(paths[0].path, [
      '@red-hat-developer-hub/backstage-plugin-orchestrator-backend',
      '@backstage/plugin-scaffolder-backend',
      '@backstage/backend-openapi-utils',
      'mockttp',
      'pac-proxy-agent',
      'basic-ftp',
    ]);
    assert.equal(paths[0].firstHop, '@backstage/plugin-scaffolder-backend');
    assert.deepEqual(paths[1].path, [
      '@red-hat-developer-hub/backstage-plugin-orchestrator-backend',
      'real-prod-dep',
      'basic-ftp',
    ]);
  });

  it('ignores chains whose first hop is not a runtime dependency', () => {
    const paths = collectPluginProdPaths({
      yarnWhyOutput: WHY,
      targetPackage: 'basic-ftp',
      runtimeDepsByPlugin: {
        'orchestrator-backend': new Set([
          '@backstage/plugin-scaffolder-backend',
        ]),
      },
    });

    assert.equal(paths.length, 1);
    assert.ok(paths[0].path.includes('mockttp'));
    assert.ok(!paths.some(p => p.firstHop === 'some-dev-tool'));
    assert.ok(!paths.some(p => p.firstHop === 'real-prod-dep'));
  });

});
