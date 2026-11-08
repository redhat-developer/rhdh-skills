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
 * react-router and react-router-dom must resolve to the same patch within a
 * major. Dependabot often only alerts on react-router; bumping that alone
 * leaves react-router-dom behind and trips review bots (e.g. Qodo).
 *
 * When either package is in the bump set and the other is present in the
 * lockfile, include both. After yarn up -R, if same-major highs still differ,
 * pin react-router-dom descriptors to react-router's version via
 * `yarn set resolution` (lockfile only — no package.json pin).
 */

export const REACT_ROUTER = 'react-router';
export const REACT_ROUTER_DOM = 'react-router-dom';

const PAIR = [REACT_ROUTER, REACT_ROUTER_DOM];

export function lockfileHasPackage(lockfileText, packageName) {
  const escaped = String(packageName || '').replace(
    /[.*+?^${}()|[\]\\]/g,
    '\\$&',
  );
  return new RegExp(`^"${escaped}@`, 'm').test(lockfileText);
}

/**
 * If the bump list includes either half of the pair and the other exists in
 * the lockfile, add the missing half. Returns sorted unique names plus which
 * packages were auto-added for pairing.
 */
export function expandReactRouterPair(packageNames, lockfileText) {
  const set = new Set(packageNames);
  const bumpingRouter = set.has(REACT_ROUTER);
  const bumpingDom = set.has(REACT_ROUTER_DOM);
  if (!bumpingRouter && !bumpingDom) {
    return { packageNames: [...packageNames], pairedAdded: [] };
  }

  const pairedAdded = [];
  if (
    bumpingRouter &&
    !set.has(REACT_ROUTER_DOM) &&
    lockfileHasPackage(lockfileText, REACT_ROUTER_DOM)
  ) {
    set.add(REACT_ROUTER_DOM);
    pairedAdded.push(REACT_ROUTER_DOM);
  }
  if (
    bumpingDom &&
    !set.has(REACT_ROUTER) &&
    lockfileHasPackage(lockfileText, REACT_ROUTER)
  ) {
    set.add(REACT_ROUTER);
    pairedAdded.push(REACT_ROUTER);
  }

  return {
    packageNames: [...set].sort(),
    pairedAdded,
  };
}

/**
 * Lockfile keys are often comma-joined descriptors:
 *   "react-router-dom@npm:^6.28.0, react-router-dom@npm:6.30.4":
 */
export function descriptorsFromLockfile(lockfileText, packageName) {
  const escaped = String(packageName || '').replace(
    /[.*+?^${}()|[\]\\]/g,
    '\\$&',
  );
  const keyRe = new RegExp(`^"${escaped}@[^"]+":`, 'gm');
  const descriptors = new Set();
  let match;
  while ((match = keyRe.exec(lockfileText)) !== null) {
    const key = match[0].slice(1, -2);
    for (const part of key.split(', ')) {
      const trimmed = part.trim();
      if (trimmed) {
        descriptors.add(trimmed);
      }
    }
  }
  return [...descriptors].sort();
}

function rangeFromDescriptor(descriptor, packageName) {
  const prefix = `${packageName}@npm:`;
  if (!descriptor.startsWith(prefix)) {
    return null;
  }
  return descriptor.slice(prefix.length);
}

/**
 * Per major that both packages resolve, react-router-dom's highest version
 * must equal react-router's. Returns align targets keyed by major, or [].
 */
export function reactRouterDomAlignTargets(semver, routerVersions, domVersions) {
  const targets = [];
  const majors = new Set(
    [...routerVersions, ...domVersions]
      .map(v => {
        try {
          return semver.major(v);
        } catch {
          return null;
        }
      })
      .filter(m => m !== null && m !== undefined),
  );

  for (const major of [...majors].sort((a, b) => a - b)) {
    const routerOfMajor = routerVersions.filter(v => semver.major(v) === major);
    const domOfMajor = domVersions.filter(v => semver.major(v) === major);
    if (!routerOfMajor.length || !domOfMajor.length) {
      continue;
    }
    const routerTarget = [...routerOfMajor].sort(semver.rcompare)[0];
    const domHigh = [...domOfMajor].sort(semver.rcompare)[0];
    if (routerTarget !== domHigh) {
      targets.push({ major, version: routerTarget, domWas: domHigh });
    }
  }
  return targets;
}

/**
 * Which react-router-dom@npm:… descriptors can be set to `version`.
 * Includes caret/tilde ranges that satisfy the target, and exact pins on the
 * same major (so 6.30.4 can be retargeted to 6.30.6).
 */
export function descriptorsSatisfyingVersion(
  semver,
  descriptors,
  packageName,
  version,
) {
  return descriptors.filter(descriptor => {
    const range = rangeFromDescriptor(descriptor, packageName);
    if (!range) {
      return false;
    }
    if (range === version) {
      return true;
    }
    try {
      if (semver.satisfies(version, range, { includePrerelease: true })) {
        return true;
      }
    } catch {
      // fall through
    }
    try {
      if (
        semver.valid(range) &&
        semver.major(range) === semver.major(version)
      ) {
        return true;
      }
    } catch {
      return false;
    }
    return false;
  });
}
