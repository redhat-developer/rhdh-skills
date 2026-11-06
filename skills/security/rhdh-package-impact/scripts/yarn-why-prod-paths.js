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

const PKG_AT_RE = /((?:@[^/\s]+\/)?[^\s@[]+)@(?:npm:|workspace:)/;
const PLUGIN_ROOT_RE = /workspace:plugins\/([^@\s\[]+)/;

/** Split yarn why -R output into one tree per top-level root. */
export function parseWhyRootTrees(output) {
  const trees = [];
  let current = null;

  for (const line of (output || '').split('\n')) {
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

/** Depth from connector column (~3 cols per level). */
function lineDepth(line) {
  const connector = line.search(/[├└]─/);
  return connector < 0 ? -1 : Math.round(connector / 3);
}

function extractPackageName(line) {
  const match = line.match(PKG_AT_RE);
  return match ? match[1] : null;
}

function pluginIdFromRoot(rootLine) {
  const match = rootLine.match(PLUGIN_ROOT_RE);
  return match ? match[1] : null;
}

/**
 * PLUGIN_PROD chains to targetPackage (runtime first hop).
 * Returns `{ plugin, firstHop, path }[]`.
 */
export function collectPluginProdPaths({
  yarnWhyOutput,
  targetPackage,
  runtimeDepsByPlugin,
}) {
  const paths = [];

  for (const tree of parseWhyRootTrees(yarnWhyOutput)) {
    const pluginId = pluginIdFromRoot(tree.rootLine);
    if (!pluginId) {
      continue;
    }
    const runtime = runtimeDepsByPlugin[pluginId];
    if (!runtime) {
      continue;
    }
    const runtimeSet = runtime instanceof Set ? runtime : new Set(runtime);

    const packageAtDepth = {};
    for (const line of tree.lines) {
      const depth = lineDepth(line);
      if (depth < 0) {
        continue;
      }
      const name = extractPackageName(line);
      if (!name) {
        continue;
      }
      packageAtDepth[depth] = name;
      for (const key of Object.keys(packageAtDepth)) {
        if (Number(key) > depth) {
          delete packageAtDepth[key];
        }
      }
      if (name !== targetPackage) {
        continue;
      }
      const firstHop = packageAtDepth[1] ?? null;
      if (firstHop === null || !runtimeSet.has(firstHop)) {
        continue;
      }
      const chain = [];
      for (let d = 0; d <= depth; d += 1) {
        if (packageAtDepth[d]) {
          chain.push(packageAtDepth[d]);
        }
      }
      paths.push({ plugin: pluginId, firstHop, path: chain });
    }
  }

  return paths;
}
