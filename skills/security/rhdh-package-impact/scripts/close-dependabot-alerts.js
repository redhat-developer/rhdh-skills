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

import { createInterface } from 'readline';

import { resolveGithubToken } from './github-auth.js';
import { resolveGithubRepo } from './github-repo.js';

const DISMISS_REASONS = [
  'fix_started',
  'inaccurate',
  'no_bandwidth',
  'not_used',
  'tolerable_risk',
];

const API_BASE = 'https://api.github.com';

function usage() {
  console.error(`Usage: close-dependabot-alerts.js [options] <manifest> <package>

List open Dependabot alerts for a package under a workspace manifest, and
optionally dismiss (close) them via the GitHub REST API (fetch — never gh).

Talks to a remote GitHub repo only (no local checkout required). By default it
uses GITHUB_REPOSITORY or the local git origin remote; override with --repo.

Requires a GitHub PAT with Dependabot alerts access (security_events or
fine-grained "Dependabot alerts" read/write). Set via:

  export GITHUB_TOKEN=ghp_...
  # or: export GH_TOKEN=ghp_...
  # or: put GITHUB_TOKEN=... in a .env file near cwd
  # Do not use: --token, gh auth / gh api, git credential helper

<manifest> is the Dependabot manifest_path in the GitHub repo, e.g.:
  workspaces/quickstart/yarn.lock
  workspaces/quickstart          (implies .../yarn.lock)
  quickstart                     (implies workspaces/quickstart/yarn.lock)

Options:
  --repo <owner/name>            Remote GitHub repo for REST alerts
                                 (default: detect from GITHUB_REPOSITORY or git origin)
  --state <open|dismissed|fixed|auto_dismissed|all>
                                 Alert state filter (default: open)
  --scope <runtime|development>  Optional Dependabot dependency scope filter
  --close                        Dismiss matching alerts (requires --reason)
  --reason <reason>              One of: ${DISMISS_REASONS.join(', ')}
  --comment <text>               Optional dismissal comment (max 280 chars)
  --yes                          Skip interactive [y/N] confirmation when closing
                                 (default: prompt; do not use unless requested)
  --json                         Print machine-readable JSON
  -h, --help                     Show this help

Examples:
  GITHUB_TOKEN=ghp_... node close-dependabot-alerts.js \\
    workspaces/quickstart/yarn.lock lodash
  GITHUB_TOKEN=ghp_... node close-dependabot-alerts.js quickstart immutable --json
  GITHUB_TOKEN=ghp_... node close-dependabot-alerts.js quickstart tmp \\
    --close --reason not_used --comment "runner-only; classification=RUNNER"
  # Interactive [y/N] prompt unless --yes is passed
`);
}

function parseArgs(argv) {
  const flags = new Set();
  const options = {
    state: 'open',
    comment: undefined,
    reason: undefined,
    scope: undefined,
    repo: undefined,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];

    if (arg === '--json') {
      flags.add('json');
    } else if (arg === '--close') {
      flags.add('close');
    } else if (arg === '--yes') {
      flags.add('yes');
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
    } else if (arg === '--reason') {
      options.reason = argv[++i];
      if (!options.reason) {
        throw new Error('--reason requires a value');
      }
    } else if (arg === '--comment') {
      options.comment = argv[++i];
      if (options.comment === undefined) {
        throw new Error('--comment requires a value');
      }
    } else if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
  }

  return { flags, options, positional };
}

