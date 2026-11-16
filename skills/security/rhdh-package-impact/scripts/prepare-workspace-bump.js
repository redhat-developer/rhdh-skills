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
 * Prepare a plugins checkout for a Dependabot CVE lockfile bump.
 *
 * Interactive (default when not under Fullsend):
 *   git fetch <upstream> <base>
 *   git checkout -B chore/<workspace>-cve-bumps <upstream>/<base>
 *   verify workspaces/<workspace>/yarn.lock
 *
 * Fullsend / --verify-only:
 *   verify workspaces/<workspace>/yarn.lock only
 *   report current branch/HEAD
 *   do not fetch or checkout — the Fullsend runner owns clone/branch setup
 *
 * Does not commit, push, open a PR, run yarn, or touch unrelated untracked
 * paths. Prints the next skill commands after a successful prep.
 */

import { execFile as execFileCb } from 'child_process';
import { existsSync } from 'fs';
import { dirname, resolve as resolvePath } from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';

import { resolveRepoLayout } from './repo-layout.js';

const execFile = promisify(execFileCb);
const __dirname = dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`Usage: prepare-workspace-bump.js [options] <workspace>

Prepare a plugins monorepo or rhdh core checkout for a CVE yarn.lock bump.

Modes:
  Interactive (default): verify lockfile, then
    git fetch <upstream> <base>
    git checkout -B chore/<workspace>-cve-bumps <upstream>/<base>
  Fullsend / --verify-only: verify lockfile only. Do not fetch or checkout.

<workspace> is a plugins name (homepage) or rhdh (or .) for redhat-developer/rhdh.

Options:
  --repo-root <path>   Local checkout (default: cwd walk-up / RHDH_PLUGINS_ROOT / RHDH_CORE_ROOT)
  --upstream <remote>  Remote that tracks redhat-developer (default: upstream)
  --base <branch>      Base branch to fetch/reset onto (default: main)
  --branch <name>      Branch to create/reset (default: chore/<workspace>-cve-bumps)
  --verify-only        Verify lockfile + report HEAD; skip git fetch/checkout
  --reset-branch       Force interactive reset even when FULLSEND_OUTPUT_DIR is set
  --dry-run            Print the plan only; no git fetch/checkout
  --json               Machine-readable JSON on stdout
  -h, --help           Show this help

Examples:
  node prepare-workspace-bump.js --repo-root /path/to/rhdh-plugins scorecard
  node prepare-workspace-bump.js --repo-root /path/to/rhdh rhdh
  node prepare-workspace-bump.js --verify-only cost-management
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
    } else if (arg === '--verify-only') {
      flags.add('verify-only');
    } else if (arg === '--reset-branch') {
      flags.add('reset-branch');
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

function isFullsendEnv() {
  return Boolean(process.env.FULLSEND_OUTPUT_DIR);
}

function resolveVerifyOnly(flags) {
  if (flags.has('reset-branch')) {
    return false;
  }
  if (flags.has('verify-only')) {
    return true;
  }
  return isFullsendEnv();
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

function nextCommands(layout, skillDir) {
  const repo = layout.defaultDependabotRepo || 'redhat-developer/rhdh-plugins';
  const ws = layout.workspace;
  const bump = `node ${skillDir}/bump-workspace-packages.js --repo-root ${layout.repoRoot} --repo ${repo} ${ws} --json`;
  return [
    `node ${skillDir}/list-dependabot-packages.js --repo ${repo} ${ws}`,
    `${bump} | node ${skillDir}/format-bump-pr.js --with-title`,
  ];
}

async function currentGitState(repoRoot, statusPaths) {
  const { stdout: head } = await runGit(repoRoot, ['rev-parse', '--short', 'HEAD']);
  const { stdout: branch } = await runGit(repoRoot, [
    'rev-parse',
    '--abbrev-ref',
    'HEAD',
  ]);
  const { stdout: status } = await runGit(repoRoot, [
    'status',
    '-sb',
    '--',
    ...statusPaths,
  ]);
  return { head, branch, status };
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
  if (flags.has('verify-only') && flags.has('reset-branch')) {
    throw new Error('Use either --verify-only or --reset-branch, not both');
  }

  const layout = resolveRepoLayout({
    explicitRoot: options.repoRoot,
    workspaceInput: positional[0],
    requireCheckout: true,
  });
  const workspace = layout.workspace;
  const repoRoot = layout.repoRoot;
  const lockfileRel = layout.lockfileRel;
  const upstream = options.upstream;
  const base = options.base;
  const branch = options.branch || layout.bumpBranch;
  const upstreamRef = `${upstream}/${base}`;
  const dryRun = flags.has('dry-run');
  const verifyOnly = resolveVerifyOnly(flags);
  const fullsendDetected = isFullsendEnv();
  const skillDir = __dirname;

  if (!existsSync(resolvePath(repoRoot, '.git'))) {
    throw new Error(`${repoRoot} is not a git checkout`);
  }

  const plan = {
    repoRoot,
    workspace,
    layout: layout.kind,
    lockPath: lockfileRel,
    upstream,
    base,
    branch,
    upstreamRef,
    dryRun,
    verifyOnly,
    fullsendDetected,
    mode: verifyOnly ? 'verify-only' : 'reset-branch',
    steps: verifyOnly
      ? [`verify ${lockfileRel}`]
      : [
          `git fetch ${upstream} ${base}`,
          `git checkout -B ${branch} ${upstreamRef}`,
        ],
    next: nextCommands(layout, skillDir),
  };

  if (verifyOnly) {
    const state = await currentGitState(repoRoot, layout.statusPaths);
    const result = {
      ...plan,
      fetched: false,
      checkedOut: false,
      head: state.head,
      currentBranch: state.branch,
      status: state.status,
    };

    if (flags.has('json')) {
      console.log(JSON.stringify(result, null, 2));
      return;
    }

    console.log(`Mode:      verify-only (no git fetch/checkout)`);
    if (fullsendDetected && !flags.has('verify-only')) {
      console.log(
        'Detected:  FULLSEND_OUTPUT_DIR — branch setup owned by Fullsend runner',
      );
    }
    console.log(`Repo:      ${repoRoot}`);
    console.log(`Workspace: ${workspace}`);
    console.log(`Lockfile:  ${lockfileRel}`);
    console.log(`Branch:    ${state.branch} @ ${state.head}`);
    if (state.status) {
      console.log(`Status:    ${state.status}`);
    }
    console.log('');
    console.log('Next:');
    for (const cmd of plan.next) {
      console.log(`  ${cmd}`);
    }
    console.log('');
    console.log(
      'Does not commit, push, or open a PR. Leave branch creation to the Fullsend runner (or pass --reset-branch for interactive Cursor use).',
    );
    return;
  }

  if (!(await remoteExists(repoRoot, upstream))) {
    throw new Error(
      `git remote "${upstream}" not found in ${repoRoot} (expected fork→origin, redhat-developer→upstream)`,
    );
  }

  if (dryRun) {
    if (flags.has('json')) {
      console.log(
        JSON.stringify({ ...plan, fetched: false, checkedOut: false }, null, 2),
      );
      return;
    }
    console.log('Mode:      dry-run (no git changes)');
    console.log(`Repo:      ${repoRoot}`);
    console.log(`Workspace: ${workspace}`);
    console.log(`Lockfile:  ${lockfileRel}`);
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
  const state = await currentGitState(repoRoot, layout.statusPaths);

  const result = {
    ...plan,
    fetched: true,
    checkedOut: true,
    head: state.head,
    currentBranch: state.branch,
    status: state.status,
  };

  if (flags.has('json')) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  console.log(`Mode:      reset-branch`);
  console.log(`Repo:      ${repoRoot}`);
  console.log(`Workspace: ${workspace}`);
  console.log(`Lockfile:  ${lockfileRel}`);
  console.log(`Branch:    ${branch} @ ${state.head} (from ${upstreamRef})`);
  if (state.status) {
    console.log(`Status:    ${state.status}`);
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
