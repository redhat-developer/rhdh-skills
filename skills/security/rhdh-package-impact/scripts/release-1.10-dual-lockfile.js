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

/**
 * REMOVE WHEN redhat-developer/rhdh `release-1.10` is EOL.
 *
 * On rhdh-core release-1.10 only, the same Dependabot package list used for
 * the product (root) yarn.lock may also need `yarn up -R` under
 * `dynamic-plugins/yarn.lock` (independent resolved versions). main and
 * release-2.1+ stay root-only. Plugins monorepos never use this path —
 * their Fullsend CVE schedule stays workspace×main and omits --base /
 * CVE_BASE_BRANCH. Any schedule that passes --base release-1.10 belongs
 * in the rhdh core repo, not rhdh-plugins.
 *
 * Assumption (intentional, imperfect): product / main-line Dependabot alerts
 * are treated as also applying to wrapped plugins under dynamic-plugins/,
 * even when Dependabot has not filed a matching sibling-lockfile alert.
 * That closes a patching gap; per-lockfile scoring still uses resolved
 * version + advisory range so already-safe sibling lines are not force-bumped.
 *
 * Delete this file and every import of it after 1.10 EOL.
 */

import { execFile as execFileCb } from 'child_process';
import { existsSync } from 'fs';
import { resolve as resolvePath } from 'path';
import { promisify } from 'util';

import { LAYOUT_RHDH_CORE } from './repo-layout.js';

const execFile = promisify(execFileCb);

/** Exact release train that needs the second lockfile. */
export const DUAL_LOCKFILE_RELEASE = 'release-1.10';

export const DUAL_LOCKFILE = Object.freeze({
  name: 'dynamic-plugins',
  lockfileRel: 'dynamic-plugins/yarn.lock',
  yarnCwdRel: 'dynamic-plugins',
  alertPrefix: 'dynamic-plugins/',
});

/**
 * Normalize a branch / --base value to a release train id when present.
 * `chore/rhdh-cve-bumps-release-1.10` → `release-1.10`
 * `release-1.10` → `release-1.10`
 * `main` → null
 */
export function extractReleaseBase(branchOrBase) {
  const raw = String(branchOrBase || '').trim();
  if (!raw || raw === 'HEAD' || raw === 'main' || raw === 'master') {
    return null;
  }
  if (/^release-\d+\.\d+/.test(raw)) {
    return raw.match(/^release-\d+\.\d+/)[0];
  }
  const embedded = raw.match(/release-\d+\.\d+/);
  return embedded ? embedded[0] : null;
}

/**
 * True only for rhdh-core product bumps on the release-1.10 train.
 */
export function wantsDualLockfileBump({ layoutKind, scope, base } = {}) {
  if (layoutKind !== LAYOUT_RHDH_CORE || scope !== 'product') {
    return false;
  }
  const release = extractReleaseBase(base);
  return release === DUAL_LOCKFILE_RELEASE;
}

/**
 * Sibling lockfile paths when present on disk (release-1.10 path only).
 */
export function dualLockfilePaths(repoRoot) {
  if (!repoRoot) {
    return null;
  }
  const root = resolvePath(repoRoot);
  const lockPath = resolvePath(root, DUAL_LOCKFILE.lockfileRel);
  if (!existsSync(lockPath)) {
    return null;
  }
  return {
    ...DUAL_LOCKFILE,
    lockPath,
    yarnCwd: resolvePath(root, DUAL_LOCKFILE.yarnCwdRel),
  };
}

/**
 * Product alert discovery on release-1.10 also accepts dynamic-plugins/
 * manifests so the main Dependabot package list covers both lockfiles.
 * Classification / dismiss still treat product vs sibling separately.
 */
export function isDualLockfileAlertManifest(manifestPath) {
  return String(manifestPath || '').startsWith(DUAL_LOCKFILE.alertPrefix);
}

/**
 * Resolve --base, else infer release train from the current git branch
 * (Fullsend already checks out release-1.10 / chore/…-release-1.10).
 */
export async function resolveBumpBase({ repoRoot, explicitBase } = {}) {
  if (explicitBase) {
    return explicitBase;
  }
  if (!repoRoot || !existsSync(resolvePath(repoRoot, '.git'))) {
    return null;
  }
  try {
    const { stdout } = await execFile(
      'git',
      ['rev-parse', '--abbrev-ref', 'HEAD'],
      { cwd: repoRoot, maxBuffer: 1024 * 1024 },
    );
    return extractReleaseBase((stdout || '').toString().trim());
  } catch {
    return null;
  }
}