function normalizeManifestPath(input) {
  let path = input.replace(/^\.\//, '').replace(/\/+$/, '');

  if (
    !path.includes('/') &&
    !path.endsWith('.lock') &&
    !path.endsWith('.json')
  ) {
    path = `workspaces/${path}/yarn.lock`;
  } else if (
    path.startsWith('workspaces/') &&
    !path.endsWith('.lock') &&
    !path.endsWith('.json')
  ) {
    path = `${path}/yarn.lock`;
  }

  return path;
}

function resolveToken() {
  return resolveGithubToken({
    requiredFor: 'Dependabot alerts read/write to dismiss',
  });
}

function parseOwnerRepo(repo) {
  const [owner, name, ...rest] = repo.split('/');
  if (!owner || !name || rest.length) {
    throw new Error(`Invalid --repo "${repo}"; expected owner/name`);
  }
  return { owner, repo: name };
}

function formatApiError(status, message, repo) {
  if (status === 401 || status === 403) {
    return `Failed to access Dependabot alerts for ${repo} (HTTP ${status}). Check that GITHUB_TOKEN is valid and has security_events / Dependabot alerts permission. Details: ${message}`;
  }
  if (status === 404) {
    return `Dependabot alerts not found for ${repo} (HTTP 404). Confirm the repo name and that Dependabot alerts are enabled, and that the token can see security alerts. Details: ${message}`;
  }
  return `GitHub API error for ${repo}: ${message}`;
}

/** Dependabot alerts use Link-header cursor pagination (not ?page=). */
function parseNextLink(linkHeader) {
  if (!linkHeader) {
    return null;
  }
  const match = linkHeader.match(/<([^>]+)>;\s*rel="next"/);
  return match ? match[1] : null;
}

async function githubRequest(token, method, pathOrUrl, body) {
  const url = pathOrUrl.startsWith('http')
    ? pathOrUrl
    : `${API_BASE}${pathOrUrl}`;
  const response = await fetch(url, {
    method,
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'plugins-package-impact',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
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

  return { response, data };
}

async function fetchAlerts({
  token,
  owner,
  repo,
  packageName,
  manifest,
  state,
  scope,
}) {
  const alerts = [];
  const params = new URLSearchParams({ per_page: '100' });
  if (state && state !== 'all') {
    params.set('state', state);
  }
  let nextUrl = `${API_BASE}/repos/${owner}/${repo}/dependabot/alerts?${params}`;

  try {
    while (nextUrl) {
      const { response, data } = await githubRequest(token, 'GET', nextUrl);

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

    return alerts.filter(alert => {
      const dep = alert.dependency ?? {};
      const pkg = dep.package ?? {};
      if (pkg.name !== packageName) {
        return false;
      }
      if (dep.manifest_path !== manifest) {
        return false;
      }
      if (scope && dep.scope !== scope) {
        return false;
      }
      return true;
    });
  } catch (error) {
    if (
      error.message.startsWith('Failed to access') ||
      error.message.startsWith('Dependabot') ||
      error.message.startsWith('GitHub API')
    ) {
      throw error;
    }
    throw new Error(
      formatApiError(undefined, error.message, `${owner}/${repo}`),
    );
  }
}

function summarizeAlert(alert) {
  return {
    number: alert.number,
    state: alert.state,
    severity: alert.security_advisory?.severity ?? null,
    summary: alert.security_advisory?.summary ?? null,
    ghsa: alert.security_advisory?.ghsa_id ?? null,
    cve: alert.security_advisory?.cve_id ?? null,
    package: alert.dependency?.package?.name ?? null,
    ecosystem: alert.dependency?.package?.ecosystem ?? null,
    manifest: alert.dependency?.manifest_path ?? null,
    scope: alert.dependency?.scope ?? null,
    html_url: alert.html_url ?? null,
  };
}

async function confirm(prompt) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = await new Promise(resolve => {
      rl.question(prompt, resolve);
    });
    return ['y', 'yes'].includes(
      String(answer).trim().toLocaleLowerCase('en-US'),
    );
  } finally {
    rl.close();
  }
}

async function dismissAlert({
  token,
  owner,
  repo,
  alertNumber,
  reason,
  comment,
}) {
  const body = {
    state: 'dismissed',
    dismissed_reason: reason,
  };
  if (comment) {
    body.dismissed_comment = comment.slice(0, 280);
  }

  const { response, data } = await githubRequest(
    token,
    'PATCH',
    `/repos/${owner}/${repo}/dependabot/alerts/${alertNumber}`,
    body,
  );

  if (!response.ok) {
    throw new Error(
      formatApiError(
        response.status,
        data?.message || response.statusText,
        `${owner}/${repo}`,
      ),
    );
  }

  return data;
}

function printAlerts(alerts) {
  if (!alerts.length) {
    console.log('No matching Dependabot alerts.');
    return;
  }

  console.log(`Found ${alerts.length} matching alert(s):\n`);
  for (const alert of alerts) {
    const s = summarizeAlert(alert);
    console.log(`#${s.number}  [${s.severity ?? 'unknown'}]  state=${s.state}`);
    console.log(`  package:  ${s.package} (${s.ecosystem})`);
    console.log(`  manifest: ${s.manifest}`);
    console.log(`  scope:    ${s.scope ?? 'n/a'}`);
    if (s.ghsa || s.cve) {
      console.log(
        `  ids:      ${[s.ghsa, s.cve].filter(Boolean).join(' / ')}`,
      );
    }
    if (s.summary) {
      console.log(`  summary:  ${s.summary}`);
    }
    if (s.html_url) {
      console.log(`  url:      ${s.html_url}`);
    }
    console.log('');
  }
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

  const [manifestInput, packageName] = positional;
  const manifest = normalizeManifestPath(manifestInput);
  const repoFull = await resolveGithubRepo({
    explicitRepo: options.repo,
    requiredFor: 'Dependabot alerts read/write to dismiss',
  });
  const { owner, repo } = parseOwnerRepo(repoFull);
  const token = resolveToken();

  if (flags.has('close')) {
    if (!options.reason) {
      throw new Error(
        `--close requires --reason (${DISMISS_REASONS.join(', ')})`,
      );
    }
    if (!DISMISS_REASONS.includes(options.reason)) {
      throw new Error(
        `Invalid --reason "${options.reason}". Expected one of: ${DISMISS_REASONS.join(', ')}`,
      );
    }
  }

  const alerts = await fetchAlerts({
    token,
    owner,
    repo,
    packageName,
    manifest,
    state: options.state,
    scope: options.scope,
  });

  const summaries = alerts.map(summarizeAlert);

  if (flags.has('json') && !flags.has('close')) {
    console.log(
      JSON.stringify(
        {
          repo: repoFull,
          package: packageName,
          manifest,
          state: options.state,
          scope: options.scope ?? null,
          count: summaries.length,
          alerts: summaries,
        },
        null,
        2,
      ),
    );
    return;
  }

  console.log(`Repo:     ${repoFull}`);
  console.log(`Package:  ${packageName}`);
  console.log(`Manifest: ${manifest}`);
  console.log(`State:    ${options.state}`);
  if (options.scope) {
    console.log(`Scope:    ${options.scope}`);
  }
  console.log('');
  printAlerts(alerts);

  if (!flags.has('close')) {
    if (alerts.length) {
      console.log(
        'Dry run only. Re-run with --close --reason <reason> [--comment "..."] [--yes] to dismiss.',
      );
    }
    return;
  }

  const dismissible = alerts.filter(a => a.state === 'open');
  if (!dismissible.length) {
    console.log('Nothing to close (no open matching alerts).');
    return;
  }

  if (!flags.has('yes')) {
    const ok = await confirm(
      `Dismiss ${dismissible.length} alert(s) with reason "${options.reason}"? [y/N] `,
    );
    if (!ok) {
      console.log('Aborted.');
      process.exit(1);
    }
  }

  const results = [];
  for (const alert of dismissible) {
    process.stdout.write(`Dismissing #${alert.number}... `);
    try {
      const updated = await dismissAlert({
        token,
        owner,
        repo,
        alertNumber: alert.number,
        reason: options.reason,
        comment: options.comment,
      });
      console.log(`ok (state=${updated.state})`);
      results.push({
        number: alert.number,
        ok: true,
        state: updated.state,
        dismissed_reason: updated.dismissed_reason ?? options.reason,
      });
    } catch (error) {
      console.log('failed');
      console.error(`  ${error.message}`);
      results.push({ number: alert.number, ok: false, error: error.message });
    }
  }

  if (flags.has('json')) {
    console.log(
      JSON.stringify(
        { repo: repoFull, manifest, package: packageName, results },
        null,
        2,
      ),
    );
  }

  if (results.some(r => !r.ok)) {
    process.exit(1);
  }
}

main().catch(error => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
