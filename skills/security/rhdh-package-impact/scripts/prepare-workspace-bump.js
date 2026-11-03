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

/**
 * Prepare a plugins checkout for a Dependabot CVE lockfile bump:
 *   git fetch <upstream> <base>
 *   git checkout -B chore/<workspace>-cve-bumps <upstream>/<base>
 *   verify workspaces/<workspace>/yarn.lock
 *
 * Does not commit, push, open a PR, run yarn, or touch unrelated untracked
 * paths. Prints the next skill commands after a successful prep.
 */

import { execFile as execFileCb } from 'child_process';
import { existsSync } from 'fs';
import { dirname, resolve as resolvePath } from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';

const execFile = promisify(execFileCb);
const __dirname = dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`Usage: prepare-workspace-bump.js [options] <workspace>

Prepare a plugins monorepo checkout for a CVE yarn.lock bump:
  1. Verify workspaces/<workspace>/yarn.lock exists
  2. git fetch <upstream-remote> <base>
  3. git checkout -B chore/<workspace>-cve-bumps <upstream-remote>/<base>

Does not commit, push, open a PR, or modify unrelated untracked files.

Options:
  --repo-root <path>   Local plugins checkout (default: cwd walk-up / RHDH_PLUGINS_ROOT)
  --upstream <remote>  Remote that tracks redhat-developer (default: upstream)
  --base <branch>      Base branch to fetch/reset onto (default: main)
  --branch <name>      Branch to create/reset (default: chore/<workspace>-cve-bumps)
  --dry-run            Print the plan only; no git fetch/checkout
  --json               Machine-readable JSON on stdout
  -h, --help           Show this help

Examples:
  node prepare-workspace-bump.js --repo-root /path/to/rhdh-plugins scorecard
  node prepare-workspace-bump.js translations --dry-run
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const options = {
    repoRoot: undefined,
    upstream: 'upstream',
    base: 'main',
    branch: undefined,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--json') {
      flags.add('json');
    } else if (arg === '--dry-run') {
      flags.add('dry-run');
    } else if (arg === '-h' || arg === '--help') {
      flags.add('help');
    } else if (arg === '--repo-root') {
      options.repoRoot = argv[++i];
      if (!options.repoRoot) {
        throw new Error('--repo-root requires a path');
      }
    } else if (arg === '--upstream') {
      options.upstream = argv[++i];
      if (!options.upstream) {
        throw new Error('--upstream requires a remote name');
      }
    } else if (arg === '--base') {
      options.base = argv[++i];
      if (!options.base) {
        throw new Error('--base requires a branch name');
      }
    } else if (arg === '--branch') {
      options.branch = argv[++i];
      if (!options.branch) {
        throw new Error('--branch requires a branch name');
      }
    } else if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
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
    if (existsSync(resolvePath(dir, 'workspaces'))) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir) {
      throw new Error(
        'Could not find plugins repo root (no workspaces/). Pass --repo-root or set RHDH_PLUGINS_ROOT.',
      );
    }
    dir = parent;
  }
}

function normalizeWorkspace(name) {
  const raw = String(name || '').trim();
  if (!raw) {
    throw new Error('workspace name is required');
  }
  return raw.replace(/^workspaces\//, '').replace(/\/$/, '');
}

async function runGit(repoRoot, args) {
  const { stdout, stderr } = await execFile('git', args, {
    cwd: repoRoot,
    maxBuffer: 10 * 1024 * 1024,
  });
  return {
    stdout: (stdout || '').toString().trim(),
    stderr: (stderr || '').toString().trim(),
  };
}

async function remoteExists(repoRoot, remote) {
  const { stdout } = await runGit(repoRoot, ['remote']);
  return stdout
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .includes(remote);
}

function nextCommands(repoRoot, workspace, skillDir) {
  const bump = `node ${skillDir}/bump-workspace-packages.js --repo-root ${repoRoot} --repo redhat-developer/rhdh-plugins ${workspace} --json`;
  return [
    `node ${skillDir}/list-dependabot-packages.js --repo redhat-developer/rhdh-plugins ${workspace}`,
    `${bump} | node ${skillDir}/format-bump-pr.js --with-title`,
  ];
}

async function main() {
  const { flags, options, positional } = parseArgs(process.argv.slice(2));
  if (flags.has('help')) {
    usage();
    process.exit(0);
  }
  if (positional.length !== 1) {
    usage();
    process.exit(1);
  }

  const workspace = normalizeWorkspace(positional[0]);
  const repoRoot = findRepoRoot(options.repoRoot);
  const upstream = options.upstream;
  const base = options.base;
  const branch = options.branch || `chore/${workspace}-cve-bumps`;
  const upstreamRef = `${upstream}/${base}`;
  const dryRun = flags.has('dry-run');
  const workspaceDir = resolvePath(repoRoot, 'workspaces', workspace);
  const lockPath = resolvePath(workspaceDir, 'yarn.lock');
  const skillDir = __dirname;

  if (!existsSync(workspaceDir)) {
    throw new Error(`Workspace not found: workspaces/${workspace}`);
  }
  if (!existsSync(lockPath)) {
    throw new Error(`No yarn.lock in workspaces/${workspace}`);
  }
  if (!existsSync(resolvePath(repoRoot, '.git'))) {
    throw new Error(`${repoRoot} is not a git checkout`);
  }
  if (!(await remoteExists(repoRoot, upstream))) {
    throw new Error(
      `git remote "${upstream}" not found in ${repoRoot} (expected fork→origin, redhat-developer→upstream)`,
    );
  }

  const plan = {
    repoRoot,
    workspace,
    lockPath: `workspaces/${workspace}/yarn.lock`,
    upstream,
    base,
    branch,
    upstreamRef,
    dryRun,
    steps: [
      `git fetch ${upstream} ${base}`,
      `git checkout -B ${branch} ${upstreamRef}`,
    ],
    next: nextCommands(repoRoot, workspace, skillDir),
  };

  if (dryRun) {
    if (flags.has('json')) {
      console.log(JSON.stringify({ ...plan, fetched: false, checkedOut: false }, null, 2));
      return;
    }
    console.log('Mode:      dry-run (no git changes)');
    console.log(`Repo:      ${repoRoot}`);
    console.log(`Workspace: ${workspace}`);
    console.log(`Lockfile:  workspaces/${workspace}/yarn.lock`);
    console.log(`Branch:    ${branch} ← ${upstreamRef}`);
    console.log('');
    console.log('Would run:');
    for (const step of plan.steps) {
      console.log(`  ${step}`);
    }
    console.log('');
    console.log('Then:');
    for (const cmd of plan.next) {
      console.log(`  ${cmd}`);
    }
    return;
  }

  await runGit(repoRoot, ['fetch', upstream, base]);
  await runGit(repoRoot, ['checkout', '-B', branch, upstreamRef]);
  const { stdout: head } = await runGit(repoRoot, ['rev-parse', '--short', 'HEAD']);
  const { stdout: status } = await runGit(repoRoot, [
    'status',
    '-sb',
    '--',
    `workspaces/${workspace}`,
  ]);

  const result = {
    ...plan,
    fetched: true,
    checkedOut: true,
    head,
    status,
  };

  if (flags.has('json')) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  console.log(`Repo:      ${repoRoot}`);
  console.log(`Workspace: ${workspace}`);
  console.log(`Lockfile:  workspaces/${workspace}/yarn.lock`);
  console.log(`Branch:    ${branch} @ ${head} (from ${upstreamRef})`);
  if (status) {
    console.log(`Status:    ${status}`);
  }
  console.log('');
  console.log('Next:');
  for (const cmd of plan.next) {
    console.log(`  ${cmd}`);
  }
  console.log('');
  console.log(
    'Does not commit, push, or open a PR. Leave unrelated untracked paths alone.',
  );
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
