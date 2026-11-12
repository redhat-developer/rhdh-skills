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

import { loadDependabotAlerts } from './dependabot-alerts.js';
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
import {
  LAYOUT_RHDH_CORE,
  filterAlertsForLayout,
  findCheckout,
  inferKindFromRepo,
  resolveRepoLayout,
  splitWorkspaceArgs,
} from './repo-layout.js';

/**
 * Bare yarn up -R is required (Yarn forbids ranges with --recursive).
 * For known no-major-bump packages (currently http-proxy-middleware), after
 * each up pinMajorJumps re-pins jumped descriptors to the latest release
 * within their previous major via yarn set resolution.
 */

const execFile = promisify(execFileCb);
const __dirname = dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`Usage: bump-workspace-packages.js [options] <workspace> [package...]

Runs yarn up -R for one or more packages in a workspace (bare package name;
Yarn forbids ranges with -R). Known no-major-bump packages (currently
http-proxy-middleware) are re-pinned if a descriptor major-jumped. Then
yarn install and yarn dedupe, and prints a table summarizing version
changes and which open CVEs look fixed.

<workspace> is a plugins-monorepo name (homepage) or rhdh-core token
(rhdh / .). On rhdh-core you may omit the token and pass package names
directly when --repo-root points at the rhdh checkout.

If [package] is omitted, bumps every package with open Dependabot alerts
under the workspace (plugins: workspaces/<name>/; rhdh: product lockfile
yarn.lock + packages/ + plugins/), except @backstage/* and
@backstage-community/* (denylist; never yarn up those).

Options:
  --repo-root <path>   Plugins monorepo or rhdh core checkout
  --repo <owner/name>  GitHub repo for Dependabot alerts (default: auto-detect;
                       rhdh-core defaults to redhat-developer/rhdh)
  --alerts-json <file> Snapshot of GitHub Dependabot alert objects (no token)
  --json               Machine-readable JSON on stdout
  --dry-run            Report only; do not run yarn up, install, or dedupe
  --no-dedupe          Skip yarn dedupe after yarn install
  --no-ancestors       Skip allowlisted leftover ancestor bumps
  -h, --help           Show this help

Examples:
  node bump-workspace-packages.js --repo-root /path/to/plugins-repo boost
  node bump-workspace-packages.js --repo-root /path/to/rhdh --repo redhat-developer/rhdh rhdh --json
  node bump-workspace-packages.js boost adm-zip ws --json
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const options = {
    repoRoot: undefined,
    repo: undefined,
    alertsJson: undefined,
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
    } else if (arg === '--alerts-json') {
      options.alertsJson = argv[++i];
      if (!options.alertsJson) {
        throw new Error('--alerts-json requires a file path');
      }
    } else if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
  }

  return { flags, options, positional };
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

/** Run yarn install in the workspace; retry once on failure. */
async function runWorkspaceInstall(repoRoot, workspaceDir) {
  let retried = false;
  let lastError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await runYarn(repoRoot, workspaceDir, ['install']);
      return { ok: true, error: null, retried };
    } catch (error) {
      lastError = yarnFailureMessage(error);
      if (attempt === 0) {
        retried = true;
        continue;
      }
    }
  }
  return { ok: false, error: lastError, retried };
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

async function runAncestorBump(repoRoot, workspace, packageName, repo, alertsJson) {
  const script = resolvePath(__dirname, 'bump-package-ancestors.js');
  const args = [script, '--repo-root', repoRoot];
  if (repo) {
    args.push('--repo', repo);
  }
  if (alertsJson) {
    args.push('--alerts-json', alertsJson);
  }
  args.push(workspace, packageName, '--json');
  try {
    const { stdout } = await execFile(process.execPath, args, {
      maxBuffer: 20 * 1024 * 1024,
    });
    return JSON.parse(stdout);
  } catch (error) {
    const stdout = error.stdout?.toString().trim();
    if (stdout) {
      try {
        return JSON.parse(stdout);
      } catch {
        // fall through
      }
    }
    return {
      complete: false,
      error: yarnFailureMessage(error),
      subprocessFailed: true,
    };
  }
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

function lockfileOutcomeStatus({
  versionsBefore,
  versionsAfter,
  semver,
  alerts,
}) {
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
    return 'updated';
  }
  return 'updated';
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

  const outcome = lockfileOutcomeStatus({
    versionsBefore,
    versionsAfter,
    semver,
    alerts,
  });

  if (!yarnError) {
    return outcome;
  }

  // `yarn up -R` can exit non-zero while stderr only carries warnings, or fail
  // for one package while a later install / dedupe / ancestor pass still moves
  // the lockfile. Base status on the final lockfile, not the up exit code.
  if (outcome !== 'unchanged') {
    return outcome;
  }

  if (
    alerts.length > 0 &&
    anyVersionVulnerable(semver, versionsAfter, alerts)
  ) {
    return 'error';
  }

  return 'unchanged';
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
    ancestorAuto: ancestorAuto != null,
    ancestorComplete: ancestorAuto?.complete ?? null,
    ancestorReverted: ancestorAuto?.reverted ?? null,
    ancestorBlockedReason: ancestorAuto?.blockedReason ?? null,
    ancestorError:
      ancestorAuto?.error ||
      ancestorAuto?.yarnWhyError ||
      ancestorAuto?.prepInstallError ||
      null,
    skipReason: skipReason(packageName),
  };
}

async function main() {
  const { flags, options, positional } = parseArgs(process.argv.slice(2));
  if (flags.has('help')) {
    usage();
    process.exit(0);
  }

  const checkout = findCheckout({
    explicitRoot: options.repoRoot,
    required: false,
  });
  const kind =
    checkout?.kind || inferKindFromRepo(options.repo) || undefined;
  const { workspaceInput, packages: requestedFromArgs } = splitWorkspaceArgs(
    kind,
    positional,
  );
  if (!workspaceInput && kind !== LAYOUT_RHDH_CORE) {
    usage();
    process.exit(1);
  }

  const layout = resolveRepoLayout({
    explicitRoot: options.repoRoot,
    workspaceInput: workspaceInput || 'rhdh',
    explicitRepo: options.repo,
    requireCheckout: true,
  });
  const workspace = layout.workspace;
  const repoRoot = layout.repoRoot;
  const workspaceDir = layout.workspaceDir;
  const lockPath = layout.lockPath;
  const requestedPackages = requestedFromArgs;

  const {
    alerts: allAlerts,
    repo: repoFull,
    fromSnapshot,
  } = await loadDependabotAlerts({
    alertsJson: options.alertsJson,
    explicitRepo: options.repo || layout.defaultDependabotRepo,
    cwd: repoRoot,
    state: 'open',
    requiredFor: 'Dependabot alerts read',
  });
  const semver = loadSemver(repoRoot);
  const dryRun = flags.has('dry-run');

  const workspaceAlerts = filterAlertsForLayout(allAlerts, layout);

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
      layout: layout.kind,
      lockfileRel: layout.lockfileRel,
      repoRoot,
      dryRun,
      packageCount: 0,
      results: [],
    };
    if (flags.has('json')) {
      console.log(JSON.stringify(empty, null, 2));
    } else {
      console.log(
        `No open Dependabot alerts under ${layout.lockfileRel} (${layout.scope})`,
      );
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
  let installRetried = false;
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
        yarnErrors[packageName] = yarnFailureMessage(error);
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
          yarnErrors[`${packageName}__majorPin`] = yarnFailureMessage(error);
        }
      }
    }
    const attemptedUp = packageNames.some(name => !skippedPackages[name]);
    if (attemptedUp) {
      const installResult = await runWorkspaceInstall(repoRoot, workspaceDir);
      installRetried = installResult.retried;
      if (!installResult.ok) {
        yarnErrors.__install = installResult.error;
      }
      if (!flags.has('no-dedupe') && !yarnErrors.__install) {
        try {
          await runYarn(repoRoot, workspaceDir, ['dedupe']);
        } catch (error) {
          yarnErrors.__dedupe = yarnFailureMessage(error);
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
  const installFailed = Boolean(yarnErrors.__install);
  if (!dryRun && !flags.has('no-ancestors')) {
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
      const pkgAlerts = workspaceAlerts
        .filter(a => a.dependency?.package?.name === packageName)
        .map(summarizeAlert);
      // Single patched line is done. Single unpatched pin or extra
      // still-vulnerable lines are leftovers held by a parent.
      if (!leftoverVersions(semver, pkgAlerts, leftoverResolved).length) {
        continue;
      }
      try {
        ancestorAuto[packageName] = await runAncestorBump(
          repoRoot,
          workspace,
          packageName,
          repoFull,
          options.alertsJson,
        );
        lockAfterUp = await readFile(lockPath, 'utf8');
      } catch (error) {
        ancestorAuto[packageName] = {
          complete: false,
          error: yarnFailureMessage(error),
          subprocessFailed: true,
        };
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

  const attemptedBump =
    !dryRun && packageNames.some(name => !skippedPackages[name]);
  if (
    attemptedBump &&
    !flags.has('no-dedupe') &&
    !yarnErrors.__install
  ) {
    try {
      await runYarn(repoRoot, workspaceDir, ['dedupe']);
    } catch (error) {
      yarnErrors.__finalDedupe = yarnFailureMessage(error);
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
    const upYarnError = yarnErrors[packageName];
    const status = bumpStatus({
      dryRun,
      skipped,
      versionsBefore,
      versionsAfter,
      semver,
      alerts: pkgAlerts,
      yarnError: upYarnError,
    });

    const row = buildRow({
      packageName,
      classification: classification.classification ?? 'UNKNOWN',
      versionsBefore,
      versionsAfter,
      alerts: pkgAlerts,
      semver,
      status,
      yarnError: status === 'error' ? upYarnError : null,
      ancestorAuto: ancestorAuto[packageName],
    });
    if (majorPinsByPackage[packageName]) {
      row.majorPins = majorPinsByPackage[packageName];
    }
    results.push(row);
  }

  const ancestorsDespiteInstallFailure =
    installFailed && Object.keys(ancestorAuto).length > 0;

  const output = {
    repo: repoFull,
    source: fromSnapshot ? 'alerts-json' : 'github-rest',
    workspace,
    layout: layout.kind,
    lockfileRel: layout.lockfileRel,
    repoRoot,
    dryRun,
    installed:
      !dryRun &&
      packageNames.some(name => !skippedPackages[name]) &&
      !yarnErrors.__install,
    installError: yarnErrors.__install || null,
    installRetried,
    deduped:
      !dryRun &&
      packageNames.some(name => !skippedPackages[name]) &&
      !flags.has('no-dedupe') &&
      !yarnErrors.__install &&
      !yarnErrors.__dedupe &&
      !yarnErrors.__finalDedupe,
    dedupeError:
      yarnErrors.__finalDedupe || yarnErrors.__dedupe || null,
    ancestorsDespiteInstallFailure,
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
    if (installFailed) {
      console.log(
        '  (yarn install failed; ancestor bumps still ran for allowlisted leftovers)',
      );
    }
    for (const r of ancestorRows) {
      console.log(
        `  • ${r.package}: ${r.ancestorComplete ? 'complete' : 'attempted'}`,
      );
    }
  } else if (installFailed && !flags.has('no-ancestors')) {
    console.log('');
    console.log(
      'Allowlisted ancestor bumps: skipped (no CVE leftovers on allowlist packages)',
    );
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

  const failed = results.filter(r => r.status === 'error' && r.yarnError);
  const recoveredUp = results.filter(
    r => r.status !== 'error' && yarnErrors[r.package],
  );
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
  if (recoveredUp.length) {
    console.log('');
    console.log(
      'Yarn up recovered (non-zero exit, lockfile outcome OK after install/dedupe/ancestors):',
    );
    for (const r of recoveredUp) {
      console.log(`  • ${r.package}: ${yarnErrors[r.package]}`);
    }
  }
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
