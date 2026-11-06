#!/usr/bin/env node
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

import { createRequire } from 'module';
import { existsSync } from 'fs';
import { readFile } from 'fs/promises';
import { resolve as resolvePath } from 'path';

import {
  compactAlerts,
  formatAdvisoryId,
  formatRemainingLabel,
  leftoverVersions,
} from './cve-version-status.js';

function usage() {
  console.error(`Usage: format-bump-pr.js [options] [bump.json]

Reads bump-workspace-packages.js --json (file, or stdin) and prints PR
markdown: Fully fixed / Partial leftovers / Unchanged tables.

Skipped denylist packages (@backstage/* / @backstage-community/*) are omitted.

Options:
  --title        Print only the PR title
  --with-title   Print title, then the PR body
  -h, --help     Show this help

Examples:
  node bump-workspace-packages.js --repo-root /path/to/plugins-repo <ws> --json \\
    | node format-bump-pr.js
  node format-bump-pr.js --with-title bump.json
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const positional = [];

  for (const arg of argv) {
    if (arg === '--title') {
      flags.add('title');
    } else if (arg === '--with-title') {
      flags.add('with-title');
    } else if (arg === '-h' || arg === '--help') {
      flags.add('help');
    } else if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
  }

  return { flags, positional };
}

function loadSemver(repoRoot) {
  if (!repoRoot) {
    throw new Error('bump JSON is missing repoRoot; cannot load semver');
  }
  const require = createRequire(resolvePath(repoRoot, 'package.json'));
  try {
    return require('semver');
  } catch {
    try {
      return require(resolvePath(repoRoot, 'node_modules/semver/index.js'));
    } catch {
      throw new Error(
        'semver package not found in repo checkout; run yarn install at repo root',
      );
    }
  }
}

async function readInput(filePath) {
  if (filePath && filePath !== '-') {
    return readFile(resolvePath(filePath), 'utf8');
  }
  if (process.stdin.isTTY) {
    usage();
    process.exit(1);
  }
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

function escapeMarkdownCell(value) {
  return String(value ?? '')
    .replace(/\|/g, '\\|')
    .replace(/\n/g, ' ');
}

function printMarkdownTable(headers, rows) {
  console.log(`| ${headers.join(' | ')} |`);
  console.log(`| ${headers.map(() => '---').join(' | ')} |`);
  for (const row of rows) {
    console.log(`| ${row.map(escapeMarkdownCell).join(' | ')} |`);
  }
}

function versionsCell(versions) {
  return (versions || []).join(', ') || '-';
}

function prTitle(workspace) {
  return `fix(${workspace}): bump yarn.lock packages for Dependabot CVEs`;
}

function remainingForRow(row, semver) {
  if (Array.isArray(row.remaining) && row.remaining.length) {
    return row.remaining;
  }
  return leftoverVersions(semver, row.alerts || [], row.versionsAfter || []);
}

function remainingCell(row, semver) {
  if (row.status === 'error' && row.yarnError) {
    return row.yarnError;
  }
  return formatRemainingLabel({
    semver,
    versionsBefore: row.versionsBefore,
    versionsAfter: row.versionsAfter,
    remaining: remainingForRow(row, semver),
    firstPatched: row.firstPatched,
  });
}

function cvesClearedCell(row) {
  const alerts = row.alerts || [];
  const labels = (row.cvesFixed || []).map(id => formatAdvisoryId(id, alerts));
  return labels.join(', ') || '-';
}

function versionsMoved(row) {
  const before = row.versionsBefore || [];
  const after = row.versionsAfter || [];
  if (before.length !== after.length) {
    return true;
  }
  return before.some((version, i) => version !== after[i]);
}

function isFullyFixed(row, semver) {
  if (row.status === 'fixed') {
    return true;
  }
  if (row.status === 'updated') {
    return remainingForRow(row, semver).length === 0;
  }
  return false;
}

function isPartialLeftover(row, semver) {
  if (isFullyFixed(row, semver) || row.status === 'error') {
    return false;
  }
  if (row.status === 'partial') {
    return true;
  }
  if (row.status === 'updated') {
    return remainingForRow(row, semver).length > 0;
  }
  return versionsMoved(row) && remainingForRow(row, semver).length > 0;
}

function isUnchangedLeftover(row, semver) {
  if (isFullyFixed(row, semver) || isPartialLeftover(row, semver)) {
    return false;
  }
  if (row.status === 'unchanged' || row.status === 'error') {
    return true;
  }
  return !versionsMoved(row) && remainingForRow(row, semver).length > 0;
}

function leftoverTableRows(rows, semver) {
  return rows.map(row => [
    row.package,
    versionsCell(row.versionsBefore),
    versionsCell(row.versionsAfter),
    remainingCell(row, semver),
  ]);
}

function printSection(heading, headers, rows) {
  console.log(`## ${heading}`);
  console.log('');
  if (!rows.length) {
    console.log('None.');
    return;
  }
  printMarkdownTable(headers, rows);
}

async function main() {
  const { flags, positional } = parseArgs(process.argv.slice(2));
  if (flags.has('help')) {
    usage();
    process.exit(0);
  }
  if (positional.length > 1) {
    usage();
    process.exit(1);
  }

  const raw = await readInput(positional[0]);
  let output;
  try {
    output = JSON.parse(raw);
  } catch {
    throw new Error('input is not valid JSON from bump-workspace-packages.js --json');
  }
  if (!output || !Array.isArray(output.results)) {
    throw new Error('JSON is missing results[]; expected bump-workspace-packages.js --json');
  }

  const workspace = output.workspace || 'workspace';
  const title = prTitle(workspace);

  if (flags.has('title')) {
    console.log(title);
    return;
  }

  let semver = null;
  const repoRoot = output.repoRoot;
  if (repoRoot && existsSync(resolvePath(repoRoot, 'package.json'))) {
    semver = loadSemver(repoRoot);
  }

  const rows = output.results
    .filter(row => row.status !== 'skipped' && row.status !== 'dry-run')
    .map(row => ({
      ...row,
      alerts: compactAlerts(row.alerts),
    }));

  const fullyFixed = rows.filter(row => isFullyFixed(row, semver));
  const partial = rows.filter(row => isPartialLeftover(row, semver));
  const unchanged = rows.filter(row => isUnchangedLeftover(row, semver));

  if (flags.has('with-title')) {
    console.log(title);
    console.log('');
  }

  console.log('## Summary');
  console.log('');
  console.log(
    `- \`yarn up -R\` on \`workspaces/${workspace}\` for open Dependabot alert packages, then \`yarn install\` and \`yarn dedupe\`.`,
  );
  const pairAdded = Array.isArray(output.reactRouterPairAdded)
    ? output.reactRouterPairAdded
    : [];
  if (pairAdded.length || output.reactRouterPairAlign?.aligned) {
    console.log(
      `- Keep \`react-router\` / \`react-router-dom\` on the same patch (co-bump` +
        (pairAdded.length ? `; auto-included ${pairAdded.join(', ')}` : '') +
        (output.reactRouterPairAlign?.aligned
          ? '; aligned via yarn set resolution'
          : '') +
        ').',
    );
  }
  console.log('');

  printSection(
    'Fully fixed',
    ['package', 'before', 'after', 'CVEs cleared'],
    fullyFixed.map(row => [
      row.package,
      versionsCell(row.versionsBefore),
      versionsCell(row.versionsAfter),
      cvesClearedCell(row),
    ]),
  );
  console.log('');
  printSection(
    'Partial leftovers',
    ['package', 'before', 'after', 'remaining'],
    leftoverTableRows(partial, semver),
  );
  console.log('');
  printSection(
    'Unchanged',
    ['package', 'before', 'after', 'remaining'],
    leftoverTableRows(unchanged, semver),
  );
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
