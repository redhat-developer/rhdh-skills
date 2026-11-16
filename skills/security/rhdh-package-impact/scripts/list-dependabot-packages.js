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
 * List unique npm packages from open Dependabot alerts for a plugins
 * workspace or the rhdh core product lockfile. Output is the package list
 * used as input to classify-cve-source.js impact assessment.
 *
 * Uses GitHub REST (fetch) only — never the gh CLI — unless --alerts-json
 * supplies a snapshot (no token, no network).
 * Token from GITHUB_TOKEN / GH_TOKEN env or a .env file (see github-auth.js).
 */

import { loadDependabotAlerts } from './dependabot-alerts.js';
import { filterAlertsForLayout, resolveRepoLayout } from './repo-layout.js';

function usage() {
  console.error(`Usage: list-dependabot-packages.js [options] <workspace-or-manifest>

Fetch open Dependabot alerts for a workspace (all manifests under
workspaces/<name>/) or the rhdh core product lockfile (yarn.lock +
packages/ + plugins/), and print the unique package names — the input
set for classify-cve-source.js.

Uses GitHub REST API (not gh). Token: GITHUB_TOKEN / GH_TOKEN in the
environment or a .env file near cwd. --alerts-json skips REST and token.

<workspace-or-manifest> may be:
  homepage
  workspaces/homepage
  workspaces/homepage/yarn.lock
  rhdh            (redhat-developer/rhdh product lockfile)
  yarn.lock       (rhdh core exact manifest)

Options:
  --repo <owner/name>            Remote GitHub repo for REST alerts
                                 (default: detect from GITHUB_REPOSITORY or git origin)
  --repo-root <path>             Local checkout (detects plugins vs rhdh-core)
  --alerts-json <file>           Snapshot of GitHub Dependabot alert objects
                                 (array, or { "alerts": [...] }). No REST.
  --state <open|dismissed|fixed|auto_dismissed|all>
                                 Alert state filter (default: open)
  --scope <runtime|development>  Optional dependency scope filter
  --exact-manifest               Match only the exact yarn.lock path
                                 (default: all manifests under the workspace)
  --packages-only                Print one package name per line (default)
  --json                         Print machine-readable JSON (packages + alerts)
  -h, --help                     Show this help

Examples:
  GITHUB_TOKEN=… node list-dependabot-packages.js homepage
  GITHUB_TOKEN=… node list-dependabot-packages.js --repo redhat-developer/rhdh rhdh --json
  node list-dependabot-packages.js homepage --alerts-json /tmp/dependabot-alerts.json
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const options = {
    state: 'open',
    scope: undefined,
    repo: undefined,
    repoRoot: undefined,
    alertsJson: undefined,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];

    if (arg === '--json') {
      flags.add('json');
    } else if (arg === '--packages-only') {
      flags.add('packages-only');
    } else if (arg === '--exact-manifest') {
      flags.add('exact-manifest');
    } else if (arg === '-h' || arg === '--help') {
      flags.add('help');
    } else if (arg === '--repo') {
      options.repo = argv[++i];
      if (!options.repo) {
        throw new Error('--repo requires owner/name');
      }
    } else if (arg === '--repo-root') {
      options.repoRoot = argv[++i];
      if (!options.repoRoot) {
        throw new Error('--repo-root requires a path');
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
    } else if (arg === '--state') {
      options.state = argv[++i];
      if (!options.state) {
        throw new Error('--state requires a value');
      }
    } else if (arg === '--scope') {
      options.scope = argv[++i];
      if (!['runtime', 'development'].includes(options.scope)) {
        throw new Error('--scope must be runtime or development');
      }
    } else if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
  }

  return { flags, options, positional };
}

function summarizeAlert(alert) {
  return {
    number: alert.number,
    state: alert.state,
    package: alert.dependency?.package?.name ?? null,
    ecosystem: alert.dependency?.package?.ecosystem ?? null,
    manifest: alert.dependency?.manifest_path ?? null,
    scope: alert.dependency?.scope ?? null,
    severity: alert.security_advisory?.severity ?? null,
    summary: alert.security_advisory?.summary ?? null,
    ghsa: alert.security_advisory?.ghsa_id ?? null,
    cve: alert.security_advisory?.cve_id ?? null,
    html_url: alert.html_url ?? null,
  };
}

function filterAlerts(alerts, { layout, scope }) {
  return filterAlertsForLayout(alerts, layout).filter(alert => {
    const dep = alert.dependency ?? {};
    if (scope && dep.scope !== scope) {
      return false;
    }
    return true;
  });
}

function compilePackages(filtered) {
  const byPackage = new Map();

  for (const alert of filtered) {
    const s = summarizeAlert(alert);
    if (!s.package) {
      continue;
    }
    if (!byPackage.has(s.package)) {
      byPackage.set(s.package, {
        package: s.package,
        alertCount: 0,
        manifests: new Set(),
        severities: new Set(),
        alerts: [],
      });
    }
    const entry = byPackage.get(s.package);
    entry.alertCount += 1;
    if (s.manifest) {
      entry.manifests.add(s.manifest);
    }
    if (s.severity) {
      entry.severities.add(s.severity);
    }
    entry.alerts.push(s);
  }

  return [...byPackage.values()]
    .map(entry => ({
      package: entry.package,
      alertCount: entry.alertCount,
      manifests: [...entry.manifests].sort(),
      severities: [...entry.severities].sort(),
      alerts: entry.alerts,
    }))
    .sort((a, b) => a.package.localeCompare(b.package));
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

  const layout = resolveRepoLayout({
    explicitRoot: options.repoRoot,
    workspaceInput: positional[0],
    exactManifest: flags.has('exact-manifest'),
    explicitRepo: options.repo,
    requireCheckout: false,
  });
  const { workspace, exactManifest, lockfileRel, kind } = layout;
  const { alerts: allAlerts, repo: repoFull, fromSnapshot } = await loadDependabotAlerts({
    alertsJson: options.alertsJson,
    explicitRepo: options.repo || layout.defaultDependabotRepo,
    cwd: layout.repoRoot || process.cwd(),
    state: options.state,
  });

  const filtered = filterAlerts(allAlerts, {
    layout,
    scope: options.scope,
  });

  const packages = compilePackages(filtered);
  const packageNames = packages.map(p => p.package);

  if (flags.has('json')) {
    console.log(
      JSON.stringify(
        {
          repo: repoFull,
          workspace,
          layout: kind,
          lockfileRel,
          prefix: layout.alertPrefix,
          exactManifest,
          state: options.state,
          scope: options.scope ?? null,
          source: fromSnapshot ? 'alerts-json' : 'github-rest',
          alertCount: filtered.length,
          packageCount: packageNames.length,
          packages: packageNames,
          packageDetails: packages.map(
            ({ package: name, alertCount, manifests, severities }) => ({
              package: name,
              alertCount,
              manifests,
              severities,
            }),
          ),
          alerts: packages.flatMap(p => p.alerts),
        },
        null,
        2,
      ),
    );
    return;
  }

  // Default: one package per line for piping into classify
  for (const name of packageNames) {
    console.log(name);
  }

  if (packageNames.length === 0) {
    console.error(
      `No ${options.state} Dependabot alerts for ${exactManifest || lockfileRel}`,
    );
  } else {
    console.error(
      `# ${packageNames.length} package(s) from ${filtered.length} alert(s) under ${exactManifest || lockfileRel}`,
    );
  }
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
