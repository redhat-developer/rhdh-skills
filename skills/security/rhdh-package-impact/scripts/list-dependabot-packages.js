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
 * List unique npm packages from open Dependabot alerts for an rhdh-plugins
 * workspace (or a specific manifest). Output is the package list used as
 * input to classify-cve-source.js impact assessment.
 *
 * Uses GitHub REST (fetch) only — never the gh CLI.
 * Token from GITHUB_TOKEN / GH_TOKEN env or a .env file (see github-auth.js).
 */

import { resolveGithubToken } from './github-auth.js';
import { resolveGithubRepo } from './github-repo.js';

const API_BASE = 'https://api.github.com';

function usage() {
  console.error(`Usage: list-dependabot-packages.js [options] <workspace-or-manifest>

Fetch open Dependabot alerts for a workspace (all manifests under
workspaces/<name>/) or a single manifest path, and print the unique package
names — the input set for classify-cve-source.js.

Uses GitHub REST API (not gh). Token: GITHUB_TOKEN / GH_TOKEN in the
environment or a .env file near cwd.

<workspace-or-manifest> may be:
  homepage
  workspaces/homepage
  workspaces/homepage/yarn.lock

Options:
  --repo <owner/name>            Remote GitHub repo for REST alerts\n                                 (default: detect from GITHUB_REPOSITORY or git origin)
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
  GITHUB_TOKEN=… node list-dependabot-packages.js homepage --json
  GITHUB_TOKEN=… node list-dependabot-packages.js workspaces/homepage/yarn.lock --exact-manifest
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const options = {
    state: 'open',
    scope: undefined,
    repo: undefined,
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
  return { owner, repo: name };
}

/**
 * Normalize input to { workspace, prefix, exactManifest }.
 * prefix = workspaces/<name>/  (all alerts under workspace)
 * exactManifest set when input ends with yarn.lock/package.json or --exact-manifest
 */
function normalizeWorkspaceInput(input, exactManifestFlag) {
  let path = input.replace(/^\.\//, '').replace(/\/+$/, '');

  if (!path.includes('/') && !path.endsWith('.lock') && !path.endsWith('.json')) {
    path = `workspaces/${path}`;
  }

  if (path.startsWith('workspaces/')) {
    const rest = path.slice('workspaces/'.length);
    const slash = rest.indexOf('/');
    const workspace = slash === -1 ? rest : rest.slice(0, slash);
    if (!workspace) {
      throw new Error(`Could not parse workspace from "${input}"`);
    }

    const isFile =
      path.endsWith('.lock') ||
      path.endsWith('.json') ||
      exactManifestFlag;

    if (isFile) {
      let manifest = path;
      if (
        exactManifestFlag &&
        !path.endsWith('.lock') &&
        !path.endsWith('.json')
      ) {
        manifest = `${path}/yarn.lock`;
      }
      return {
        workspace,
        prefix: `workspaces/${workspace}/`,
        exactManifest: manifest,
      };
    }

    return {
      workspace,
      prefix: `workspaces/${workspace}/`,
      exactManifest: null,
    };
  }

  throw new Error(
    `Expected workspace name or workspaces/<name>/… path, got "${input}"`,
  );
}

function parseNextLink(linkHeader) {
  if (!linkHeader) {
    return null;
  }
  const match = linkHeader.match(/<([^>]+)>;\s*rel="next"/);
  return match ? match[1] : null;
}

function formatApiError(status, message, repo) {
  if (status === 401 || status === 403) {
    return `Failed to access Dependabot alerts for ${repo} (HTTP ${status}). Check GITHUB_TOKEN permissions. Details: ${message}`;
  }
  if (status === 404) {
    return `Dependabot alerts not found for ${repo} (HTTP 404). Details: ${message}`;
  }
  return `GitHub API error for ${repo}: ${message}`;
}

async function fetchAllAlerts({ token, owner, repo, state }) {
  const alerts = [];
  const params = new URLSearchParams({ per_page: '100' });
  if (state && state !== 'all') {
    params.set('state', state);
  }
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
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { message: text };
      }
    }

    if (!response.ok) {
      throw new Error(
        formatApiError(
          response.status,
          data?.message || response.statusText,
          `${owner}/${repo}`,
        ),
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

function filterAlerts(alerts, { prefix, exactManifest, scope }) {
  return alerts.filter(alert => {
    const dep = alert.dependency ?? {};
    const manifest = dep.manifest_path ?? '';
    const pkg = dep.package?.name;
    if (!pkg || !manifest) {
      return false;
    }
    if (exactManifest) {
      if (manifest !== exactManifest) {
        return false;
      }
    } else if (!manifest.startsWith(prefix)) {
      return false;
    }
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

  const { workspace, prefix, exactManifest } = normalizeWorkspaceInput(
    positional[0],
    flags.has('exact-manifest'),
  );
  const repoFull = await resolveGithubRepo({
    explicitRepo: options.repo,
    requiredFor: 'Dependabot alerts read',
  });
  const { owner, repo } = parseOwnerRepo(repoFull);
  const token = resolveToken();

  const allAlerts = await fetchAllAlerts({
    token,
    owner,
    repo,
    state: options.state,
  });

  const filtered = filterAlerts(allAlerts, {
    prefix,
    exactManifest,
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
          prefix,
          exactManifest,
          state: options.state,
          scope: options.scope ?? null,
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
      `No ${options.state} Dependabot alerts for ${exactManifest || prefix}`,
    );
  } else {
    console.error(
      `# ${packageNames.length} package(s) from ${filtered.length} alert(s) under ${exactManifest || prefix}`,
    );
  }
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
