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

import { execFile as execFileCb } from 'child_process';
import { createRequire } from 'module';
import { existsSync } from 'fs';
import { readFile, writeFile } from 'fs/promises';
import { resolve as resolvePath } from 'path';
import { promisify } from 'util';

import { isSkippedBumpPackage } from './bump-skip.js';
import { isNoMajorBumpPackage, pinMajorJumps } from './same-major-yarn-up.js';
import { leftoverVersions, cveLeftoverCleared } from './cve-version-status.js';
import { loadDependabotAlerts } from './dependabot-alerts.js';
import { filterAlertsForLayout, resolveRepoLayout } from './repo-layout.js';

const execFile = promisify(execFileCb);
const NPM_PKG_RE = /((?:@[^/\s]+\/)?[^\s@[]+)@npm:/;

function usage() {
  console.error(`Usage: bump-package-ancestors.js [options] <workspace> <package>

Advanced: leftover parent-chain bumps after yarn up -R.

Allowlisted leftovers (see ancestor-allowlist.js) are invoked automatically
from bump-workspace-packages.js when yarn up -R leaves a CVE leftover. Do
not run this script for other packages unless the user explicitly asks.

Walks the ancestor chain from yarn why -R when yarn up -R leaves a leftover
held by a parent (a second resolved line, or a single unpatched pin).
Success is CVE leftover gone (Dependabot ranges); more than one patched
resolved line is OK. Reverts lockfile collateral when parent bumps do not
clear the leftover. Parent and target yarn up -R calls use bare
package names (Yarn forbids ranges with -R). Known no-major-bump packages
(currently http-proxy-middleware) are re-pinned if they major-jump.

For simple yarn up -R with a CVE summary table, use bump-workspace-packages.js.

Complex cases (e.g. fast-xml-parser dual-major lines, yarn set resolution)
are out of scope — handle those manually.

Options:
  --repo-root <path>     Local checkout (plugins monorepo or rhdh core)
  --repo <owner/name>    GitHub repo for Dependabot leftover ranges (default: auto-detect)
  --alerts-json <file>   Snapshot of GitHub Dependabot alert objects (no token)
  --max-parents <number> Max parent packages to try per depth tier (default: 8)
  --max-depth <number>   Max ancestor depth from target (default: 2)
  --fast                 Shorthand for --max-depth 1 --max-parents 4
  --json                 Print machine-readable result
  --dry-run              Analyze and print planned updates, but do not run yarn up
  -h, --help             Show this help

Examples:
  node bump-package-ancestors.js homepage js-cookie --json
  node bump-package-ancestors.js --repo-root /path/to/plugins-repo boost uuid --fast
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const options = {
    repoRoot: undefined,
    repo: undefined,
    alertsJson: undefined,
    maxParents: 8,
    maxDepth: 2,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--json') {
      flags.add('json');
    } else if (arg === '--dry-run') {
      flags.add('dry-run');
    } else if (arg === '--fast') {
      flags.add('fast');
    } else if (arg === '-h' || arg === '--help') {
      flags.add('help');
    } else if (arg === '--repo-root') {
      options.repoRoot = argv[++i];
      if (!options.repoRoot) {
        throw new Error('--repo-root requires a path');
      }
    } else if (arg === '--repo') {
      options.repo = argv[++i];
      if (!options.repo) {
        throw new Error('--repo requires owner/name');
      }
    } else if (arg === '--alerts-json') {
      options.alertsJson = argv[++i];
      if (!options.alertsJson) {
        throw new Error('--alerts-json requires a file path');
      }
    } else if (arg === '--max-parents') {
      const raw = argv[++i];
      const parsed = Number(raw);
      if (!raw || !Number.isInteger(parsed) || parsed < 1) {
        throw new Error('--max-parents must be a positive integer');
      }
      options.maxParents = parsed;
    } else if (arg === '--max-depth') {
      const raw = argv[++i];
      const parsed = Number(raw);
      if (!raw || !Number.isInteger(parsed) || parsed < 1) {
        throw new Error('--max-depth must be a positive integer');
      }
      options.maxDepth = parsed;
    } else if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
  }

  if (flags.has('fast')) {
    options.maxDepth = 1;
    options.maxParents = 4;
  }

  return { flags, options, positional };
}

async function resolveYarnInvocation(repoRoot) {
  const yarnrcPath = resolvePath(repoRoot, '.yarnrc.yml');
  if (!existsSync(yarnrcPath)) {
    return { command: 'yarn', argsPrefix: [] };
  }
  const yarnrc = await readFile(yarnrcPath, 'utf8');
  const match = yarnrc.match(/^yarnPath:\s*(.+)$/m);
  if (!match) {
    return { command: 'yarn', argsPrefix: [] };
  }
  const yarnPath = match[1].trim().replace(/^["']|["']$/g, '');
  const yarnScript = resolvePath(repoRoot, yarnPath);
  if (!existsSync(yarnScript)) {
    return { command: 'yarn', argsPrefix: [] };
  }
  return { command: process.execPath, argsPrefix: [yarnScript] };
}

async function runYarn(repoRoot, cwd, args) {
  const { command, argsPrefix } = await resolveYarnInvocation(repoRoot);
  const { stdout, stderr } = await execFile(
    command,
    [...argsPrefix, '--cwd', cwd, ...args],
    { cwd: repoRoot, maxBuffer: 20 * 1024 * 1024 },
  );
  return { stdout, stderr };
}

function yarnFailureMessage(error) {
  return error.stderr?.toString().trim() || error.message;
}

async function runYarnWhy(repoRoot, workspaceDir, packageName) {
  try {
    const { stdout } = await runYarn(repoRoot, workspaceDir, ['why', '-R', packageName]);
    if (!stdout.trim()) {
      throw new Error(
        'yarn why returned no output; run `yarn install` in the workspace first',
      );
    }
    return stdout;
  } catch (error) {
    throw new Error(`yarn why -R ${packageName} failed: ${yarnFailureMessage(error)}`);
  }
}

function resolvedVersionsFromLockfile(lockfileText, packageName) {
  const versions = new Set();
  const escaped = packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const blockRe = new RegExp(`^"${escaped}@[^"]+":\\n((?:  .*\\n)*)`, 'gm');
  let match;
  while ((match = blockRe.exec(lockfileText)) !== null) {
    const ver = match[1].match(/^  version: (.+)$/m);
    if (ver) {
      versions.add(ver[1].trim().replace(/^["']|["']$/g, ''));
    }
  }
  return [...versions].sort();
}

function packageVersionFromLockfile(lockfileText, packageName) {
  const versions = resolvedVersionsFromLockfile(lockfileText, packageName);
  return versions.length === 1 ? versions[0] : null;
}

/** Direct lockfile dependents when yarn why is unavailable (e.g. after failed install). */
function parentDepSpecFromLockfile(lockfileText, parent, packageName) {
  const escapedParent = parent.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const blockRe = new RegExp(
    `"${escapedParent}@npm:[^"]*":\\n((?:  .*\\n)*)`,
    'm',
  );
  const match = lockfileText.match(blockRe);
  if (!match) {
    return null;
  }
  const escapedPkg = packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const depMatch = match[1].match(
    new RegExp(`^    ${escapedPkg}: "npm:([^"]+)"`, 'm'),
  );
  return depMatch ? depMatch[1] : null;
}

function parentLeftoverScore(semver, lockfileText, parent, packageName, leftovers) {
  const depSpec = parentDepSpecFromLockfile(lockfileText, parent, packageName);
  if (!depSpec || !leftovers.length) {
    return 0;
  }
  let score = 0;
  for (const version of leftovers) {
    const coerced = semver.coerce(version)?.version;
    if (!coerced) {
      continue;
    }
    try {
      if (semver.satisfies(coerced, depSpec, { includePrerelease: true })) {
        score += 1;
      }
    } catch {
      // ignore unparseable ranges
    }
  }
  return score;
}

function rankParentsByLeftoverHold({
  semver,
  lockfileText,
  packageName,
  parents,
  leftovers,
}) {
  return [...parents].sort((left, right) => {
    const leftScore = parentLeftoverScore(
      semver,
      lockfileText,
      left,
      packageName,
      leftovers,
    );
    const rightScore = parentLeftoverScore(
      semver,
      lockfileText,
      right,
      packageName,
      leftovers,
    );
    if (leftScore !== rightScore) {
      return rightScore - leftScore;
    }
    return left.localeCompare(right);
  });
}

function findLockfileParents(lockfileText, packageName) {
  const parents = new Set();
  const escapedDep = packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const depLineRe = new RegExp(`^    ${escapedDep}: "npm:[^"]+"`, 'm');
  const blockRe = /^"([^"]+)":\n((?:  .*\n)*)/gm;
  let match;
  while ((match = blockRe.exec(lockfileText)) !== null) {
    const header = match[1];
    const body = match[2];
    if (!depLineRe.test(body)) {
      continue;
    }
    for (const part of header.split(', ')) {
      const pkgMatch = part.match(NPM_PKG_RE);
      if (
        pkgMatch &&
        pkgMatch[1] !== packageName &&
        !isDisallowedParentPackage(pkgMatch[1])
      ) {
        parents.add(pkgMatch[1]);
      }
    }
  }
  return [...parents].sort();
}

async function ensureWorkspaceInstall(repoRoot, workspaceDir) {
  let retried = false;
  let lastError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await runYarn(repoRoot, workspaceDir, ['install']);
      return { ok: true, error: null, retried };
    } catch (error) {
      lastError = yarnFailureMessage(error);
      retried = attempt > 0;
    }
  }
  return { ok: false, error: lastError, retried };
}

