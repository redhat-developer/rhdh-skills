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

import { existsSync } from 'fs';
import { readFile } from 'fs/promises';
import { resolve as resolvePath } from 'path';

import { LAYOUT_PLUGINS } from './repo-layout.js';
import { identifyWhyRoot, parseWhyRootTrees } from './yarn-why-roots.js';

const NPM_PKG_RE = /((?:@[^/\s]+\/)?[^\s@[]+)@npm:([^\s\]]+)/;

function uniqueSorted(values) {
  return [...new Set(values)].sort();
}

export { parseWhyRootTrees };

function lineDepth(line) {
  if (/^(├─|└─)/.test(line)) {
    return 0;
  }
  if (line.includes('│')) {
    return (line.match(/│/g) || []).length;
  }
  return -1;
}

function parseTreeLine(line) {
  const connector = line.search(/[├└]─/);
  if (connector < 0) {
    return null;
  }
  const depth = lineDepth(line);
  const rest = line.slice(connector + 2).trimStart();
  const pkgMatch = rest.match(NPM_PKG_RE);
  if (!pkgMatch) {
    return { depth, packageName: null, version: null, raw: rest };
  }
  return {
    depth,
    packageName: pkgMatch[1],
    version: pkgMatch[2],
    raw: rest,
  };
}

async function loadWorkspaceManifest(workspaceDir, parentDir, packageDir) {
  const packageJsonPath = resolvePath(
    workspaceDir,
    parentDir,
    packageDir,
    'package.json',
  );
  if (!existsSync(packageJsonPath)) {
    return null;
  }
  return JSON.parse(await readFile(packageJsonPath, 'utf8'));
}

function classifyVersionOnWorkspacePath({
  manifest,
  targetPackage,
  depth1Package,
  targetDepth,
  rootLineDepth,
  prodLabel,
  devLabel,
}) {
  const devDeps = new Set(Object.keys(manifest.devDependencies ?? {}));
  const runtimeDeps = new Set([
    ...Object.keys(manifest.dependencies ?? {}),
    ...Object.keys(manifest.peerDependencies ?? {}),
  ]);

  const directRuntime =
    targetDepth === rootLineDepth + 1 && runtimeDeps.has(targetPackage);
  const viaDevHop = depth1Package !== null && devDeps.has(depth1Package);

  if (directRuntime || (!viaDevHop && depth1Package !== null)) {
    return prodLabel;
  }
  return devLabel;
}

function collectTargetVersionsInTree({
  tree,
  packageName,
  manifest,
  rootId,
  isProdRoot,
  isDevRoot,
  prodLabel,
  devLabel,
  prod,
  nonProd,
  prodPathDetails,
}) {
  const rootLineDepth = 0;
  const packageAtDepth = {};

  for (const line of tree.lines) {
    const parsed = parseTreeLine(line);
    if (!parsed?.packageName) {
      continue;
    }

    packageAtDepth[parsed.depth] = parsed.packageName;
    for (const d of Object.keys(packageAtDepth)) {
      if (Number(d) > parsed.depth) {
        delete packageAtDepth[d];
      }
    }

    if (parsed.packageName !== packageName || !parsed.version) {
      continue;
    }

    const depth1Package = packageAtDepth[rootLineDepth + 1] ?? null;
    const pathKind = classifyVersionOnWorkspacePath({
      manifest,
      targetPackage: packageName,
      depth1Package,
      targetDepth: parsed.depth,
      rootLineDepth,
      prodLabel,
      devLabel,
    });

    const detail = {
      plugin: rootId,
      packageName: manifest.name,
      version: parsed.version,
      path: isDevRoot && !isProdRoot ? devLabel : pathKind,
    };

    if (isProdRoot && pathKind === prodLabel) {
      prod.add(parsed.version);
      prodPathDetails.push(detail);
    } else {
      nonProd.add(parsed.version);
      prodPathDetails.push(detail);
    }
  }
}

/**
 * For each yarn why tree rooted at a published plugin or rhdh core package,
 * bucket target versions on production vs dev paths.
 */
