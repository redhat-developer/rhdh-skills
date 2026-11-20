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

import { LAYOUT_PLUGINS, LAYOUT_RHDH_CORE, pluginRunnerPackage } from './repo-layout.js';

const PLUGIN_ROOT_RE = /workspace:plugins\/([^@\s\[]+)/;
const PACKAGES_ROOT_RE = /@workspace:packages\/([^@\s\[]+)/;
const WORKSPACE_ROOT_RE = /@workspace:\.(?:\s|$|\[)/;

/** Split yarn why output into one tree per top-level ├─/└─ root line. */
export function parseWhyRootTrees(output) {
  const lines = String(output || '').split('\n');
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

/**
 * Identify the workspace package that owns a yarn why tree.
 *
 * plugins-monorepo: packages/app|app-legacy|backend → runner (local-dev).
 * rhdh-core: every packages/* tree → core (shipped RHDH app/backend).
 */
export function identifyWhyRoot(rootLine, layoutKind = LAYOUT_PLUGINS) {
  const line = String(rootLine || '');
  if (WORKSPACE_ROOT_RE.test(line)) {
    return { kind: 'workspace', id: 'workspace-root' };
  }

  const packagesMatch = line.match(PACKAGES_ROOT_RE);
  if (packagesMatch) {
    const id = packagesMatch[1];
    if (layoutKind === LAYOUT_RHDH_CORE) {
      return { kind: 'core', id };
    }
    if (pluginRunnerPackage(id)) {
      return { kind: 'runner', id };
    }
    return { kind: 'unknown', id };
  }

  const pluginMatch = line.match(PLUGIN_ROOT_RE);
  if (pluginMatch) {
    return { kind: 'plugin', id: pluginMatch[1] };
  }

  return { kind: 'unknown', id: line.trim() };
}

export { LAYOUT_PLUGINS, LAYOUT_RHDH_CORE };