function extractResolvedVersions(whyOutput, packageName) {
  const escaped = packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`${escaped}@npm:([^\\s,]+)`, 'g');
  const versions = new Set();
  let match;
  while ((match = re.exec(whyOutput)) !== null) {
    versions.add(match[1]);
  }
  return [...versions].sort();
}

function parseWhyRootTrees(output) {
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

function extractNpmPackage(line) {
  const match = line.match(NPM_PKG_RE);
  return match ? match[1] : null;
}

function parseTreeDepth(line) {
  const match = line.match(/^((?:│  |   )*)(?:├─|└─) /);
  if (!match) {
    return null;
  }
  return Math.floor(match[1].length / 3);
}

function findParentsByDepth(whyOutput, packageName) {
  const trees = parseWhyRootTrees(whyOutput);
  const byDepth = new Map();
  const targetMarker = `${packageName}@npm:`;

  for (const tree of trees) {
    const stackByDepth = [];

    for (let i = 0; i < tree.lines.length; i += 1) {
      const line = tree.lines[i];
      const depth = parseTreeDepth(line);
      if (depth === null) {
        continue;
      }

      const pkg = extractNpmPackage(line);
      stackByDepth[depth] = pkg || null;
      stackByDepth.length = depth + 1;

      if (!line.includes(targetMarker)) {
        continue;
      }

      for (let d = 1; d <= depth; d += 1) {
        const ancestor = stackByDepth[depth - d];
        if (!ancestor || ancestor === packageName) {
          continue;
        }
        if (!byDepth.has(d)) {
          byDepth.set(d, new Set());
        }
        byDepth.get(d).add(ancestor);
      }
    }
  }

  return byDepth;
}

function isDisallowedParentPackage(packageName) {
  return isSkippedBumpPackage(packageName);
}

function loadSemver(repoRoot) {
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

async function updatePackage(repoRoot, workspaceDir, packageName, semver) {
  const lockPath = resolvePath(workspaceDir, 'yarn.lock');
  const lockBefore = await readFile(lockPath, 'utf8');
  const versionBefore = packageVersionFromLockfile(lockBefore, packageName);
  try {
    await runYarn(repoRoot, workspaceDir, ['up', '-R', packageName]);
  } catch (error) {
    throw new Error(
      `yarn up -R ${packageName} failed: ${yarnFailureMessage(error)}`,
    );
  }
  let lockAfter = await readFile(lockPath, 'utf8');
  const versionAfterRecursive = packageVersionFromLockfile(lockAfter, packageName);
  if (versionBefore && versionAfterRecursive === versionBefore) {
    try {
      await runYarn(repoRoot, workspaceDir, ['up', packageName]);
      lockAfter = await readFile(lockPath, 'utf8');
    } catch (error) {
      throw new Error(
        `yarn up ${packageName} failed after -R made no change: ${yarnFailureMessage(error)}`,
      );
    }
  }
  if (!isNoMajorBumpPackage(packageName)) {
    return;
  }
  await pinMajorJumps({
    semver,
    packageName,
    lockfileBefore: lockBefore,
    lockfileAfter: lockAfter,
    runYarn: args => runYarn(repoRoot, workspaceDir, args),
  });
}

async function refreshLockfileResilient(repoRoot, workspaceDir) {
  const install = await ensureWorkspaceInstall(repoRoot, workspaceDir);
  if (!install.ok) {
    return {
      ok: false,
      installError: install.error,
      installRetried: install.retried,
      dedupeError: null,
    };
  }
  try {
    await runYarn(repoRoot, workspaceDir, ['dedupe']);
    return { ok: true, installError: null, installRetried: install.retried, dedupeError: null };
  } catch (error) {
    return {
      ok: false,
      installError: null,
      installRetried: install.retried,
      dedupeError: yarnFailureMessage(error),
    };
  }
}

function versionsEqual(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] !== right[i]) {
      return false;
    }
  }
  return true;
}

