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

const NPM_PKG_RE = /((?:@[^/\s]+\/)?[^\s@[]+)@npm:([^\s\]]+)/;
const PLUGIN_ROOT_RE = /workspace:plugins\/([^@\s\[]+)/;
const RUNNER_ROOT_RE =
  /(backend|app|app-legacy)@workspace:packages\/(backend|app|app-legacy)/;
const WORKSPACE_ROOT_RE = /@workspace:\.(?:\s|$|\[)/;

function uniqueSorted(values) {
  return [...new Set(values)].sort();
}

/** Split yarn why output into one tree per top-level ├─/└─ root line. */
export function parseWhyRootTrees(output) {
  const lines = output.split('\n');
  const trees = [];
  let current = null;

  for (const line of lines) {
    if (/^(├─|└─)/.test(line)) {
      if (current) {
        trees.push(current);
      }
      current = { rootLine: line, lines: [line] };
    } else if (current && line.trim()) {
      current.lines.push(line);
    }
  }

  if (current) {
    trees.push(current);
  }

  return trees;
}

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

function identifyRoot(rootLine) {
  if (WORKSPACE_ROOT_RE.test(rootLine)) {
    return { kind: 'workspace', id: 'workspace-root' };
  }

  const runnerMatch = rootLine.match(RUNNER_ROOT_RE);
  if (runnerMatch) {
    return { kind: 'runner', id: runnerMatch[1] };
  }

  const pluginMatch = rootLine.match(PLUGIN_ROOT_RE);
  if (pluginMatch) {
    return { kind: 'plugin', id: pluginMatch[1] };
  }

  return { kind: 'unknown', id: rootLine.trim() };
}

async function loadPluginManifest(workspaceDir, pluginDir) {
  const packageJsonPath = resolvePath(
    workspaceDir,
    'plugins',
    pluginDir,
    'package.json',
  );
  if (!existsSync(packageJsonPath)) {
    return null;
  }
  return JSON.parse(await readFile(packageJsonPath, 'utf8'));
}

function classifyVersionOnPluginPath({
  manifest,
  targetPackage,
  version,
  depth1Package,
  targetDepth,
  pluginLineDepth,
}) {
  const devDeps = new Set(Object.keys(manifest.devDependencies ?? {}));
  const runtimeDeps = new Set([
    ...Object.keys(manifest.dependencies ?? {}),
    ...Object.keys(manifest.peerDependencies ?? {}),
  ]);

  const directRuntime =
    targetDepth === pluginLineDepth + 1 && runtimeDeps.has(targetPackage);
  const viaDevHop = depth1Package !== null && devDeps.has(depth1Package);

  if (directRuntime || (!viaDevHop && depth1Package !== null)) {
    return 'PLUGIN_PROD';
  }
  return 'PLUGIN_DEV';
}

/**
 * For each yarn why tree rooted at a published plugin, bucket target versions
 * on production vs plugin-dev paths. Unpublished / harness plugins (pluginDev)
 * contribute only to nonProd.
 */
async function versionsFromPluginMarkers({
  yarnWhyOutput,
  workspaceDir,
  packageName,
  pluginProd,
  pluginDev = [],
}) {
  const prod = new Set();
  const nonProd = new Set();
  const prodPathDetails = [];
  const manifestCache = new Map();
  const trees = parseWhyRootTrees(yarnWhyOutput);

  const prodIds = new Set(pluginProd.map(entry => entry.plugin));
  const devIds = new Set(pluginDev.map(entry => entry.plugin));

  for (const tree of trees) {
    const root = identifyRoot(tree.rootLine);
    if (root.kind !== 'plugin') {
      continue;
    }

    const isProdPlugin = prodIds.has(root.id);
    const isDevPlugin = devIds.has(root.id);
    if (!isProdPlugin && !isDevPlugin) {
      continue;
    }

    let manifest = manifestCache.get(root.id);
    if (manifest === undefined) {
      manifest = await loadPluginManifest(workspaceDir, root.id);
      manifestCache.set(root.id, manifest);
    }
    if (!manifest) {
      continue;
    }

    const pluginLineDepth = 0;
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

      const depth1Package = packageAtDepth[pluginLineDepth + 1] ?? null;
      const pathKind = classifyVersionOnPluginPath({
        manifest,
        targetPackage: packageName,
        version: parsed.version,
        depth1Package,
        targetDepth: parsed.depth,
        pluginLineDepth,
      });

      const detail = {
        plugin: root.id,
        packageName: manifest.name,
        version: parsed.version,
        path: isDevPlugin && !isProdPlugin ? 'PLUGIN_DEV' : pathKind,
      };

      if (isProdPlugin && pathKind === 'PLUGIN_PROD') {
        prod.add(parsed.version);
        prodPathDetails.push(detail);
      } else {
        nonProd.add(parsed.version);
        prodPathDetails.push(detail);
      }
    }
  }

  return { prod, nonProd, prodPathDetails };
}

function versionsFromRunnerAndWorkspaceTrees(yarnWhyOutput, packageName) {
  const nonProd = new Set();
  const trees = parseWhyRootTrees(yarnWhyOutput);

  for (const tree of trees) {
    const root = identifyRoot(tree.rootLine);
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
 * Walk yarn why trees and split resolved target versions into production-plugin
 * paths vs local-dev paths (runner, workspace root, plugin devDependencies).
 */
export async function resolveVersionsByPath({
  yarnWhyOutput,
  workspaceDir,
  packageName,
  pluginProd = [],
  pluginDev = [],
}) {
  const {
    prod,
    nonProd: pluginNonProd,
    prodPathDetails,
  } = await versionsFromPluginMarkers({
    yarnWhyOutput,
    workspaceDir,
    packageName,
    pluginProd,
    pluginDev,
  });

  const runnerNonProd = versionsFromRunnerAndWorkspaceTrees(
    yarnWhyOutput,
    packageName,
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
