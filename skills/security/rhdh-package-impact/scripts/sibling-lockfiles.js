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
 * Cross-lockfile helpers for release-1.10 dual lockfile (see
 * release-1.10-dual-lockfile.js — REMOVE WHEN release-1.10 is EOL).
 */

import { readFile } from 'fs/promises';

import { leftoverVersions } from './cve-version-status.js';
import { dualLockfilePaths } from './release-1.10-dual-lockfile.js';

/**
 * Collect unique resolved versions of packageName from a Yarn Berry lockfile.
 */
export function resolvedVersionsFromLockfile(lockfileText, packageName) {
  const escaped = String(packageName).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const blockRe = new RegExp(
    `(?:^|\\n)(?:"?${escaped}@[^:\\n]+"?(?:,\\s*"?${escaped}@[^:\\n]+"?)*:)([\\s\\S]*?)(?=\\n[^\\s]|\\n?$)`,
    'g',
  );
  const versions = new Set();
  let match;
  while ((match = blockRe.exec(lockfileText)) !== null) {
    const versionMatch = match[1].match(/^\s+version:\s+(.+)$/m);
    if (versionMatch) {
      versions.add(versionMatch[1].trim().replace(/^"|"$/g, ''));
    }
  }
  return [...versions].sort();
}

/**
 * Compare product Dependabot packages against the release-1.10 sibling
 * lockfile. Status keys off resolved versions + advisory ranges.
 */
export async function auditSiblingLockfiles({
  repoRoot,
  packageNames,
  alertsByPackage = {},
  productVersionsByPackage = {},
  semver = null,
}) {
  const sibling = dualLockfilePaths(repoRoot);
  if (!sibling || !packageNames?.length) {
    return {
      siblings: sibling ? [summarizeSibling(sibling)] : [],
      gaps: [],
      needsBump: [],
    };
  }

  const siblingText = await readFile(sibling.lockPath, 'utf8');
  const gaps = [];

  for (const packageName of packageNames) {
    const alerts = alertsByPackage[packageName] || [];
    const productVersions = productVersionsByPackage[packageName] || [];
    const siblingVersions = resolvedVersionsFromLockfile(
      siblingText,
      packageName,
    );

    if (!siblingVersions.length) {
      gaps.push({
        package: packageName,
        sibling: sibling.name,
        lockfileRel: sibling.lockfileRel,
        status: 'n/a',
        productVersions,
        siblingVersions: [],
        remaining: [],
        note: 'not in sibling lockfile',
      });
      continue;
    }

    const remaining =
      semver && alerts.length
        ? leftoverVersions(semver, alerts, siblingVersions)
        : [];
    const status = remaining.length
      ? 'needs bump'
      : alerts.length
        ? 'ok'
        : 'present';

    gaps.push({
      package: packageName,
      sibling: sibling.name,
      lockfileRel: sibling.lockfileRel,
      status,
      productVersions,
      siblingVersions,
      remaining,
      note:
        status === 'needs bump'
          ? `sibling still in advisory range (${remaining.join(', ')})`
          : status === 'ok'
            ? 'sibling versions outside advisory ranges'
            : 'present (no advisories to score)',
    });
  }

  return {
    siblings: [summarizeSibling(sibling)],
    gaps,
    needsBump: gaps.filter(g => g.status === 'needs bump'),
  };
}

function summarizeSibling(sib) {
  return {
    name: sib.name,
    lockfileRel: sib.lockfileRel,
    yarnCwdRel: sib.yarnCwdRel,
    alertPrefix: sib.alertPrefix,
  };
}

export function formatSiblingGapTable(gaps) {
  if (!gaps?.length) {
    return 'No sibling lockfile gaps to report.';
  }
  const headers = [
    'package',
    'sibling',
    'status',
    'product_versions',
    'sibling_versions',
    'remaining',
  ];
  const lines = [
    `| ${headers.join(' | ')} |`,
    `| ${headers.map(() => '---').join(' | ')} |`,
  ];
  for (const row of gaps) {
    lines.push(
      `| ${[
        row.package,
        row.sibling,
        row.status,
        (row.productVersions || []).join(', ') || '-',
        (row.siblingVersions || []).join(', ') || '-',
        (row.remaining || []).join(', ') || '-',
      ].join(' | ')} |`,
    );
  }
  return lines.join('\n');
}