function summarizeAlert(alert) {
  const vuln = alert.security_vulnerability ?? {};
  return {
    vulnerableRange: vuln.vulnerable_version_range ?? null,
    firstPatched: vuln.first_patched_version?.identifier ?? null,
    ghsa: alert.security_advisory?.ghsa_id ?? null,
    cve: alert.security_advisory?.cve_id ?? null,
  };
}

async function loadPackageAlerts({
  layout,
  packageName,
  explicitRepo,
  alertsJson,
}) {
  try {
    const { alerts: all } = await loadDependabotAlerts({
      alertsJson,
      explicitRepo: explicitRepo || layout.defaultDependabotRepo,
      cwd: layout.repoRoot,
      state: 'open',
      requiredFor: 'Dependabot leftover ranges',
    });
    return filterAlertsForLayout(all, layout, packageName).map(summarizeAlert);
  } catch {
    return [];
  }
}

function isUpdateComplete(versionsBefore, versionsAfter, semver, alerts) {
  const cleared = cveLeftoverCleared(
    semver,
    alerts,
    versionsBefore,
    versionsAfter,
  );
  if (cleared === true) {
    return true;
  }
  if (cleared === false) {
    return false;
  }
  if (versionsEqual(versionsBefore, versionsAfter)) {
    return false;
  }
  return versionsAfter.length <= 1;
}

