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
 * Leftover packages that bump-workspace-packages.js may ancestor-bump
 * automatically after yarn up -R.
 *
 * Allowlist a package only when all of these hold across workspaces:
 * - yarn up -R leaves a second resolved line held by a parent range
 * - clearing it is a parent patch/minor (not a dual major)
 * - the remaining resolved version is patched for the open CVE
 * - bump-package-ancestors.js revert-on-failure is enough safety
 *
 * qs: leftover `qs@npm:~6.14.0` (6.14.2) via express / body-parser;
 * bumping those parents collapses the lockfile to qs 6.15.3.
 * webpack-dev-server: leftover `webpack-dev-server@npm:5.2.2` (5.2.2) via @rspack/dev-server;
 * 
 * Do not add uuid, react-router, @nestjs/*, adm-zip, tmp, lodash, tar,
 * undici, or fast-xml-parser — dual-major or pinned leftovers.
 * Everything else still requires an explicit ancestor-bump ask.
 */
export const ANCESTOR_AUTO_PACKAGES = ['qs', 'webpack-dev-server'];

export function isAncestorAutoPackage(packageName) {
  return ANCESTOR_AUTO_PACKAGES.includes(String(packageName || ''));
}
