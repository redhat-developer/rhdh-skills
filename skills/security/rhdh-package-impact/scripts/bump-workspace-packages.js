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
import { readFile } from 'fs/promises';
import { dirname, resolve as resolvePath } from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';

import { resolveGithubToken } from './github-auth.js';
import { resolveGithubRepo } from './github-repo.js';
import { isSkippedBumpPackage, skipReason } from './bump-skip.js';
import { isAncestorAutoPackage } from './ancestor-allowlist.js';
import {
  compactAlerts,
  leftoverVersions,
  versionIsPatched,
} from './cve-version-status.js';
import {
  REACT_ROUTER,
  REACT_ROUTER_DOM,
  descriptorsFromLockfile,
  descriptorsSatisfyingVersion,
  expandReactRouterPair,
  reactRouterDomAlignTargets,
} from './react-router-pair.js';
import { isNoMajorBumpPackage, pinMajorJumps } from './same-major-yarn-up.js';

/**
 * Bare yarn up -R is required (Yarn forbids ranges with --recursive).
 * For known no-major-bump packages (currently http-proxy-middleware), after
 * each up pinMajorJumps re-pins jumped descriptors to the latest release
 * within their previous major via yarn set resolution.
 */

const execFile = promisify(execFileCb);
const __dirname = dirname(fileURLToPath(import.meta.url));
const API_BASE = 'https://api.github.com';