function hasDisallowedOnlyParents(whyOutput, packageName, maxDepth) {
  let sawAnyParent = false;
  const byDepth = findParentsByDepth(whyOutput, packageName);
  for (let depth = 1; depth <= maxDepth; depth += 1) {
    for (const parent of byDepth.get(depth) || []) {
      sawAnyParent = true;
      if (!isDisallowedParentPackage(parent)) {
        return false;
      }
    }
  }
  return sawAnyParent;
}

function getCandidatesForDepth({
  whyOutput,
  lockfileText,
  packageName,
  depth,
  maxParents,
  visitedParents,
  semver,
  alerts,
  versionsCurrent,
}) {
  const byDepth = findParentsByDepth(whyOutput || '', packageName);
  let candidates = [...(byDepth.get(depth) || [])];
  if (!candidates.length && depth === 1 && lockfileText) {
    candidates = findLockfileParents(lockfileText, packageName);
  }
  const filtered = candidates
    .filter(parent => !isDisallowedParentPackage(parent))
    .filter(parent => !visitedParents.has(parent));
  const leftovers = leftoverVersions(semver, alerts, versionsCurrent);
  return rankParentsByLeftoverHold({
    semver,
    lockfileText,
    packageName,
    parents: filtered,
    leftovers,
  }).slice(0, maxParents);
}

