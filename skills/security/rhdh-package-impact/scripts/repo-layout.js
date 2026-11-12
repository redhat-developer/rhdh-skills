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

import { existsSync, statSync } from 'fs';
import { dirname, resolve as resolvePath } from 'path';

import { parseOwnerRepo } from './github-repo.js';

export const LAYOUT_PLUGINS = 'plugins-monorepo';
export const LAYOUT_RHDH_CORE = 'rhdh-core';

const CORE_PRODUCT_ALIASES = new Set(['', '.', 'rhdh', 'root']);
const PLUGIN_RUNNER_PACKAGES = new Set(['app', 'app-legacy', 'backend']);

function isDir(path) {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

export function isCoreWorkspaceToken(input) {
  const raw = String(input ?? '')
    .trim()
    .replace(/^\.\//, '')
    .replace(/\/+$/, '');
  if (CORE_PRODUCT_ALIASES.has(raw)) {
    return true;
  }
  if (
    raw === 'e2e-tests' ||
    raw.startsWith('e2e-tests/') ||
    raw === '.ci' ||
    raw.startsWith('.ci/')
  ) {
    return true;
  }
  if (
    raw === 'yarn.lock' ||
    raw === 'package.json' ||
    raw.startsWith('packages/') ||
    raw.startsWith('plugins/')
  ) {
    return true;
  }
  return false;
}

export function inferKindFromRepo(ownerRepo) {
  const parsed = parseOwnerRepo(ownerRepo);
  if (!parsed) {
    return null;
  }
  const name = parsed.split('/')[1];
  if (name === 'rhdh-plugins' || name === 'community-plugins') {
    return LAYOUT_PLUGINS;
  }
  if (name === 'rhdh') {
    return LAYOUT_RHDH_CORE;
  }
  return null;
}

export function defaultDependabotRepo(kind) {
  if (kind === LAYOUT_RHDH_CORE) {
    return 'redhat-developer/rhdh';
  }
  return undefined;
}

export function detectLayoutKind(root) {
  if (!root) {
    return null;
  }
  const resolved = resolvePath(root);
  if (isDir(resolvePath(resolved, 'workspaces'))) {
    return LAYOUT_PLUGINS;
  }
  if (
    existsSync(resolvePath(resolved, 'yarn.lock')) &&
    isDir(resolvePath(resolved, 'packages')) &&
    (existsSync(resolvePath(resolved, 'backstage.json')) ||
      isDir(resolvePath(resolved, 'plugins')))
  ) {
    return LAYOUT_RHDH_CORE;
  }
  return null;
}

function walkUpForCheckout(startDir) {
  let dir = startDir;
  for (;;) {
    const kind = detectLayoutKind(dir);
    if (kind) {
      return { kind, repoRoot: dir };
    }
    const parent = dirname(dir);
    if (parent === dir) {
      return null;
    }
    dir = parent;
  }
}

function envCheckout(kind, envName) {
  const raw = process.env[envName];
  if (!raw) {
    return null;
  }
  const root = resolvePath(raw);
  const detected = detectLayoutKind(root);
  if (detected !== kind) {
    throw new Error(
      `${envName}=${root} is not a ${kind} checkout (expected ${
        kind === LAYOUT_PLUGINS
          ? 'a workspaces/ directory'
          : 'root yarn.lock + packages/'
      })`,
    );
  }
  return { kind, repoRoot: root };
}

/**
 * Locate a plugins-monorepo or rhdh-core checkout.
 * @returns {{ kind: string, repoRoot: string }}
 */
export function findCheckout({
  explicitRoot,
  cwd = process.cwd(),
  required = true,
} = {}) {
  if (explicitRoot) {
    const root = resolvePath(explicitRoot);
    const kind = detectLayoutKind(root);
    if (!kind) {
      throw new Error(
        `--repo-root ${root} is neither a plugins monorepo (workspaces/) nor rhdh core (root yarn.lock + packages/)`,
      );
    }
    return { kind, repoRoot: root };
  }

  const walked = walkUpForCheckout(cwd);
  if (walked) {
    return walked;
  }

  const pluginsEnv = process.env.RHDH_PLUGINS_ROOT
    ? envCheckout(LAYOUT_PLUGINS, 'RHDH_PLUGINS_ROOT')
    : null;
  if (pluginsEnv) {
    return pluginsEnv;
  }
  const coreEnv = process.env.RHDH_CORE_ROOT
    ? envCheckout(LAYOUT_RHDH_CORE, 'RHDH_CORE_ROOT')
    : null;
  if (coreEnv) {
    return coreEnv;
  }

  if (!required) {
    return null;
  }

  throw new Error(
    'Could not find repo root. Pass --repo-root, set RHDH_PLUGINS_ROOT / RHDH_CORE_ROOT, or run from a plugins (workspaces/) or rhdh core checkout.',
  );
}

function parsePluginsWorkspace(input, exactManifestFlag) {
  let path = String(input || '')
    .trim()
    .replace(/^\.\//, '')
    .replace(/\/+$/, '');
  if (!path) {
    throw new Error('workspace name is required for a plugins monorepo');
  }

  if (
    !path.includes('/') &&
    !path.endsWith('.lock') &&
    !path.endsWith('.json')
  ) {
    path = `workspaces/${path}`;
  }

  if (!path.startsWith('workspaces/')) {
    throw new Error(
      `Expected workspace name or workspaces/<name>/… path, got "${input}"`,
    );
  }

  const rest = path.slice('workspaces/'.length);
  const slash = rest.indexOf('/');
  const workspace = slash === -1 ? rest : rest.slice(0, slash);
  if (!workspace) {
    throw new Error(`Could not parse workspace from "${input}"`);
  }

  const isFile =
    path.endsWith('.lock') || path.endsWith('.json') || exactManifestFlag;

  if (isFile) {
    let manifest = path;
    if (
      exactManifestFlag &&
      !path.endsWith('.lock') &&
      !path.endsWith('.json')
    ) {
      manifest = `${path}/yarn.lock`;
    }
    return {
      workspace,
      scope: 'workspace',
      exactManifest: manifest,
      lockfileRel: `workspaces/${workspace}/yarn.lock`,
      alertPrefix: `workspaces/${workspace}/`,
    };
  }

  return {
    workspace,
    scope: 'workspace',
    exactManifest: null,
    lockfileRel: `workspaces/${workspace}/yarn.lock`,
    alertPrefix: `workspaces/${workspace}/`,
  };
}

function parseCoreWorkspace(input, exactManifestFlag) {
  const raw = String(input ?? '')
    .trim()
    .replace(/^\.\//, '')
    .replace(/\/+$/, '');

  if (!raw || CORE_PRODUCT_ALIASES.has(raw)) {
    return {
      workspace: 'rhdh',
      scope: 'product',
      exactManifest: exactManifestFlag ? 'yarn.lock' : null,
      lockfileRel: 'yarn.lock',
      alertPrefix: null,
    };
  }

  if (raw === 'yarn.lock' || raw === 'package.json') {
    return {
      workspace: 'rhdh',
      scope: 'product',
      exactManifest: raw,
      lockfileRel: 'yarn.lock',
      alertPrefix: null,
    };
  }

  if (raw === 'e2e-tests' || raw.startsWith('e2e-tests/')) {
    const exact =
      raw.endsWith('.lock') || raw.endsWith('.json')
        ? raw
        : exactManifestFlag
          ? `${raw.replace(/\/+$/, '')}/yarn.lock`
          : raw === 'e2e-tests'
            ? null
            : raw;
    return {
      workspace: 'e2e-tests',
      scope: 'e2e',
      exactManifest: exact,
      lockfileRel: 'e2e-tests/yarn.lock',
      alertPrefix: 'e2e-tests/',
    };
  }

  if (raw === '.ci' || raw.startsWith('.ci/')) {
    const exact =
      raw.endsWith('.lock') || raw.endsWith('.json')
        ? raw
        : exactManifestFlag
          ? `${raw.replace(/\/+$/, '')}/yarn.lock`
          : raw === '.ci'
            ? null
            : raw;
    return {
      workspace: '.ci',
      scope: 'ci',
      exactManifest: exact,
      lockfileRel: '.ci/yarn.lock',
      alertPrefix: '.ci/',
    };
  }

  if (raw.startsWith('packages/') || raw.startsWith('plugins/')) {
    return {
      workspace: 'rhdh',
      scope: 'product',
      exactManifest: raw,
      lockfileRel: 'yarn.lock',
      alertPrefix: null,
    };
  }

  throw new Error(
    `rhdh core has no workspaces/${raw}. Use rhdh (or .) for the product lockfile, e2e-tests, or .ci.`,
  );
}

export function parseWorkspaceInput(kind, input, exactManifestFlag = false) {
  if (kind === LAYOUT_RHDH_CORE) {
    return parseCoreWorkspace(input, exactManifestFlag);
  }
  return parsePluginsWorkspace(input, exactManifestFlag);
}

function productManifest(manifestPath) {
  if (!manifestPath) {
    return false;
  }
  if (
    manifestPath.startsWith('e2e-tests/') ||
    manifestPath.startsWith('.ci/') ||
    manifestPath.startsWith('scripts/')
  ) {
    return false;
  }
  if (manifestPath === 'yarn.lock' || manifestPath === 'package.json') {
    return true;
  }
  return (
    manifestPath.startsWith('packages/') || manifestPath.startsWith('plugins/')
  );
}

export function matchAlertManifest(layout, manifestPath) {
  const manifest = String(manifestPath || '');
  if (!manifest) {
    return false;
  }
  if (layout.exactManifest) {
    return manifest === layout.exactManifest;
  }
  if (layout.kind === LAYOUT_PLUGINS) {
    if (manifest === 'yarn.lock') {
      return layout.workspace === 'root';
    }
    return Boolean(layout.alertPrefix) && manifest.startsWith(layout.alertPrefix);
  }
  if (layout.scope === 'e2e') {
    return manifest.startsWith('e2e-tests/');
  }
  if (layout.scope === 'ci') {
    return manifest.startsWith('.ci/');
  }
  return productManifest(manifest);
}

export function filterAlertsForLayout(alerts, layout, packageName) {
  return (alerts || []).filter(alert => {
    const dep = alert.dependency ?? {};
    if (packageName && dep.package?.name !== packageName) {
      return false;
    }
    return matchAlertManifest(layout, dep.manifest_path);
  });
}

/**
 * Dependabot manifest_path (+ optional scope) → classification label.
 * For rhdh-core, packages/app|backend are CORE_PROD, never RUNNER.
 */
export function classifyManifest(layoutKind, manifestPath, scope) {
  if (!manifestPath) {
    return 'UNKNOWN';
  }
  if (layoutKind === LAYOUT_RHDH_CORE) {
    if (manifestPath.startsWith('e2e-tests/')) {
      return 'E2E';
    }
    if (manifestPath.startsWith('.ci/')) {
      return 'CI';
    }
    if (/(^|\/)plugins\//.test(manifestPath)) {
      return scope === 'development' ? 'PLUGIN_DEV' : 'PLUGIN_PROD';
    }
    if (/(^|\/)packages\/[^/]+\/package\.json$/.test(manifestPath)) {
      return scope === 'development' ? 'CORE_DEV' : 'CORE_PROD';
    }
    if (manifestPath === 'package.json') {
      return 'WORKSPACE_DEV';
    }
    if (manifestPath === 'yarn.lock' || manifestPath.endsWith('/yarn.lock')) {
      return 'LOCKFILE';
    }
    if (scope === 'development') {
      return 'PLUGIN_DEV';
    }
    return 'UNKNOWN';
  }

  if (/(^|\/)plugins\//.test(manifestPath)) {
    return scope === 'development' ? 'PLUGIN_DEV' : 'PLUGIN_PROD';
  }
  if (
    /(^|\/)packages\/(backend|app|app-legacy)\/package\.json$/.test(
      manifestPath,
    )
  ) {
    return 'RUNNER';
  }
  if (
    manifestPath.endsWith('/yarn.lock') ||
    manifestPath.endsWith('yarn.lock')
  ) {
    return 'LOCKFILE';
  }
  if (scope === 'development') {
    return 'PLUGIN_DEV';
  }
  return 'UNKNOWN';
}

export function isShippedClassification(classification) {
  const value = String(classification || '');
  return value.includes('PLUGIN_PROD') || value.includes('CORE_PROD');
}

function coreYarnCwd(repoRoot, parsed) {
  if (parsed.scope === 'e2e') {
    return resolvePath(repoRoot, 'e2e-tests');
  }
  if (parsed.scope === 'ci') {
    return resolvePath(repoRoot, '.ci');
  }
  return repoRoot;
}

function assertLockfile(layout) {
  if (!layout.repoRoot) {
    return;
  }
  if (!existsSync(layout.lockPath)) {
    throw new Error(`No yarn.lock at ${layout.lockfileRel}`);
  }
  if (layout.kind === LAYOUT_PLUGINS && !existsSync(layout.workspaceDir)) {
    throw new Error(`Workspace not found: workspaces/${layout.workspace}`);
  }
}

/**
 * Resolve layout + workspace paths for classify / bump / list.
 *
 * `workspaceInput` may be omitted for rhdh-core (defaults to product `rhdh`).
 */
export function resolveRepoLayout({
  explicitRoot,
  workspaceInput,
  exactManifest = false,
  explicitRepo,
  cwd = process.cwd(),
  requireCheckout = true,
} = {}) {
  const checkout = findCheckout({
    explicitRoot,
    cwd,
    required: requireCheckout,
  });

  let kind = checkout?.kind ?? null;
  if (!kind) {
    kind = inferKindFromRepo(explicitRepo) || LAYOUT_PLUGINS;
  }

  const parsed = parseWorkspaceInput(kind, workspaceInput, exactManifest);
  const repoRoot = checkout?.repoRoot ?? null;
  const workspaceDir = repoRoot ? coreOrPluginsDir(kind, repoRoot, parsed) : null;
  const lockPath = workspaceDir
    ? resolvePath(workspaceDir, 'yarn.lock')
    : null;

  const layout = {
    kind,
    repoRoot,
    workspace: parsed.workspace,
    scope: parsed.scope,
    exactManifest: parsed.exactManifest,
    alertPrefix: parsed.alertPrefix,
    lockfileRel: parsed.lockfileRel,
    workspaceDir,
    lockPath,
    yarnCwd: workspaceDir,
    defaultDependabotRepo: defaultDependabotRepo(kind),
    bumpBranch: `chore/${parsed.workspace}-cve-bumps`,
    statusPaths:
      kind === LAYOUT_RHDH_CORE && parsed.scope === 'product'
        ? ['yarn.lock', 'package.json', 'packages', 'plugins']
        : kind === LAYOUT_PLUGINS
          ? [`workspaces/${parsed.workspace}`]
          : [parsed.lockfileRel],
  };

  if (requireCheckout) {
    assertLockfile(layout);
  }

  return layout;
}

function coreOrPluginsDir(kind, repoRoot, parsed) {
  if (kind === LAYOUT_RHDH_CORE) {
    return coreYarnCwd(repoRoot, parsed);
  }
  return resolvePath(repoRoot, 'workspaces', parsed.workspace);
}

export function pluginRunnerPackage(id) {
  return PLUGIN_RUNNER_PACKAGES.has(id);
}

export function splitWorkspaceArgs(kind, positional) {
  if (kind !== LAYOUT_RHDH_CORE) {
    return {
      workspaceInput: positional[0],
      packages: positional.slice(1),
    };
  }
  const first = positional[0];
  if (!first || isCoreWorkspaceToken(first)) {
    return { workspaceInput: first || 'rhdh', packages: positional.slice(1) };
  }
  return { workspaceInput: 'rhdh', packages: positional.slice() };
}
