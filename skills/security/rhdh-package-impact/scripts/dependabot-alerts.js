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
 * Load Dependabot alerts from GitHub REST, or from a trusted-runner snapshot
 * (--alerts-json). Snapshot path skips token + network.
 */

import { readFile } from 'fs/promises';
import { resolve as resolvePath } from 'path';

import { resolveGithubToken } from './github-auth.js';
import { parseOwnerRepo, resolveGithubRepo } from './github-repo.js';

const API_BASE = 'https://api.github.com';

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

function splitOwnerRepo(repoFull) {
  const [owner, repo, ...rest] = String(repoFull || '').split('/');
  if (!owner || !repo || rest.length) {
    throw new Error(`Invalid repo "${repoFull}"; expected owner/name`);
  }
  return { owner, repo };
}

function firstPatchedIdentifier(alert) {
  const vuln = alert.security_vulnerability ?? {};
  if (vuln.first_patched_version?.identifier) {
    return vuln.first_patched_version.identifier;
  }
  if (typeof vuln.first_patched_version === 'string') {
    return vuln.first_patched_version;
  }
  if (alert.firstPatched) {
    return alert.firstPatched;
  }
  if (typeof alert.first_patched_version === 'string') {
    return alert.first_patched_version;
  }
  return alert.first_patched_version?.identifier ?? null;
}

function vulnerableRangeOf(alert) {
  return (
    alert.security_vulnerability?.vulnerable_version_range ??
    alert.vulnerableRange ??
    alert.vulnerable_version_range ??
    null
  );
}

/**
 * GitHub list-alerts objects pass through. Flattened skill JSON
 * (package/manifest/ghsa) is lifted into the same shape so filter/classify
 * work; patch-status still needs vulnerability ranges on those objects.
 */
export function normalizeDependabotAlert(alert) {
  if (!alert || typeof alert !== 'object') {
    throw new Error('--alerts-json contains a non-object alert entry');
  }

  if (alert.dependency) {
    const firstPatched = firstPatchedIdentifier(alert);
    const range = vulnerableRangeOf(alert);
    const vuln = alert.security_vulnerability ?? {};
    return {
      ...alert,
      security_vulnerability: {
        ...vuln,
        vulnerable_version_range: vuln.vulnerable_version_range ?? range,
        first_patched_version: firstPatched
          ? { identifier: firstPatched }
          : vuln.first_patched_version ?? null,
      },
    };
  }

  const firstPatched = firstPatchedIdentifier(alert);
  const range = vulnerableRangeOf(alert);
  return {
    number: alert.number,
    state: alert.state,
    html_url: alert.html_url,
    dependency: {
      package: {
        name: alert.package ?? alert.dependency?.package?.name ?? null,
        ecosystem: alert.ecosystem ?? alert.dependency?.package?.ecosystem ?? 'npm',
      },
      manifest_path: alert.manifest ?? alert.dependency?.manifest_path ?? null,
      scope: alert.scope ?? alert.dependency?.scope ?? null,
    },
    security_advisory: {
      severity: alert.severity ?? alert.security_advisory?.severity ?? null,
      ghsa_id: alert.ghsa ?? alert.security_advisory?.ghsa_id ?? null,
      cve_id: alert.cve ?? alert.security_advisory?.cve_id ?? null,
      summary: alert.summary ?? alert.security_advisory?.summary ?? null,
    },
    security_vulnerability: {
      severity: alert.severity ?? null,
      vulnerable_version_range: range,
      first_patched_version: firstPatched ? { identifier: firstPatched } : null,
    },
  };
}

function extractAlertArray(data, filePath) {
  if (Array.isArray(data)) {
    if (data.length > 0 && Array.isArray(data[0])) {
      return data.flat();
    }
    return data;
  }
  if (data && typeof data === 'object' && Array.isArray(data.alerts)) {
    return data.alerts;
  }
  throw new Error(
    `--alerts-json ${filePath} must be a JSON array of Dependabot alert objects, or an object with an "alerts" array`,
  );
}

export async function loadAlertsFromJson(filePath) {
  const path = resolvePath(filePath);
  let text;
  try {
    text = await readFile(path, 'utf8');
  } catch (error) {
    throw new Error(`Cannot read --alerts-json ${path}: ${error.message}`);
  }

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(
      `--alerts-json ${path} is not valid JSON (use a single array, e.g. gh api --paginate --slurp)`,
    );
  }

  return extractAlertArray(data, path).map(normalizeDependabotAlert);
}

export function alertHasPatchMetadata(alert) {
  const vuln = alert.security_vulnerability ?? {};
  return Boolean(
    vuln.vulnerable_version_range || vuln.first_patched_version?.identifier,
  );
}

export async function fetchDependabotAlerts({
  token,
  owner,
  repo,
  state = 'open',
}) {
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

function filterByState(alerts, state) {
  if (!state || state === 'all') {
    return alerts;
  }
  return alerts.filter(alert => !alert.state || alert.state === state);
}

async function repoLabelForSnapshot({ explicitRepo, cwd }) {
  const fromFlag = parseOwnerRepo(explicitRepo);
  if (fromFlag) {
    return fromFlag;
  }
  const fromEnv = parseOwnerRepo(process.env.GITHUB_REPOSITORY);
  if (fromEnv) {
    return fromEnv;
  }
  if (cwd) {
    try {
      return await resolveGithubRepo({
        explicitRepo,
        cwd,
        requiredFor: 'Dependabot alerts snapshot label',
      });
    } catch {
      // snapshot does not require a resolvable remote
    }
  }
  return 'snapshot';
}

/**
 * @returns {Promise<{ alerts: object[], repo: string, fromSnapshot: boolean }>}
 */
export async function loadDependabotAlerts({
  alertsJson,
  explicitRepo,
  cwd,
  state = 'open',
  requiredFor = 'Dependabot alerts read',
} = {}) {
  if (alertsJson) {
    const alerts = filterByState(await loadAlertsFromJson(alertsJson), state);
    const repo = await repoLabelForSnapshot({ explicitRepo, cwd });
    return { alerts, repo, fromSnapshot: true };
  }

  const repo = await resolveGithubRepo({
    explicitRepo,
    cwd,
    requiredFor,
  });
  const { owner, repo: name } = splitOwnerRepo(repo);
  const token = resolveGithubToken({ requiredFor });
  const alerts = await fetchDependabotAlerts({
    token,
    owner,
    repo: name,
    state,
  });
  return { alerts, repo, fromSnapshot: false };
}
