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
 * Check whether Dependabot-vulnerable packages in an rhdh-plugins workspace
 * are patched to the advisory fix level, and whether remaining open alerts
 * are runner-only (safe to dismiss at alert-level).
 *
 * Uses GitHub REST (fetch) only — never the gh CLI — unless --alerts-json
 * supplies a snapshot (no token, no network).
 */

import { execFile as execFileCb } from 'child_process';
import { createRequire } from 'module';
import { readFile } from 'fs/promises';
import { dirname, resolve as resolvePath } from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';

import {
  alertHasPatchMetadata,
  loadDependabotAlerts,
} from './dependabot-alerts.js';
import {
  buildVersionStatuses,
  patchedVersions,
  resolveVersionsByPath,
} from './resolve-versions-by-path.js';
import {
  LAYOUT_RHDH_CORE,
  classifyManifest,
  filterAlertsForLayout,
  findCheckout,
  inferKindFromRepo,
  isShippedClassification,
  resolveRepoLayout,
  splitWorkspaceArgs,
} from './repo-layout.js';

const execFile = promisify(execFileCb);
const __dirname = dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`Usage: check-dependabot-patch-status.js [options] <workspace> [package]

For a workspace (and optional package), fetch open Dependabot alerts, compare
resolved yarn.lock versions to each alert's first_patched_version / vulnerable
range, run impact classification, and report whether runner alerts can be
dismissed because prod paths are patched (or no PLUGIN_PROD alerts remain).

Uses GitHub REST (not gh). Token: GITHUB_TOKEN / GH_TOKEN in the
environment or a .env file near cwd. --alerts-json skips REST and token.
Needs --repo-root / RHDH_PLUGINS_ROOT (or cwd in a checkout)
for yarn.lock + classify.

If [package] is omitted, checks every package with open alerts in the workspace.

Options:
  --repo-root <path>             Local checkout (plugins monorepo or rhdh core)
  --repo <owner/name>            Remote GitHub repo for REST alerts
                                 (default: detect; rhdh-core uses redhat-developer/rhdh)
  --alerts-json <file>           Snapshot of GitHub Dependabot alert objects
                                 (array, or { "alerts": [...] }). No REST.
                                 Prefer the raw list-alerts payload so
                                 security_vulnerability ranges are present.
  --table                        Markdown classification table (default)
  --json                         Machine-readable JSON
  -h, --help                     Show this help

Examples:
  GITHUB_TOKEN=… node check-dependabot-patch-status.js \\
    --repo-root /path/to/plugins-repo extensions
  GITHUB_TOKEN=… node check-dependabot-patch-status.js \\
    --repo-root /path/to/plugins-repo extensions --json
  node check-dependabot-patch-status.js \\
    --repo-root /path/to/plugins-repo --alerts-json /tmp/dependabot-alerts.json homepage
  GITHUB_TOKEN=… node check-dependabot-patch-status.js \\
    --repo-root /path/to/plugins-repo extensions lodash --table
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
    } else if (arg === '--table') {
      flags.add('table');
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
    } else if (arg === '--token') {
      throw new Error(
        '--token is not supported; set GITHUB_TOKEN or GH_TOKEN in the environment or a .env file',
      );
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
      return require(
        resolvePath(repoRoot, 'node_modules/semver/index.js'),
      );
    } catch {
      throw new Error(
        'semver package not found in repo checkout; run yarn install at repo root',
      );
    }
  }
}

/**
 * Collect unique resolved versions of packageName from a Yarn Berry lockfile.
 */
function resolvedVersionsFromLockfile(lockfileText, packageName) {
  const versions = new Set();
  // Yarn Berry: "name@npm:…" or "name@npm:…, name@npm:…":
  //   version: x.y.z
  const escaped = packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const blockRe = new RegExp(
    `^"${escaped}@[^"]+":\\n((?:  .*\\n)*)`,
    'gm',
  );
  let match;
  while ((match = blockRe.exec(lockfileText)) !== null) {
    const block = match[1];
    const ver = block.match(/^  version: (.+)$/m);
    if (ver) {
      versions.add(ver[1].trim().replace(/^["']|["']$/g, ''));
    }
  }
  return [...versions].sort();
}

function normalizeVulnerableRange(range) {
  if (!range) {
    return range;
  }
  // GitHub emits ">= 6.7.0, < 6.30.4" (comma AND). node-semver treats commas
  // as OR, which falsely marks in-range versions as patched.
  return String(range).replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
}

function versionIsPatched(semver, version, vulnerableRange, firstPatched) {
  const v = semver.coerce(version)?.version;
  if (!v) {
    return { patched: null, reason: `unparseable version ${version}` };
  }

  const range = normalizeVulnerableRange(vulnerableRange);
  if (range) {
    try {
      if (semver.satisfies(v, range, { includePrerelease: true })) {
        return {
          patched: false,
          reason: `in vulnerable range ${range}`,
        };
      }
      return {
        patched: true,
        reason: `outside vulnerable range ${range}`,
      };
    } catch {
      // fall through to firstPatched compare
    }
  }

  if (firstPatched) {
    const fp = semver.coerce(firstPatched)?.version;
    if (!fp) {
      return {
        patched: null,
        reason: `unparseable first_patched ${firstPatched}`,
      };
    }
    if (semver.gte(v, fp)) {
      return { patched: true, reason: `>= first_patched ${fp}` };
    }
    return { patched: false, reason: `< first_patched ${fp}` };
  }

  return {
    patched: null,
    reason: 'no vulnerable range or first_patched_version',
  };
}

/** True only if the version is not in any alert's vulnerable range. */
function versionPatchedAgainstAlerts(semver, version, alerts) {
  if (!alerts.length) {
    return { patched: null, reason: 'no alerts', checks: [] };
  }
  const checks = alerts.map(a =>
    versionIsPatched(semver, version, a.vulnerableRange, a.firstPatched),
  );
  // Vulnerable if any advisory says it is still in-range / below first_patched
  if (checks.some(c => c.patched === false)) {
    return { patched: false, reason: 'vulnerable to at least one open advisory', checks };
  }
  if (checks.every(c => c.patched === true)) {
    return { patched: true, reason: 'outside all open advisory ranges', checks };
  }
  return { patched: null, reason: 'incomplete advisory metadata', checks };
}

function summarizeAlert(alert) {
  const vuln = alert.security_vulnerability ?? {};
  return {
    number: alert.number,
    manifest: alert.dependency?.manifest_path ?? null,
    scope: alert.dependency?.scope ?? null,
    package: alert.dependency?.package?.name ?? null,
    severity: alert.security_advisory?.severity ?? vuln.severity ?? null,
    vulnerableRange: vuln.vulnerable_version_range ?? null,
    firstPatched: vuln.first_patched_version?.identifier ?? null,
    ghsa: alert.security_advisory?.ghsa_id ?? null,
    cve: alert.security_advisory?.cve_id ?? null,
    html_url: alert.html_url ?? null,
  };
}

async function runClassify(repoRoot, workspace, packageName) {
  const script = resolvePath(__dirname, 'classify-cve-source.js');
  try {
    const { stdout } = await execFile(
      process.execPath,
      [script, '--repo-root', repoRoot, workspace, packageName, '--json', '--include-yarn-why'],
      { maxBuffer: 10 * 1024 * 1024 },
    );
    return JSON.parse(stdout);
  } catch (error) {
    const message = error.stderr?.toString().trim() || error.message;
    return {
      workspace,
      package: packageName,
      classification: 'ERROR',
      customerImpact: 'unknown',
      error: message,
    };
  }
}

function assessPackage({
  workspace,
  layoutKind,
  packageName,
  classification,
  customerImpact,
  classifyError,
  workspaceAlerts,
  resolvedVersions,
  pathResolution,
  semver,
}) {
  const alerts = workspaceAlerts.map(a => {
    const s = summarizeAlert(a);
    const manifestClass = classifyManifest(layoutKind, s.manifest, s.scope);
    const versionChecks = resolvedVersions.map(version => ({
      version,
      ...versionIsPatched(semver, version, s.vulnerableRange, s.firstPatched),
    }));
    const allResolvedPatched =
      versionChecks.length > 0 &&
      versionChecks.every(c => c.patched === true);
    const anyResolvedVulnerable = versionChecks.some(c => c.patched === false);

    return {
      ...s,
      manifestClass,
      versionChecks,
      allResolvedPatched,
      anyResolvedVulnerable,
    };
  });

  const counts = {
    RUNNER: 0,
    PLUGIN_PROD: 0,
    PLUGIN_DEV: 0,
    LOCKFILE: 0,
    UNKNOWN: 0,
  };
  for (const a of alerts) {
    counts[a.manifestClass] = (counts[a.manifestClass] || 0) + 1;
  }

  const firstPatchedVersions = [
    ...new Set(alerts.map(a => a.firstPatched).filter(Boolean)),
  ].sort();
  const vulnerableRanges = [
    ...new Set(alerts.map(a => a.vulnerableRange).filter(Boolean)),
  ].sort();

  const versionStatuses = resolvedVersions.map(version => ({
    version,
    ...versionPatchedAgainstAlerts(semver, version, alerts),
  }));

  const fullyPatchedInLockfile =
    versionStatuses.length > 0 &&
    versionStatuses.every(v => v.patched === true);
  const anyUnpatchedInLockfile = versionStatuses.some(v => v.patched === false);

  const prodResolvedVersions = pathResolution?.prodResolvedVersions ?? [];
  const nonProdResolvedVersions = pathResolution?.nonProdResolvedVersions ?? [];
  const summarizedForPath = alerts.map(({ vulnerableRange, firstPatched, number }) => ({
    vulnerableRange,
    firstPatched,
    number,
  }));
  const prodVersionStatuses = buildVersionStatuses(
    prodResolvedVersions,
    semver,
    summarizedForPath,
  );
  const patchedOnProdPaths =
    prodResolvedVersions.length > 0 && patchedVersions(prodVersionStatuses);
  const hasPluginProdReach = isShippedClassification(classification);

  const openPluginProd = counts.PLUGIN_PROD || 0;
  const openCoreProd = counts.CORE_PROD || 0;
  const openProd = openPluginProd + openCoreProd;
  const openRunner = layoutKind === LAYOUT_RHDH_CORE ? 0 : counts.RUNNER || 0;
  const openLockfile = counts.LOCKFILE || 0;
  const openPluginDev = counts.PLUGIN_DEV || 0;

  // Mode A: whole package is exact local-dev label
  const packageLevelRunnerOnly =
    layoutKind !== LAYOUT_RHDH_CORE && classification === 'RUNNER';
  const packageLevelPluginDevOnly = classification === 'PLUGIN_DEV';
  const packageLevelCoreDevOnly = classification === 'CORE_DEV';
  const packageLevelWorkspaceDevOnly = classification === 'WORKSPACE_DEV';

  // Mode B: lockfile versions meet patch level; only runner package.json alerts remain
  const patchedEverywhereExceptRunner =
    layoutKind !== LAYOUT_RHDH_CORE &&
    openProd === 0 &&
    openRunner > 0 &&
    fullyPatchedInLockfile;

  // Lockfile-only remaining alerts after versions are patched
  const lockfileOnlyRemaining =
    openProd === 0 &&
    openRunner === 0 &&
    openLockfile > 0;

  let verdict;
  let safeToDismissRunnerAlerts = false;
  let safeToDismissPackageLevel = false;

  if (classifyError) {
    verdict = 'ERROR';
  } else if (packageLevelRunnerOnly) {
    verdict = 'RUNNER_ONLY';
    safeToDismissPackageLevel = true;
    safeToDismissRunnerAlerts = true;
  } else if (packageLevelPluginDevOnly) {
    verdict = 'PLUGIN_DEV_ONLY';
    safeToDismissPackageLevel = true;
  } else if (packageLevelCoreDevOnly) {
    verdict = 'CORE_DEV_ONLY';
    safeToDismissPackageLevel = true;
  } else if (packageLevelWorkspaceDevOnly) {
    verdict = 'WORKSPACE_DEV_ONLY';
    safeToDismissPackageLevel = true;
  } else if (openProd > 0) {
    verdict =
      openPluginProd > 0
        ? 'PLUGIN_PROD_ALERTS_REMAIN'
        : 'CORE_PROD_ALERTS_REMAIN';
  } else if (patchedEverywhereExceptRunner) {
    verdict = 'PATCHED_EXCEPT_RUNNER';
    safeToDismissRunnerAlerts = true;
  } else if (lockfileOnlyRemaining && fullyPatchedInLockfile) {
    verdict = 'LOCKFILE_ALERTS_ONLY';
  } else if (
    openProd === 0 &&
    hasPluginProdReach &&
    patchedOnProdPaths &&
    anyUnpatchedInLockfile
  ) {
    verdict = 'PROD_PATCHED_DEV_UNPATCHED';
  } else if (
    fullyPatchedInLockfile &&
    openProd === 0 &&
    openRunner === 0 &&
    openLockfile === 0 &&
    openPluginDev === 0 &&
    !(counts.CORE_DEV || 0)
  ) {
    verdict = 'FULLY_PATCHED';
  } else if (anyUnpatchedInLockfile && openProd === 0) {
    verdict = 'UNPATCHED_IN_LOCKFILE_NO_PROD_ALERTS';
  } else {
    verdict = 'NEEDS_REVIEW';
  }

  if (layoutKind === LAYOUT_RHDH_CORE) {
    safeToDismissRunnerAlerts = false;
    if (isShippedClassification(classification)) {
      safeToDismissPackageLevel = false;
    }
  }

  return {
    workspace,
    package: packageName,
    classification,
    customerImpact,
    classifyError: classifyError || null,
    resolvedVersions,
    firstPatchedVersions,
    vulnerableRanges,
    versionStatuses,
    fullyPatchedInLockfile,
    anyUnpatchedInLockfile,
    prodResolvedVersions,
    nonProdResolvedVersions,
    prodVersionStatuses,
    prodPathDetails: pathResolution?.prodPathDetails ?? [],
    patchedOnProdPaths,
    openAlertCount: alerts.length,
    openAlertCounts: counts,
    openAlerts: alerts,
    verdict,
    safeToDismissPackageLevel,
    safeToDismissRunnerAlerts,
    recommendation: recommendationFor(verdict, {
      openRunner,
      openLockfile,
      openPluginDev,
      classification,
      lockfilePatched: fullyPatchedInLockfile,
    }),
  };
}

function recommendationFor(verdict, ctx) {
  switch (verdict) {
    case 'RUNNER_ONLY':
      return 'Package-level RUNNER: dismiss open alerts for this package in the workspace (interactive).';
    case 'PLUGIN_DEV_ONLY':
      return (
        'Package-level PLUGIN_DEV: not a published-plugin / customer vulnerability — ' +
        'dismiss open alerts (interactive). Prefer bumping plugin harness / test ' +
        'devDependencies afterward so SBOMs stay current; dismissal alone does not remove them from SBOM output.'
      );
    case 'WORKSPACE_DEV_ONLY':
      return (
        'Package-level WORKSPACE_DEV: not a published-plugin / customer vulnerability — ' +
        'dismiss open alerts (interactive). Prefer bumping the workspace root / tooling ' +
        'deps afterward so SBOMs stay current; dismissal alone does not remove them from SBOM output.'
      );
    case 'PATCHED_EXCEPT_RUNNER':
      return (
        'No open PLUGIN_PROD alerts; runner alerts remain. ' +
        'Safe to dismiss RUNNER package.json alerts only ' +
        `(app/app-legacy/backend). Leave plugins/ and investigate lockfile if needed. ` +
        `classification=${ctx.classification}`
      );
    case 'FULLY_PATCHED':
      return 'All lockfile versions meet patch level and no PLUGIN_PROD/RUNNER package.json alerts remain.';
    case 'LOCKFILE_ALERTS_ONLY':
      return ctx.lockfilePatched
        ? 'Resolved versions look outside advisory ranges, but yarn.lock alerts remain (often stale). Not PATCHED_EXCEPT_RUNNER; refresh GH or bump lockfile. Exact RUNNER / PLUGIN_DEV / WORKSPACE_DEV may still dismiss at package level.'
        : 'Open alerts are only on yarn.lock; bump lockfile. Package-level dismiss only if classification is exactly RUNNER, PLUGIN_DEV, or WORKSPACE_DEV.';
    case 'PROD_PATCHED_DEV_UNPATCHED':
      return (
        'Published plugin production paths are patched; unpatched versions remain only on ' +
        'plugin devDependencies, runners, workspace tooling, or lockfile-only paths. ' +
        'No PLUGIN_PROD manifest alerts — fix prod only if prod_resolved is unpatched; ' +
        'otherwise prefer SBOM/dev bump or stale lockfile refresh.'
      );
    case 'CORE_DEV_ONLY':
      return (
        'Package-level CORE_DEV: not a shipped RHDH runtime path — dismiss open ' +
        'alerts (interactive). Prefer bumping package devDependencies afterward so SBOMs stay current.'
      );
    case 'CORE_PROD_ALERTS_REMAIN':
      return 'Open CORE_PROD alerts remain — bump/fix shipped RHDH packages (app/backend/plugin-utils) before dismissing anything.';
    case 'PLUGIN_PROD_ALERTS_REMAIN':
      return 'Open PLUGIN_PROD alerts remain — bump/fix published plugin path before dismissing anything on plugins/.';
    case 'UNPATCHED_IN_LOCKFILE_NO_PROD_ALERTS':
      return 'Lockfile still has unpatched versions but no PLUGIN_PROD alerts — review yarn why / multiple versions before dismissing.';
    case 'ERROR':
      return 'Classification or lookup failed — investigate manually.';
    default:
      return 'Needs manual review before dismiss.';
  }
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

function printTable(results) {
  const headers = [
    'package',
    'classification',
    'verdict',
    'patched_prod',
    'patched_lockfile',
    'prod_alerts',
    'runner_alerts',
    'safe_dismiss_pkg',
    'safe_dismiss_runner',
    'prod_resolved',
    'resolved',
    'first_patched',
  ];
  const rows = results.map(r => [
    r.package,
    r.classification,
    r.verdict,
    r.prodResolvedVersions?.length
      ? r.patchedOnProdPaths
        ? 'yes'
        : 'no'
      : '-',
    r.fullyPatchedInLockfile ? 'yes' : r.anyUnpatchedInLockfile ? 'no' : '?',
    (r.openAlertCounts.PLUGIN_PROD || 0) + (r.openAlertCounts.CORE_PROD || 0),
    r.openAlertCounts.RUNNER || 0,
    r.safeToDismissPackageLevel ? 'YES' : 'NO',
    r.safeToDismissRunnerAlerts ? 'YES' : 'NO',
    (r.prodResolvedVersions || []).join(', ') || '-',
    (r.resolvedVersions || []).join(', ') || '-',
    (r.firstPatchedVersions || []).join(', ') || '-',
  ]);
  printMarkdownTable(headers, rows);
  console.log('');
  const dismissable = results.filter(
    r => r.safeToDismissRunnerAlerts || r.safeToDismissPackageLevel,
  );
  if (dismissable.length) {
    console.log('Safe to dismiss (package-level or runner alerts):');
    for (const r of dismissable) {
      console.log(`  • ${r.package} (${r.verdict}) — ${r.recommendation}`);
    }
  } else {
    console.log('No packages currently qualify for dismissal.');
  }
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
  const { workspaceInput, packages: extra } = splitWorkspaceArgs(
    kind,
    positional,
  );
  if ((!workspaceInput && kind !== LAYOUT_RHDH_CORE) || extra.length > 1) {
    usage();
    process.exit(1);
  }
  const onlyPackage = extra[0];

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

  const semver = loadSemver(repoRoot);
  const lockfileText = await readFile(lockPath, 'utf8');

  const { alerts: allAlerts, repo: repoFull, fromSnapshot } =
    await loadDependabotAlerts({
      alertsJson: options.alertsJson,
      explicitRepo: options.repo || layout.defaultDependabotRepo,
      cwd: repoRoot,
      state: 'open',
    });
  const workspaceAlerts = filterAlertsForLayout(allAlerts, layout);

  if (fromSnapshot) {
    const missingPatch = workspaceAlerts.filter(a => !alertHasPatchMetadata(a));
    if (missingPatch.length) {
      console.error(
        `Warning: ${missingPatch.length} snapshot alert(s) lack security_vulnerability ranges; patch-status may be incomplete. Dump the raw GitHub list-alerts payload.`,
      );
    }
  }

  const packageNames = onlyPackage
    ? [onlyPackage]
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
      source: fromSnapshot ? 'alerts-json' : 'github-rest',
      packageCount: 0,
      results: [],
    };
    if (flags.has('json') && !flags.has('table')) {
      console.log(JSON.stringify(empty, null, 2));
    } else {
      console.log(
        `No open Dependabot alerts under ${layout.lockfileRel}`,
      );
    }
    return;
  }

  const results = [];
  for (const packageName of packageNames) {
    const pkgAlerts = workspaceAlerts.filter(
      a => a.dependency?.package?.name === packageName,
    );
    const resolvedVersions = resolvedVersionsFromLockfile(
      lockfileText,
      packageName,
    );
    const classification = await runClassify(repoRoot, workspace, packageName);

    let pathResolution = null;
    if (classification.yarnWhyOutput && !classification.error) {
      pathResolution = await resolveVersionsByPath({
        yarnWhyOutput: classification.yarnWhyOutput,
        workspaceDir,
        packageName,
        layoutKind: layout.kind,
        pluginProd: classification.pluginProd ?? [],
        pluginDev: classification.pluginDev ?? [],
        coreProd: classification.coreProd ?? [],
        coreDev: classification.coreDev ?? [],
      });
    }

    results.push(
      assessPackage({
        workspace,
        layoutKind: layout.kind,
        packageName,
        classification: classification.classification,
        customerImpact: classification.customerImpact,
        classifyError: classification.error || null,
        workspaceAlerts: pkgAlerts,
        resolvedVersions,
        pathResolution,
        semver,
      }),
    );
  }

  const payload = {
    repo: repoFull,
    workspace,
    layout: layout.kind,
    lockfileRel: layout.lockfileRel,
    repoRoot,
    source: fromSnapshot ? 'alerts-json' : 'github-rest',
    packageCount: results.length,
    results,
    dismissRunnerCandidates: results
      .filter(r => r.safeToDismissRunnerAlerts)
      .map(r => r.package),
    dismissPackageLevelCandidates: results
      .filter(r => r.safeToDismissPackageLevel)
      .map(r => r.package),
  };

  // Default: markdown table. Pass --json for machine-readable output.
  // --table with --json prints JSON on stdout and the table on stderr.
  if (flags.has('json') && !flags.has('table')) {
    console.log(JSON.stringify(payload, null, 2));
  } else if (flags.has('json') && flags.has('table')) {
    console.log(JSON.stringify(payload, null, 2));
    console.error('');
    printTable(results);
  } else {
    printTable(results);
  }
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