async function versionsFromWorkspaceMarkers({
  yarnWhyOutput,
  workspaceDir,
  packageName,
  layoutKind = LAYOUT_PLUGINS,
  pluginProd,
  pluginDev = [],
  coreProd = [],
  coreDev = [],
}) {
  const prod = new Set();
  const nonProd = new Set();
  const prodPathDetails = [];
  const manifestCache = new Map();
  const trees = parseWhyRootTrees(yarnWhyOutput);

  const pluginProdIds = new Set(pluginProd.map(entry => entry.plugin));
  const pluginDevIds = new Set(pluginDev.map(entry => entry.plugin));
  const coreProdIds = new Set(coreProd.map(entry => entry.package));
  const coreDevIds = new Set(coreDev.map(entry => entry.package));

  for (const tree of trees) {
    const root = identifyWhyRoot(tree.rootLine, layoutKind);
    let parentDir;
    let prodIds;
    let devIds;
    let prodLabel;
    let devLabel;
    if (root.kind === 'plugin') {
      parentDir = 'plugins';
      prodIds = pluginProdIds;
      devIds = pluginDevIds;
      prodLabel = 'PLUGIN_PROD';
      devLabel = 'PLUGIN_DEV';
    } else if (root.kind === 'core') {
      parentDir = 'packages';
      prodIds = coreProdIds;
      devIds = coreDevIds;
      prodLabel = 'CORE_PROD';
      devLabel = 'CORE_DEV';
    } else {
      continue;
    }

    const isProdRoot = prodIds.has(root.id);
    const isDevRoot = devIds.has(root.id);
    if (!isProdRoot && !isDevRoot) {
      continue;
    }

    const cacheKey = `${parentDir}/${root.id}`;
    let manifest = manifestCache.get(cacheKey);
    if (manifest === undefined) {
      manifest = await loadWorkspaceManifest(
        workspaceDir,
        parentDir,
        root.id,
      );
      manifestCache.set(cacheKey, manifest);
    }
    if (!manifest) {
      continue;
    }

    collectTargetVersionsInTree({
      tree,
      packageName,
      manifest,
      rootId: root.id,
      isProdRoot,
      isDevRoot,
      prodLabel,
      devLabel,
      prod,
      nonProd,
      prodPathDetails,
    });
  }

  return { prod, nonProd, prodPathDetails };
}

function versionsFromRunnerAndWorkspaceTrees(
  yarnWhyOutput,
  packageName,
  layoutKind = LAYOUT_PLUGINS,
) {
  const nonProd = new Set();
  const trees = parseWhyRootTrees(yarnWhyOutput);

  for (const tree of trees) {
    const root = identifyWhyRoot(tree.rootLine, layoutKind);
    if (root.kind !== 'runner' && root.kind !== 'workspace') {
      continue;
    }

    for (const line of tree.lines) {
      const parsed = parseTreeLine(line);
      if (parsed?.packageName === packageName && parsed.version) {
        nonProd.add(parsed.version);
      }
    }
  }

  return nonProd;
}

/**
 * Walk yarn why trees and split resolved target versions into production
 * paths vs local-dev paths (runner, workspace root, plugin/core devDependencies).
 * On rhdh-core, packages/app|backend trees are production (CORE_PROD), not runners.
 */
export async function resolveVersionsByPath({
  yarnWhyOutput,
  workspaceDir,
  packageName,
  layoutKind = LAYOUT_PLUGINS,
  pluginProd = [],
  pluginDev = [],
  coreProd = [],
  coreDev = [],
}) {
  const {
    prod,
    nonProd: pluginNonProd,
    prodPathDetails,
  } = await versionsFromWorkspaceMarkers({
    yarnWhyOutput,
    workspaceDir,
    packageName,
    layoutKind,
    pluginProd,
    pluginDev,
    coreProd,
    coreDev,
  });

  const runnerNonProd = versionsFromRunnerAndWorkspaceTrees(
    yarnWhyOutput,
    packageName,
    layoutKind,
  );

  const nonProd = new Set([...pluginNonProd, ...runnerNonProd]);
  const prodResolvedVersions = uniqueSorted(prod);
  const nonProdResolvedVersions = uniqueSorted(
    [...nonProd].filter(v => !prod.has(v)),
  );

  return {
    prodResolvedVersions,
    nonProdResolvedVersions,
    prodPathDetails,
  };
}

export function buildVersionStatuses(versions, semver, alerts) {
  return versions.map(version => {
    const checks = alerts.map(a => ({
      alert: a.number ?? null,
      ...versionIsPatchedForAlert(
        semver,
        version,
        a.vulnerableRange,
        a.firstPatched,
      ),
    }));
    const patched = checks.some(c => c.patched === false)
      ? false
      : checks.every(c => c.patched === true)
        ? true
        : null;
    return {
      version,
      patched,
      reason:
        patched === true
          ? 'outside all open advisory ranges'
          : patched === false
            ? 'vulnerable to at least one open advisory'
            : 'incomplete advisory metadata',
      checks,
    };
  });
}

function normalizeVulnerableRange(range) {
  if (!range) {
    return range;
  }
  return String(range).replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
}

function versionIsPatchedForAlert(semver, version, vulnerableRange, firstPatched) {
  const v = semver.coerce(version)?.version;
  if (!v) {
    return { patched: null, reason: `unparseable version ${version}` };
  }

  const range = normalizeVulnerableRange(vulnerableRange);
  if (range) {
    try {
      if (semver.satisfies(v, range, { includePrerelease: true })) {
        return { patched: false, reason: `in vulnerable range ${range}` };
      }
      return { patched: true, reason: `outside vulnerable range ${range}` };
    } catch {
      // fall through
    }
  }

  if (firstPatched) {
    const fp = semver.coerce(firstPatched)?.version;
    if (!fp) {
      return { patched: null, reason: `unparseable first_patched ${firstPatched}` };
    }
    if (semver.gte(v, fp)) {
      return { patched: true, reason: `>= first_patched ${fp}` };
    }
    return { patched: false, reason: `< first_patched ${fp}` };
  }

  return { patched: null, reason: 'no vulnerable range or first_patched_version' };
}

export function patchedVersions(versionStatuses) {
  return versionStatuses.length > 0 && versionStatuses.every(v => v.patched === true);
}