function usage() {
  console.error(`Usage: bump-workspace-packages.js [options] <workspace> [package...]

Runs yarn up -R for one or more packages in a workspace (bare package name;
Yarn forbids ranges with -R). Known no-major-bump packages (currently
http-proxy-middleware) are re-pinned if a descriptor major-jumped. Then
yarn install and yarn dedupe (rhdh-plugins lockfile hygiene so CI
--immutable matches), and prints a table summarizing version changes and
which open CVEs look fixed.

If [package] is omitted, bumps every package with open Dependabot alerts
under workspaces/<workspace>/, except @backstage/* and @backstage-community/*
(denylist; never yarn up those).

After yarn up -R, leftover allowlisted packages (currently qs) that still
resolve more than one version are ancestor-bumped automatically. Other
ancestor-chain parent bumps remain opt-in via bump-package-ancestors.js.

When react-router or react-router-dom is bumped, the other is included if
present in the lockfile, and react-router-dom is aligned to react-router's
same-major version via yarn set resolution when they still disagree.

Options:
  --repo-root <path>   Local checkout path (default: cwd walk-up / RHDH_PLUGINS_ROOT)
  --repo <owner/name>  GitHub repo for Dependabot alerts (default: auto-detect)
  --json               Machine-readable JSON on stdout
  --dry-run            Report only; do not run yarn up, install, or dedupe
  --no-dedupe          Skip yarn dedupe after yarn install
  --no-ancestors       Skip allowlisted leftover ancestor bumps (qs)
  -h, --help           Show this help

Examples:
  node bump-workspace-packages.js --repo-root /path/to/plugins-repo boost
  node bump-workspace-packages.js boost adm-zip ws --json
  node bump-workspace-packages.js boost prismjs --dry-run
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const options = {
    repoRoot: undefined,
    repo: undefined,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--json') {
      flags.add('json');
    } else if (arg === '--dry-run') {
      flags.add('dry-run');
    } else if (arg === '--no-dedupe') {
      flags.add('no-dedupe');
    } else if (arg === '--no-ancestors') {
      flags.add('no-ancestors');
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

function parseOwnerRepo(repo) {
  const [owner, name, ...rest] = repo.split('/');
  if (!owner || !name || rest.length) {
    throw new Error(`Invalid --repo "${repo}"; expected owner/name`);
  }
  return { owner, repo: name, full: `${owner}/${name}` };
}

function parseNextLink(linkHeader) {
  if (!linkHeader) {
    return null;
  }
  const match = linkHeader.match(/<([^>]+)>;\s*rel="next"/);
  return match ? match[1] : null;
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

function anyVersionVulnerable(semver, versions, alerts) {
  return versions.some(version =>
    alerts.some(
      alert =>
        versionIsPatched(
          semver,
          version,
          alert.vulnerableRange,
          alert.firstPatched,
        ).patched === false,
    ),
  );
}

function summarizeAlert(alert) {
  const vuln = alert.security_vulnerability ?? {};
  return {
    number: alert.number,
    package: alert.dependency?.package?.name ?? null,
    vulnerableRange: vuln.vulnerable_version_range ?? null,
    firstPatched: vuln.first_patched_version?.identifier ?? null,
    ghsa: alert.security_advisory?.ghsa_id ?? null,
    cve: alert.security_advisory?.cve_id ?? null,
  };
}

async function fetchOpenAlerts({ token, owner, repo }) {
  const alerts = [];
  const params = new URLSearchParams({ state: 'open', per_page: '100' });
  let nextUrl = `${API_BASE}/repos/${owner}/${repo}/dependabot/alerts?${params}`;

  while (nextUrl) {
    const response = await fetch(nextUrl, {
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'plugins-package-impact',
      },
    });
    const text = await response.text();
    let data;
    try {
      data = text ? JSON.parse(text) : [];
    } catch {
      data = { message: text };
    }
    if (!response.ok) {
      throw new Error(
        `GitHub API error for ${owner}/${repo} (HTTP ${response.status}): ${data?.message || response.statusText}`,
      );
    }
    if (!Array.isArray(data) || data.length === 0) {
      break;
    }
    alerts.push(...data);
    nextUrl = parseNextLink(response.headers.get('link'));
  }

  return alerts;
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

/**
 * After yarn up -R, force react-router-dom descriptors onto react-router's
 * same-major version when highs still disagree (lockfile-only resolutions).
 */
async function alignReactRouterPair(
  repoRoot,
  workspaceDir,
  lockPath,
  semver,
) {
  let lockfileText = await readFile(lockPath, 'utf8');
  const routerVersions = resolvedVersionsFromLockfile(
    lockfileText,
    REACT_ROUTER,
  );
  const domVersions = resolvedVersionsFromLockfile(
    lockfileText,
    REACT_ROUTER_DOM,
  );
  const targets = reactRouterDomAlignTargets(
    semver,
    routerVersions,
    domVersions,
  );
  if (!targets.length) {
    return { aligned: false, targets: [], descriptors: [] };
  }

  const descriptorsApplied = [];
  for (const target of targets) {
    const descriptors = descriptorsSatisfyingVersion(
      semver,
      descriptorsFromLockfile(lockfileText, REACT_ROUTER_DOM),
      REACT_ROUTER_DOM,
      target.version,
    );
    for (const descriptor of descriptors) {
      await runYarn(repoRoot, workspaceDir, [
        'set',
        'resolution',
        descriptor,
        `npm:${target.version}`,
      ]);
      descriptorsApplied.push({
        descriptor,
        version: target.version,
        major: target.major,
        domWas: target.domWas,
      });
    }
  }

  if (!descriptorsApplied.length) {
    return { aligned: false, targets, descriptors: [] };
  }

  await runYarn(repoRoot, workspaceDir, ['install']);
  return {
    aligned: true,
    targets,
    descriptors: descriptorsApplied,
  };
}

async function runAncestorBump(repoRoot, workspace, packageName) {
  const script = resolvePath(__dirname, 'bump-package-ancestors.js');
  const { stdout } = await execFile(
    process.execPath,
    [script, '--repo-root', repoRoot, workspace, packageName, '--json'],
    { maxBuffer: 20 * 1024 * 1024 },
  );
  return JSON.parse(stdout);
}

async function runClassify(repoRoot, workspace, packageName) {
  const script = resolvePath(__dirname, 'classify-cve-source.js');
  try {
    const { stdout } = await execFile(
      process.execPath,
      [script, '--repo-root', repoRoot, workspace, packageName, '--json'],
      { maxBuffer: 10 * 1024 * 1024 },
    );
    return JSON.parse(stdout);
  } catch (error) {
    const message = error.stderr?.toString().trim() || error.message;
    return {
      classification: 'ERROR',
      customerImpact: 'unknown',
      error: message,
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

function cvesForAlerts(alerts) {
  return [
    ...new Set(
      alerts.map(a => a.cve || a.ghsa).filter(Boolean),
    ),
  ].sort();
}

function cvesFixed(semver, alerts, versionsBefore, versionsAfter) {
  const fixed = [];
  for (const alert of alerts) {
    const wasVulnerable = versionsBefore.some(
      v =>
        versionIsPatched(semver, v, alert.vulnerableRange, alert.firstPatched)
          .patched === false,
    );
    const stillVulnerable = versionsAfter.some(
      v =>
        versionIsPatched(semver, v, alert.vulnerableRange, alert.firstPatched)
          .patched === false,
    );
    if (wasVulnerable && !stillVulnerable) {
      fixed.push(alert.cve || alert.ghsa);
    }
  }
  return [...new Set(fixed)].sort();
}

function bumpStatus({
  dryRun,
  skipped,
  versionsBefore,
  versionsAfter,
  semver,
  alerts,
  yarnError,
}) {
  if (skipped) {
    return 'skipped';
  }
  if (dryRun) {
    return 'dry-run';
  }
  if (yarnError) {
    return 'error';
  }
  if (versionsEqual(versionsBefore, versionsAfter)) {
    return 'unchanged';
  }
  const vulnerableBefore = anyVersionVulnerable(semver, versionsBefore, alerts);
  const vulnerableAfter = anyVersionVulnerable(semver, versionsAfter, alerts);
  if (vulnerableBefore && !vulnerableAfter) {
    return 'fixed';
  }
  if (vulnerableBefore && vulnerableAfter) {
    return 'partial';
  }
  if (!vulnerableBefore && !vulnerableAfter) {
    return versionsEqual(versionsBefore, versionsAfter) ? 'unchanged' : 'updated';
  }
  return 'updated';
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

function buildRow({
  packageName,
  classification,
  versionsBefore,
  versionsAfter,
  alerts,
  semver,
  status,
  yarnError,
  ancestorAuto,
}) {
  const fixed = cvesFixed(semver, alerts, versionsBefore, versionsAfter);
  const openCves = cvesForAlerts(alerts);
  const firstPatched = [
    ...new Set(alerts.map(a => a.firstPatched).filter(Boolean)),
  ].sort();

  return {
    package: packageName,
    classification,
    status,
    versionsBefore,
    versionsAfter,
    firstPatched,
    remaining: leftoverVersions(semver, alerts, versionsAfter),
    openCves,
    cvesFixed: fixed,
    alerts: compactAlerts(alerts),
    yarnError: yarnError || null,
    ancestorAuto: Boolean(ancestorAuto),
    ancestorComplete: ancestorAuto?.complete ?? null,
    skipReason: skipReason(packageName),
  };
}

async function main() {
  const { flags, options, positional } = parseArgs(process.argv.slice(2));
  if (flags.has('help')) {
    usage();
    process.exit(0);
  }
  if (positional.length < 1) {
    usage();
    process.exit(1);
  }

  const [workspace, ...requestedPackages] = positional;
  const repoRoot = findRepoRoot(options.repoRoot);
  const workspaceDir = resolvePath(repoRoot, 'workspaces', workspace);
  const lockPath = resolvePath(workspaceDir, 'yarn.lock');

  if (!existsSync(workspaceDir)) {
    throw new Error(`Workspace not found: workspaces/${workspace}`);
  }
  if (!existsSync(lockPath)) {
    throw new Error(`No yarn.lock in workspaces/${workspace}`);
  }

  const resolvedRepo = await resolveGithubRepo({
    explicitRepo: options.repo,
    cwd: repoRoot,
    requiredFor: 'Dependabot alerts read',
  });
  const { owner, repo, full: repoFull } = parseOwnerRepo(resolvedRepo);
  const token = resolveGithubToken({ requiredFor: 'Dependabot alerts read' });
  const semver = loadSemver(repoRoot);
  const dryRun = flags.has('dry-run');

  const prefix = `workspaces/${workspace}/`;
  const allAlerts = await fetchOpenAlerts({ token, owner, repo });
  const workspaceAlerts = allAlerts.filter(a => {
    const manifest = a.dependency?.manifest_path || '';
    return manifest === 'yarn.lock'
      ? workspace === 'root'
      : manifest.startsWith(prefix);
  });

  let packageNames = requestedPackages.length
    ? [...new Set(requestedPackages)].sort()
    : [
        ...new Set(
          workspaceAlerts
            .map(a => a.dependency?.package?.name)
            .filter(Boolean),
        ),
      ].sort();

  if (!packageNames.length) {
    const empty = {
      repo: repoFull,
      workspace,
      dryRun,
      packageCount: 0,
      results: [],
    };
    if (flags.has('json')) {
      console.log(JSON.stringify(empty, null, 2));
    } else {
      console.log(`No open Dependabot alerts under ${prefix}`);
    }
    return;
  }

  const lockfileBefore = await readFile(lockPath, 'utf8');
  const pairExpansion = expandReactRouterPair(packageNames, lockfileBefore);
  packageNames = pairExpansion.packageNames;
  const reactRouterPairAdded = pairExpansion.pairedAdded;

  const beforeByPackage = Object.fromEntries(
    packageNames.map(name => [
      name,
      resolvedVersionsFromLockfile(lockfileBefore, name),
    ]),
  );

  const yarnErrors = {};
  const skippedPackages = {};
  const majorPinsByPackage = {};
  if (!dryRun) {
    for (const packageName of packageNames) {
      if (isSkippedBumpPackage(packageName)) {
        skippedPackages[packageName] = skipReason(packageName);
        continue;
      }
      const needsMajorPin = isNoMajorBumpPackage(packageName);
      const lockBeforePkg = needsMajorPin
        ? await readFile(lockPath, 'utf8')
        : null;
      try {
        await runYarn(repoRoot, workspaceDir, ['up', '-R', packageName]);
      } catch (error) {
        yarnErrors[packageName] =
          error.stderr?.toString().trim() || error.message;
        continue;
      }
      if (needsMajorPin) {
        try {
          const lockAfterPkg = await readFile(lockPath, 'utf8');
          const pinResult = await pinMajorJumps({
            semver,
            packageName,
            lockfileBefore: lockBeforePkg,
            lockfileAfter: lockAfterPkg,
            runYarn: args => runYarn(repoRoot, workspaceDir, args),
          });
          if (pinResult.pinned) {
            majorPinsByPackage[packageName] = pinResult.pins;
          }
        } catch (error) {
          yarnErrors[`${packageName}__majorPin`] =
            error.stderr?.toString().trim() || error.message;
        }
      }
    }
    const attemptedUp = packageNames.some(name => !skippedPackages[name]);
    if (attemptedUp) {
      try {
        await runYarn(repoRoot, workspaceDir, ['install']);
      } catch (error) {
        yarnErrors.__install =
          error.stderr?.toString().trim() || error.message;
      }
      if (!flags.has('no-dedupe') && !yarnErrors.__install) {
        try {
          await runYarn(repoRoot, workspaceDir, ['dedupe']);
        } catch (error) {
          yarnErrors.__dedupe =
            error.stderr?.toString().trim() || error.message;
        }
      }
    }
  } else {
    for (const packageName of packageNames) {
      if (isSkippedBumpPackage(packageName)) {
        skippedPackages[packageName] = skipReason(packageName);
      }
    }
  }

  const ancestorAuto = {};
  if (
    !dryRun &&
    !flags.has('no-ancestors') &&
    !yarnErrors.__install
  ) {
    let lockAfterUp = await readFile(lockPath, 'utf8');
    for (const packageName of packageNames) {
      if (
        skippedPackages[packageName] ||
        !isAncestorAutoPackage(packageName)
      ) {
        continue;
      }
      const leftoverResolved = resolvedVersionsFromLockfile(
        lockAfterUp,
        packageName,
      );
      if (leftoverResolved.length <= 1) {
        continue;
      }
      try {
        ancestorAuto[packageName] = await runAncestorBump(
          repoRoot,
          workspace,
          packageName,
        );
        lockAfterUp = await readFile(lockPath, 'utf8');
      } catch (error) {
        yarnErrors[`${packageName}__ancestor`] =
          error.stderr?.toString().trim() || error.message;
      }
    }
  }

  let reactRouterPairAlign = null;
  const bumpedReactRouterPair =
    packageNames.includes(REACT_ROUTER) ||
    packageNames.includes(REACT_ROUTER_DOM);
  if (
    !dryRun &&
    bumpedReactRouterPair &&
    !yarnErrors.__install &&
    !skippedPackages[REACT_ROUTER] &&
    !skippedPackages[REACT_ROUTER_DOM]
  ) {
    try {
      reactRouterPairAlign = await alignReactRouterPair(
        repoRoot,
        workspaceDir,
        lockPath,
        semver,
      );
      if (
        reactRouterPairAlign?.aligned &&
        !flags.has('no-dedupe')
      ) {
        try {
          await runYarn(repoRoot, workspaceDir, ['dedupe']);
        } catch (error) {
          yarnErrors.__dedupe =
            error.stderr?.toString().trim() || error.message;
        }
      }
    } catch (error) {
      yarnErrors.__reactRouterPair =
        error.stderr?.toString().trim() || error.message;
      reactRouterPairAlign = {
        aligned: false,
        error: yarnErrors.__reactRouterPair,
      };
    }
  }

  const lockfileAfter = dryRun
    ? lockfileBefore
    : await readFile(lockPath, 'utf8');

  const results = [];
  for (const packageName of packageNames) {
    const versionsBefore = beforeByPackage[packageName];
    const skipped = Boolean(skippedPackages[packageName]);
    const versionsAfter = dryRun || skipped
      ? versionsBefore
      : resolvedVersionsFromLockfile(lockfileAfter, packageName);
    const pkgAlerts = workspaceAlerts
      .filter(a => a.dependency?.package?.name === packageName)
      .map(summarizeAlert);
    const classification = await runClassify(repoRoot, workspace, packageName);
    const status = bumpStatus({
      dryRun,
      skipped,
      versionsBefore,
      versionsAfter,
      semver,
      alerts: pkgAlerts,
      yarnError: yarnErrors[packageName],
    });

    const row = buildRow({
      packageName,
      classification: classification.classification ?? 'UNKNOWN',
      versionsBefore,
      versionsAfter,
      alerts: pkgAlerts,
      semver,
      status,
      yarnError: yarnErrors[packageName],
      ancestorAuto: ancestorAuto[packageName],
    });
    if (majorPinsByPackage[packageName]) {
      row.majorPins = majorPinsByPackage[packageName];
    }
    results.push(row);
  }

  const output = {
    repo: repoFull,
    workspace,
    repoRoot,
    dryRun,
    installed:
      !dryRun &&
      packageNames.some(name => !skippedPackages[name]) &&
      !yarnErrors.__install,
    deduped:
      !dryRun &&
      packageNames.some(name => !skippedPackages[name]) &&
      !flags.has('no-dedupe') &&
      !yarnErrors.__install &&
      !yarnErrors.__dedupe,
    skippedPackages: Object.keys(skippedPackages).sort(),
    ancestorAutoPackages: Object.keys(ancestorAuto).sort(),
    reactRouterPairAdded,
    reactRouterPairAlign,
    majorPins: majorPinsByPackage,
    sameMajorOnly: true,
    packageCount: results.length,
    results,
  };

  if (flags.has('json')) {
    console.log(JSON.stringify(output, null, 2));
    return;
  }

  console.log(`Workspace: ${workspace}`);
  console.log(`Repo:      ${repoFull}`);
  if (dryRun) {
    console.log('Mode:      dry-run (no yarn changes)');
  }
  console.log('');

  const headers = [
    'package',
    'classification',
    'status',
    'versions_before',
    'versions_after',
    'first_patched',
    'open_cves',
    'cves_fixed',
  ];
  const rows = results.map(r => [
    r.package,
    r.classification,
    r.status,
    r.versionsBefore.join(', ') || '-',
    r.versionsAfter.join(', ') || '-',
    r.firstPatched.join(', ') || '-',
    r.openCves.join(', ') || '-',
    r.cvesFixed.join(', ') || '-',
  ]);
  printMarkdownTable(headers, rows);

  const skipped = results.filter(r => r.status === 'skipped');
  if (skipped.length) {
    console.log('');
    console.log('Skipped (denylist @backstage/* / @backstage-community/*):');
    for (const r of skipped) {
      console.log(`  • ${r.package}`);
    }
  }

  const ancestorRows = results.filter(r => r.ancestorAuto);
  if (ancestorRows.length) {
    console.log('');
    console.log('Allowlisted leftover ancestor bumps:');
    for (const r of ancestorRows) {
      console.log(
        `  • ${r.package}: ${r.ancestorComplete ? 'complete' : 'attempted'}`,
      );
    }
  }

  if (reactRouterPairAdded.length || reactRouterPairAlign?.aligned) {
    console.log('');
    console.log('react-router / react-router-dom pair sync:');
    for (const name of reactRouterPairAdded) {
      console.log(`  • auto-included ${name} so both halves bump together`);
    }
    if (reactRouterPairAlign?.aligned) {
      for (const entry of reactRouterPairAlign.descriptors || []) {
        console.log(
          `  • aligned ${REACT_ROUTER_DOM} ${entry.domWas} → ${entry.version} (${entry.descriptor})`,
        );
      }
    } else if (yarnErrors.__reactRouterPair) {
      console.log(`  • align failed: ${yarnErrors.__reactRouterPair}`);
    }
  }

  const fixed = results.filter(r => r.cvesFixed.length > 0);
  if (fixed.length) {
    console.log('');
    console.log('CVEs addressed by this bump:');
    for (const r of fixed) {
      console.log(`  • ${r.package}: ${r.cvesFixed.join(', ')}`);
    }
  }

  const failed = results.filter(r => r.yarnError);
  const hygieneErrors = [
    yarnErrors.__install && ['install', yarnErrors.__install],
    yarnErrors.__dedupe && ['dedupe', yarnErrors.__dedupe],
    ...Object.entries(yarnErrors)
      .filter(([key]) => key.endsWith('__ancestor'))
      .map(([key, message]) => [key.replace(/__ancestor$/, ' ancestor'), message]),
  ].filter(Boolean);
  if (failed.length || hygieneErrors.length) {
    console.log('');
    console.log('Yarn errors:');
    for (const r of failed) {
      console.log(`  • ${r.package}: ${r.yarnError}`);
    }
    for (const [step, message] of hygieneErrors) {
      console.log(`  • ${step}: ${message}`);
    }
  }
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
