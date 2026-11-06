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
 * Packages the bump scripts must never `yarn up`.
 * Backstage / community-plugin lines are owned by those projects; bumping
 * them here pulls unrelated lockfile churn and version skew.
 */
const SKIP_PREFIXES = ['@backstage/', '@backstage-community/'];

export function isSkippedBumpPackage(packageName) {
  const name = String(packageName || '');
  return SKIP_PREFIXES.some(prefix => name.startsWith(prefix));
}

export function skipReason(packageName) {
  if (!isSkippedBumpPackage(packageName)) {
    return null;
  }
  return 'backstage_denylist';
}
