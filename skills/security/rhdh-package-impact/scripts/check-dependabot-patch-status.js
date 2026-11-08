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
 * Uses GitHub REST (fetch) only — never the gh CLI.
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
import {
  buildVersionStatuses,
  patchedVersions,
  resolveVersionsByPath,
} from './resolve-versions-by-path.js';

const execFile = promisify(execFileCb);
const __dirname = dirname(fileURLToPath(import.meta.url));

const API_BASE = 'https://api.github.com';

function usage() {
  console.error(`Usage: check-dependabot-patch-status.js [options] <workspace> [package]

For a workspace (and optional package), fetch open Dependabot alerts, compare
resolved yarn.lock versions to each alert's first_patched_version / vulnerable
range, run impact classification, and report whether runner alerts can be
dismissed because prod paths are patched (or no PLUGIN_PROD alerts remain).

Uses GitHub REST (not gh). Token: GITHUB_TOKEN / GH_TOKEN in the
environment or a .env file near cwd.
Needs --repo-root / RHDH_PLUGINS_ROOT (or cwd in a checkout)
for yarn.lock + classify.

If [package] is omitted, checks every package with open alerts in the workspace.

Options:
  --repo-root <path>             Local checkout path for yarn.lock / yarn why
  --repo <owner/name>            Remote GitHub repo for REST alerts
                                 (default: detect from GITHUB_REPOSITORY or git origin in --repo-root)
  --table                        Markdown classification table (default)
  --json                         Machine-readable JSON
  -h, --help                     Show this help

Examples:
  GITHUB_TOKEN=… node check-dependabot-patch-status.js \\
    --repo-root /path/to/plugins-repo extensions
  GITHUB_TOKEN=… node check-dependabot-patch-status.js \\
    --repo-root /path/to/plugins-repo extensions --json
  GITHUB_TOKEN=… node check-dependabot-patch-status.js \\
    --repo-root /path/to/plugins-repo extensions lodash --table
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
      throw new Error(
        `RHDH_PLUGINS_ROOT=${root} has no workspaces/ directory`,
      );
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

function resolveToken() {
  return resolveGithubToken({
    requiredFor: 'Dependabot alerts read',
  });
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

function classifyManifest(manifestPath, scope) {
  if (!manifestPath) {
    return 'UNKNOWN';
  }
  if (manifestPath.includes('/plugins/')) {
    return scope === 'development' ? 'PLUGIN_DEV' : 'PLUGIN_PROD';
  }
  if (
    /\/packages\/(backend|app|app-legacy)\/package\.json$/.test(manifestPath)
  ) {
    return 'RUNNER';
  }
  if (manifestPath.endsWith('/yarn.lock') || manifestPath.endsWith('yarn.lock')) {
    return 'LOCKFILE';
  }
  if (scope === 'development') {
    return 'PLUGIN_DEV';
  }
  return 'UNKNOWN';
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
    const manifestClass = classifyManifest(s.manifest, s.scope);
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
  const hasPluginProdReach =
    typeof classification === 'string' && classification.includes('PLUGIN_PROD');

  const openPluginProd = counts.PLUGIN_PROD || 0;
  const openRunner = counts.RUNNER || 0;
  const openLockfile = counts.LOCKFILE || 0;
  const openPluginDev = counts.PLUGIN_DEV || 0;

  // Mode A: whole package is exact local-dev label
  const packageLevelRunnerOnly = classification === 'RUNNER';
  const packageLevelPluginDevOnly = classification === 'PLUGIN_DEV';
  const packageLevelWorkspaceDevOnly = classification === 'WORKSPACE_DEV';

  // Mode B: lockfile versions meet patch level; only runner package.json alerts remain
  const patchedEverywhereExceptRunner =
    openPluginProd === 0 && openRunner > 0 && fullyPatchedInLockfile;

  // Lockfile-only remaining alerts after versions are patched
  const lockfileOnlyRemaining =
    openPluginProd === 0 &&
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
  } else if (packageLevelWorkspaceDevOnly) {
    verdict = 'WORKSPACE_DEV_ONLY';
    safeToDismissPackageLevel = true;
  } else if (openPluginProd > 0) {
    verdict = 'PLUGIN_PROD_ALERTS_REMAIN';
  } else if (patchedEverywhereExceptRunner) {
    verdict = 'PATCHED_EXCEPT_RUNNER';
    safeToDismissRunnerAlerts = true;
  } else if (lockfileOnlyRemaining && fullyPatchedInLockfile) {
    verdict = 'LOCKFILE_ALERTS_ONLY';
  } else if (
    openPluginProd === 0 &&
    hasPluginProdReach &&
    patchedOnProdPaths &&
    anyUnpatchedInLockfile
  ) {
    verdict = 'PROD_PATCHED_DEV_UNPATCHED';
  } else if (
    fullyPatchedInLockfile &&
    openPluginProd === 0 &&
    openRunner === 0 &&
    openLockfile === 0 &&
    openPluginDev === 0
  ) {
    verdict = 'FULLY_PATCHED';
  } else if (anyUnpatchedInLockfile && openPluginProd === 0) {
    verdict = 'UNPATCHED_IN_LOCKFILE_NO_PROD_ALERTS';
  } else {
    verdict = 'NEEDS_REVIEW';
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
    r.openAlertCounts.PLUGIN_PROD || 0,
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

  if (positional.length < 1 || positional.length > 2) {
    usage();
    process.exit(1);
  }

  const [workspace, onlyPackage] = positional;
  const repoRoot = findRepoRoot(options.repoRoot);
  const workspaceDir = resolvePath(repoRoot, 'workspaces', workspace);
  const lockPath = resolvePath(workspaceDir, 'yarn.lock');

  if (!existsSync(lockPath)) {
    throw new Error(`No yarn.lock at workspaces/${workspace}`);
  }

  const resolvedRepo = await resolveGithubRepo({
    explicitRepo: options.repo,
    cwd: repoRoot,
    requiredFor: 'Dependabot alerts read',
  });
  const { owner, repo, full: repoFull } = parseOwnerRepo(resolvedRepo);
  const token = resolveToken();
  const semver = loadSemver(repoRoot);
  const lockfileText = await readFile(lockPath, 'utf8');

  const allAlerts = await fetchOpenAlerts({ token, owner, repo });
  const prefix = `workspaces/${workspace}/`;
  const workspaceAlerts = allAlerts.filter(a => {
    const manifest = a.dependency?.manifest_path || '';
    return manifest === 'yarn.lock'
      ? workspace === 'root'
      : manifest.startsWith(prefix);
  });

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
      packageCount: 0,
      results: [],
    };
    if (flags.has('json') && !flags.has('table')) {
      console.log(JSON.stringify(empty, null, 2));
    } else {
      console.log(`No open Dependabot alerts under ${prefix}`);
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
        pluginProd: classification.pluginProd ?? [],
        pluginDev: classification.pluginDev ?? [],
      });
    }

    results.push(
      assessPackage({
        workspace,
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
    repoRoot,
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
