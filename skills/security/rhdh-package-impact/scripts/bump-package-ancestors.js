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

const execFile = promisify(execFileCb);
const NPM_PKG_RE = /((?:@[^/\s]+\/)?[^\s@[]+)@npm:/;

function usage() {
  console.error(`Usage: bump-package-ancestors.js [options] <workspace> <package>

Advanced: leftover parent-chain bumps after yarn up -R.

Allowlisted leftovers (qs) are invoked automatically from
bump-workspace-packages.js. Do not run this script for other packages
unless the user explicitly asks.

Walks the ancestor chain from yarn why -R when yarn up -R leaves multiple
resolved versions. Reverts lockfile collateral when parent bumps do not
complete the target update. Parent and target yarn up -R calls use bare
package names (Yarn forbids ranges with -R). Known no-major-bump packages
(currently http-proxy-middleware) are re-pinned if they major-jump.

For simple yarn up -R with a CVE summary table, use bump-workspace-packages.js.

Complex cases (e.g. fast-xml-parser dual-major lines, yarn set resolution)
are out of scope — handle those manually.

Options:
  --repo-root <path>     Local checkout path (default: cwd walk-up / RHDH_PLUGINS_ROOT)
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

function findRepoRoot(explicitRoot) {
  if (explicitRoot) {
    const root = resolvePath(explicitRoot);
    if (!existsSync(resolvePath(root, 'workspaces'))) {
      throw new Error(`--repo-root ${root} has no workspaces/ directory`);
    }
    return root;
  }
  if (process.env.RHDH_PLUGINS_ROOT) {
    const root = resolvePath(process.env.RHDH_PLUGINS_ROOT);
    if (!existsSync(resolvePath(root, 'workspaces'))) {
      throw new Error(`RHDH_PLUGINS_ROOT=${root} has no workspaces/ directory`);
    }
    return root;
  }
  let dir = process.cwd();
  for (;;) {
    if (
      existsSync(resolvePath(dir, 'workspaces')) &&
      existsSync(resolvePath(dir, 'package.json'))
    ) {
      return dir;
    }
    const parent = resolvePath(dir, '..');
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  throw new Error(
    'Could not find repo root. Pass --repo-root or set RHDH_PLUGINS_ROOT.',
  );
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
    const message = error.stderr?.toString().trim() || error.message;
    throw new Error(`yarn why -R ${packageName} failed: ${message}`);
  }
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
  await runYarn(repoRoot, workspaceDir, ['up', '-R', packageName]);
  if (!isNoMajorBumpPackage(packageName)) {
    return;
  }
  const lockAfter = await readFile(lockPath, 'utf8');
  await pinMajorJumps({
    semver,
    packageName,
    lockfileBefore: lockBefore,
    lockfileAfter: lockAfter,
    runYarn: args => runYarn(repoRoot, workspaceDir, args),
  });
}

async function refreshLockfile(repoRoot, workspaceDir) {
  await runYarn(repoRoot, workspaceDir, ['install']);
  await runYarn(repoRoot, workspaceDir, ['dedupe']);
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

function isUpdateComplete(versionsBefore, versionsAfter) {
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
  packageName,
  depth,
  maxParents,
  visitedParents,
}) {
  const byDepth = findParentsByDepth(whyOutput, packageName);
  return [...(byDepth.get(depth) || [])]
    .filter(parent => !isDisallowedParentPackage(parent))
    .filter(parent => !visitedParents.has(parent))
    .sort()
    .slice(0, maxParents);
}

async function refreshTargetState(repoRoot, workspaceDir, packageName) {
  const why = await runYarnWhy(repoRoot, workspaceDir, packageName);
  return {
    why,
    versions: extractResolvedVersions(why, packageName),
  };
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

  const [workspace, packageName] = positional;
  const repoRoot = findRepoRoot(options.repoRoot);
  const workspaceDir = resolvePath(repoRoot, 'workspaces', workspace);
  if (!existsSync(workspaceDir)) {
    throw new Error(`Workspace not found: workspaces/${workspace}`);
  }
  if (!existsSync(resolvePath(workspaceDir, 'yarn.lock'))) {
    throw new Error(`No yarn.lock in workspaces/${workspace}`);
  }
  const lockPath = resolvePath(workspaceDir, 'yarn.lock');

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
  const beforeWhy = await runYarnWhy(repoRoot, workspaceDir, packageName);
  const versionsBefore = extractResolvedVersions(beforeWhy, packageName);

  const attempts = [];
  const dryRun = flags.has('dry-run');
  const fast = flags.has('fast');
  let blockedReason = null;

  let currentWhy = beforeWhy;
  let versionsCurrent = [...versionsBefore];

  const isComplete = versions =>
    isUpdateComplete(versionsBefore, versions);

  if (!dryRun) {
    await updatePackage(repoRoot, workspaceDir, packageName, semver);
    ({ why: currentWhy, versions: versionsCurrent } = await refreshTargetState(
      repoRoot,
      workspaceDir,
      packageName,
    ));
    attempts.push({ type: 'target', package: packageName });
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
        packageName,
        depth,
        maxParents: options.maxParents,
        visitedParents,
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

        await updatePackage(repoRoot, workspaceDir, parent, semver);
        attempts.push({ type: 'parent', depth, package: parent });
        parentBumpsRan = true;
        await updatePackage(repoRoot, workspaceDir, packageName, semver);
        attempts.push({ type: 'target-retry', depth, package: packageName });
        ({ why: currentWhy, versions: versionsCurrent } = await refreshTargetState(
          repoRoot,
          workspaceDir,
          packageName,
        ));

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
    await restoreLockfile(lockPath, lockfileBeforeParents);
    reverted = true;
    attempts.push({ type: 'revert', reason: 'incomplete_parent_bumps' });
    ({ why: currentWhy, versions: versionsCurrent } = await refreshTargetState(
      repoRoot,
      workspaceDir,
      packageName,
    ));
  }

  if (
    !dryRun &&
    !reverted &&
    isComplete(versionsCurrent) &&
    attempts.some(a => !a.skipped && a.type !== 'revert')
  ) {
    await refreshLockfile(repoRoot, workspaceDir);
    attempts.push({ type: 'install' });
    attempts.push({ type: 'dedupe' });
    ({ why: currentWhy, versions: versionsCurrent } = await refreshTargetState(
      repoRoot,
      workspaceDir,
      packageName,
    ));
  }

  const result = {
    workspace,
    package: packageName,
    repoRoot,
    dryRun,
    fast,
    versionsBefore,
    versionsAfter: versionsCurrent,
    complete: isComplete(versionsCurrent),
    reverted,
    blockedReason,
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