async function readTargetState(repoRoot, workspaceDir, packageName, lockPath) {
  const lockfileText = await readFile(lockPath, 'utf8');
  let why = '';
  let whyError = null;
  try {
    why = await runYarnWhy(repoRoot, workspaceDir, packageName);
  } catch (error) {
    whyError = yarnFailureMessage(error);
  }
  const fromWhy = why ? extractResolvedVersions(why, packageName) : [];
  const versions = fromWhy.length
    ? fromWhy
    : resolvedVersionsFromLockfile(lockfileText, packageName);
  return { why, versions, lockfileText, whyError };
}

async function snapshotLockfile(lockPath) {
  return readFile(lockPath, 'utf8');
}

async function restoreLockfile(lockPath, content) {
  await writeFile(lockPath, content, 'utf8');
}

async function main() {
  const { flags, options, positional } = parseArgs(process.argv.slice(2));
  if (flags.has('help')) {
    usage();
    process.exit(0);
  }
  if (positional.length !== 2) {
    usage();
    process.exit(1);
  }

  const [workspaceInput, packageName] = positional;
  const layout = resolveRepoLayout({
    explicitRoot: options.repoRoot,
    workspaceInput,
    explicitRepo: options.repo,
    requireCheckout: true,
  });
  const workspace = layout.workspace;
  const repoRoot = layout.repoRoot;
  const workspaceDir = layout.workspaceDir;
  const lockPath = layout.lockPath;

  if (isSkippedBumpPackage(packageName)) {
    const result = {
      workspace,
      package: packageName,
      repoRoot,
      dryRun: flags.has('dry-run'),
      skipped: true,
      skipReason: 'backstage_denylist',
      versionsBefore: [],
      versionsAfter: [],
      complete: false,
      blockedReason: 'backstage_denylist',
      attempts: [{ type: 'skipped', reason: 'backstage_denylist' }],
    };
    if (flags.has('json')) {
      console.log(JSON.stringify(result, null, 2));
      return;
    }
    console.log(`Workspace: ${workspace}`);
    console.log(`Package:   ${packageName}`);
    console.log('Skipped:   backstage_denylist (@backstage/* / @backstage-community/*)');
    return;
  }

  const semver = loadSemver(repoRoot);
  const alerts = await loadPackageAlerts({
    layout,
    packageName,
    explicitRepo: options.repo,
    alertsJson: options.alertsJson,
  });

  const dryRun = flags.has('dry-run');
  const fast = flags.has('fast');
  let prepInstallError = null;
  let prepInstallRetried = false;
  if (!dryRun) {
    const prep = await ensureWorkspaceInstall(repoRoot, workspaceDir);
    prepInstallError = prep.error;
    prepInstallRetried = prep.retried;
  }

  let {
    why: beforeWhy,
    versions: versionsBefore,
    lockfileText,
    whyError: initialWhyError,
  } = await readTargetState(repoRoot, workspaceDir, packageName, lockPath);
  if (!versionsBefore.length) {
    const result = {
      workspace,
      package: packageName,
      repoRoot,
      dryRun,
      error: initialWhyError || `no resolved ${packageName} versions in lockfile`,
      versionsBefore: [],
      versionsAfter: [],
      complete: false,
      blockedReason: 'no_target_versions',
      attempts: [{ type: 'blocked', reason: 'no_target_versions' }],
    };
    if (flags.has('json')) {
      console.log(JSON.stringify(result, null, 2));
      return;
    }
    console.error(`Error: ${result.error}`);
    process.exit(1);
  }

  const attempts = [];
  let blockedReason = null;

  let currentWhy = beforeWhy;
  let lockfileSnapshot = lockfileText;
  let versionsCurrent = [...versionsBefore];
  let currentWhyError = initialWhyError;

  const isComplete = versions =>
    isUpdateComplete(versionsBefore, versions, semver, alerts);

  if (!dryRun) {
    try {
      await updatePackage(repoRoot, workspaceDir, packageName, semver);
      attempts.push({ type: 'target', package: packageName });
    } catch (error) {
      attempts.push({
        type: 'target',
        package: packageName,
        error: yarnFailureMessage(error),
      });
    }
    ({
      why: currentWhy,
      versions: versionsCurrent,
      lockfileText: lockfileSnapshot,
      whyError: currentWhyError,
    } = await readTargetState(repoRoot, workspaceDir, packageName, lockPath));
  } else {
    attempts.push({ type: 'target', package: packageName, skipped: true });
  }
  const versionsAfterTarget = [...versionsCurrent];

  const visitedParents = new Set();
  const attemptedParentsByDepth = {};
  let lockfileBeforeParents = null;
  let parentBumpsRan = false;
  let reverted = false;

  if (!blockedReason && !isComplete(versionsCurrent)) {
    if (!dryRun) {
      lockfileBeforeParents = await snapshotLockfile(lockPath);
    }

    for (let depth = 1; depth <= options.maxDepth; depth += 1) {
      const parents = getCandidatesForDepth({
        whyOutput: currentWhy,
        lockfileText: lockfileSnapshot,
        packageName,
        depth,
        maxParents: options.maxParents,
        visitedParents,
        semver,
        alerts,
        versionsCurrent,
      });
      attemptedParentsByDepth[depth] = parents;

      if (!parents.length) {
        continue;
      }

      for (const parent of parents) {
        visitedParents.add(parent);

        if (dryRun) {
          attempts.push({ type: 'parent', depth, package: parent, skipped: true });
          attempts.push({
            type: 'target-retry',
            depth,
            package: packageName,
            skipped: true,
          });
          continue;
        }

        let parentError = null;
        try {
          await updatePackage(repoRoot, workspaceDir, parent, semver);
        } catch (error) {
          parentError = yarnFailureMessage(error);
        }
        attempts.push({
          type: 'parent',
          depth,
          package: parent,
          error: parentError,
        });
        if (parentError) {
          continue;
        }
        parentBumpsRan = true;

        let targetRetryError = null;
        try {
          await updatePackage(repoRoot, workspaceDir, packageName, semver);
        } catch (error) {
          targetRetryError = yarnFailureMessage(error);
        }
        attempts.push({
          type: 'target-retry',
          depth,
          package: packageName,
          error: targetRetryError,
        });
        ({
          why: currentWhy,
          versions: versionsCurrent,
          lockfileText: lockfileSnapshot,
          whyError: currentWhyError,
        } = await readTargetState(repoRoot, workspaceDir, packageName, lockPath));

        if (isComplete(versionsCurrent)) {
          break;
        }
      }

      if (isComplete(versionsCurrent)) {
        break;
      }
    }

    if (
      !dryRun &&
      fast &&
      !isComplete(versionsCurrent) &&
      visitedParents.size > 0 &&
      versionsEqual(versionsCurrent, versionsAfterTarget)
    ) {
      blockedReason = 'no_progress';
      attempts.push({ type: 'blocked', reason: blockedReason });
    } else if (
      !dryRun &&
      fast &&
      !isComplete(versionsCurrent) &&
      visitedParents.size === 0 &&
      hasDisallowedOnlyParents(currentWhy, packageName, options.maxDepth)
    ) {
      blockedReason = 'backstage_blocked';
      attempts.push({ type: 'blocked', reason: blockedReason });
    }
  }

  if (
    !dryRun &&
    parentBumpsRan &&
    !isComplete(versionsCurrent) &&
    lockfileBeforeParents
  ) {
    const leftoverAfterTarget = leftoverVersions(
      semver,
      alerts,
      versionsAfterTarget,
    );
    const leftoverNow = leftoverVersions(semver, alerts, versionsCurrent);
    const reducedLeftover =
      leftoverAfterTarget.length > 0 &&
      leftoverNow.length < leftoverAfterTarget.length;
    if (reducedLeftover) {
      attempts.push({
        type: 'keep_partial',
        reason: 'cve_leftover_reduced',
      });
    } else {
      await restoreLockfile(lockPath, lockfileBeforeParents);
      reverted = true;
      attempts.push({ type: 'revert', reason: 'incomplete_parent_bumps' });
      ({
        why: currentWhy,
        versions: versionsCurrent,
        lockfileText: lockfileSnapshot,
        whyError: currentWhyError,
      } = await readTargetState(repoRoot, workspaceDir, packageName, lockPath));
    }
  }

  let refreshInstallError = null;
  let refreshDedupeError = null;
  let refreshInstallRetried = false;
  if (
    !dryRun &&
    !reverted &&
    isComplete(versionsCurrent) &&
    attempts.some(a => !a.skipped && a.type !== 'revert' && !a.error)
  ) {
    const refresh = await refreshLockfileResilient(repoRoot, workspaceDir);
    refreshInstallError = refresh.installError;
    refreshDedupeError = refresh.dedupeError;
    refreshInstallRetried = refresh.installRetried;
    attempts.push({
      type: 'install',
      error: refresh.installError,
      retried: refresh.installRetried,
    });
    attempts.push({ type: 'dedupe', error: refresh.dedupeError });
    ({
      why: currentWhy,
      versions: versionsCurrent,
      lockfileText: lockfileSnapshot,
      whyError: currentWhyError,
    } = await readTargetState(repoRoot, workspaceDir, packageName, lockPath));
  }

  const result = {
    workspace,
    package: packageName,
    repoRoot,
    dryRun,
    fast,
    versionsBefore,
    versionsAfter: versionsCurrent,
    leftoverAfter: leftoverVersions(semver, alerts, versionsCurrent),
    complete: isComplete(versionsCurrent),
    reverted,
    blockedReason,
    prepInstallError,
    prepInstallRetried,
    refreshInstallError,
    refreshInstallRetried,
    refreshDedupeError,
    yarnWhyError: currentWhyError,
    usedLockfileFallback: Boolean(currentWhyError || initialWhyError),
    maxDepth: options.maxDepth,
    maxParents: options.maxParents,
    attemptedParentsByDepth,
    attemptedParents: [...visitedParents].sort(),
    attempts,
  };

  if (flags.has('json')) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  console.log(`Workspace: ${workspace}`);
  console.log(`Package:   ${packageName}`);
  console.log(`Before:    ${versionsBefore.join(', ') || '(none found)'}`);
  console.log(`After:     ${versionsCurrent.join(', ') || '(none found)'}`);
  console.log(`Complete:  ${result.complete ? 'yes' : 'no'}`);
  if (result.blockedReason) {
    console.log(`Blocked:   ${result.blockedReason}`);
  }
  if (result.reverted) {
    console.log('Reverted:  yes (parent bumps did not complete the target update)');
  }
  console.log('');
  if (result.attemptedParents.length) {
    console.log(
      `Parent candidates (${result.attemptedParents.length}): ${result.attemptedParents.join(', ')}`,
    );
  } else {
    console.log('Parent candidates: none detected');
  }
  console.log('Attempts:');
  for (const a of attempts) {
    const suffix = a.skipped ? ' (dry-run)' : '';
    const depth = a.depth ? ` [depth ${a.depth}]` : '';
    const label =
      a.type === 'install'
        ? 'install'
        : a.type === 'dedupe'
          ? 'dedupe'
          : a.type === 'revert'
            ? `revert (${a.reason})`
            : `${a.type}: ${a.package}`;
    console.log(`  - ${label}${depth}${suffix}`);
  }
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
