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
 * Known packages that must not major-bump via yarn up -R.
 *
 * Yarn forbids version ranges with `--recursive`, so we run bare
 * `yarn up -R <package>`. That respects normal ranges (`^5` stays on v5) but
 * jumps when a descriptor is wide (e.g. `*`).
 *
 * Only packages listed here get post-bump major-jump re-pinning via
 * `yarn set resolution` to the latest release within the previous major.
 * Do not generalize — add a name here when a concrete case shows up.
 *
 * http-proxy-middleware: `*` went 3.0.3 → 4.2.0 even though CVE-2026-55602 is
 * fixed on 3.0.6+ and v4 is ESM-only / Node >= 22.15.
 */

export const NO_MAJOR_BUMP_PACKAGES = Object.freeze(['http-proxy-middleware']);

export function isNoMajorBumpPackage(packageName) {
  return NO_MAJOR_BUMP_PACKAGES.includes(String(packageName || ''));
}

/**
 * Map each lockfile descriptor (`pkg@npm:…`) to its resolved version.
 */
export function descriptorVersionsFromLockfile(lockfileText, packageName) {
  const escaped = String(packageName || '').replace(
    /[.*+?^${}()|[\]\\]/g,
    '\\$&',
  );
  const blockRe = new RegExp(
    `^"((?:${escaped}@[^"]+(?:, )?)*)":\\n((?:  .*\\n)*)`,
    'gm',
  );
  const out = new Map();
  let match;
  while ((match = blockRe.exec(lockfileText)) !== null) {
    const key = match[1];
    const ver = match[2].match(/^  version: (.+)$/m);
    if (!ver) {
      continue;
    }
    const version = ver[1].trim().replace(/^["']|["']$/g, '');
    for (const part of key.split(', ')) {
      const descriptor = part.trim();
      if (descriptor) {
        out.set(descriptor, version);
      }
    }
  }
  return out;
}

export async function fetchNpmVersions(packageName) {
  const name = String(packageName || '').trim();
  if (!name) {
    return [];
  }
  const scopedUrl = name.startsWith('@')
    ? `https://registry.npmjs.org/${name.replace('/', '%2F')}`
    : `https://registry.npmjs.org/${encodeURIComponent(name)}`;
  const response = await fetch(scopedUrl, {
    headers: {
      Accept: 'application/json',
      'User-Agent': 'plugins-package-impact',
    },
  });
  if (!response.ok) {
    throw new Error(
      `npm registry ${response.status} for ${name}: ${await response.text()}`,
    );
  }
  const data = await response.json();
  return Object.keys(data.versions || {});
}

export function latestVersionInMajor(semver, versions, major) {
  const inMajor = (versions || []).filter(v => {
    const coerced = semver.coerce(v);
    return coerced && semver.major(coerced) === major && semver.valid(v);
  });
  if (!inMajor.length) {
    const coercedOnly = (versions || []).filter(v => {
      const coerced = semver.coerce(v);
      return coerced && semver.major(coerced) === major;
    });
    if (!coercedOnly.length) {
      return null;
    }
    return [...coercedOnly].sort(semver.rcompare)[0];
  }
  return [...inMajor].sort(semver.rcompare)[0];
}

/**
 * Descriptors whose resolved major after bump differs from before.
 */
export function majorJumpPins(semver, beforeMap, afterMap, npmVersions) {
  const pins = [];
  for (const [descriptor, afterVersion] of afterMap.entries()) {
    const beforeVersion = beforeMap.get(descriptor);
    if (!beforeVersion) {
      continue;
    }
    const beforeCoerced = semver.coerce(beforeVersion);
    const afterCoerced = semver.coerce(afterVersion);
    if (!beforeCoerced || !afterCoerced) {
      continue;
    }
    const beforeMajor = semver.major(beforeCoerced);
    if (beforeMajor === semver.major(afterCoerced)) {
      continue;
    }
    const targetVersion = latestVersionInMajor(
      semver,
      npmVersions,
      beforeMajor,
    );
    if (!targetVersion || targetVersion === afterVersion) {
      continue;
    }
    pins.push({
      descriptor,
      beforeVersion,
      afterVersion,
      beforeMajor,
      targetVersion,
    });
  }
  return pins;
}

/**
 * For NO_MAJOR_BUMP_PACKAGES only: re-pin descriptors that major-jumped
 * after yarn up -R to the latest release within their previous major.
 */
export async function pinMajorJumps({
  semver,
  packageName,
  lockfileBefore,
  lockfileAfter,
  runYarn,
  fetchVersions = fetchNpmVersions,
}) {
  if (!isNoMajorBumpPackage(packageName)) {
    return { pinned: false, pins: [], skipped: true };
  }

  const beforeMap = descriptorVersionsFromLockfile(lockfileBefore, packageName);
  const afterMap = descriptorVersionsFromLockfile(lockfileAfter, packageName);
  const jumped = [];
  for (const [descriptor, afterVersion] of afterMap.entries()) {
    const beforeVersion = beforeMap.get(descriptor);
    if (!beforeVersion) {
      continue;
    }
    const beforeCoerced = semver.coerce(beforeVersion);
    const afterCoerced = semver.coerce(afterVersion);
    if (!beforeCoerced || !afterCoerced) {
      continue;
    }
    if (semver.major(beforeCoerced) === semver.major(afterCoerced)) {
      continue;
    }
    jumped.push(descriptor);
  }
  if (!jumped.length) {
    return { pinned: false, pins: [] };
  }

  const npmVersions = await fetchVersions(packageName);
  const pins = majorJumpPins(semver, beforeMap, afterMap, npmVersions);
  if (!pins.length) {
    return { pinned: false, pins: [], jumpedDescriptors: jumped };
  }

  for (const pin of pins) {
    await runYarn([
      'set',
      'resolution',
      pin.descriptor,
      `npm:${pin.targetVersion}`,
    ]);
  }
  return { pinned: true, pins };
}
