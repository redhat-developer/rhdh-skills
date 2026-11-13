#!/usr/bin/env node
// Fetch test coverage per workspace from codecov.io, falling back to the
// manual testConfidence overrides in the repo config. Coverage never changes
// the risk score - it shapes the recommendation ("CI can be trusted" vs
// "manual verification suggested").
//
//   fetch-codecov.ts [--config <path|dir>] [--workspace <dir>]
//
// Output (JSON): { workspaces: [{path, coverage, confidence, source}], notes }

import { pathToFileURL } from 'node:url';
import { parseArgs } from './lib/cli.ts';
import { fetchJson } from './lib/http.ts';
import { loadConfig } from './lib/yaml.ts';

export interface WorkspaceCoverage {
  path: string;
  coverage: number | null;
  confidence: 'high' | 'medium' | 'low' | 'unknown';
  source: 'codecov' | 'override' | 'none';
}

function confidenceFromCoverage(coverage: number): WorkspaceCoverage['confidence'] {
  if (coverage >= 80) return 'high';
  if (coverage >= 60) return 'medium';
  return 'low';
}

function normalizeConfidence(value: string): WorkspaceCoverage['confidence'] {
  return value === 'high' || value === 'medium' || value === 'low' ? value : 'unknown';
}

async function codecovCoverage(
  service: string,
  owner: string,
  repo: string,
  token: string | undefined,
  notes: string[],
): Promise<number | null> {
  const headers: Record<string, string> = token ? { authorization: `Bearer ${token}` } : {};
  const base = `https://api.codecov.io/api/v2/${service}/${owner}/repos/${repo}`;
  // Repo detail carries totals for the default branch; fall back to the latest commit.
  const detail = await fetchJson<{ totals?: { coverage?: number } }>(`${base}/`, { headers });
  if (detail.ok && typeof detail.data?.totals?.coverage === 'number') {
    return detail.data.totals.coverage;
  }
  const commits = await fetchJson<{ results?: Array<{ totals?: { coverage?: number } }> }>(
    `${base}/commits?page_size=1`,
    { headers },
  );
  if (commits.ok) {
    const coverage = commits.data?.results?.[0]?.totals?.coverage;
    if (typeof coverage === 'number') return coverage;
  }
  notes.push(`codecov: no coverage for ${owner}/${repo} (${detail.error ?? commits.error ?? 'no totals in response'})`);
  return null;
}

export async function fetchCodecov(args: {
  configPath?: string | null;
  workspace?: string | null;
}): Promise<Record<string, unknown>> {
  const config = loadConfig(args.configPath ?? process.cwd());
  const notes: string[] = [];
  const workspaces = new Map<string, WorkspaceCoverage>();

  const wanted = (path: string) => !args.workspace || path === args.workspace;

  if (config.codecov) {
    const codecov = config.codecov;
    const token = process.env[codecov.tokenEnv || 'CODECOV_TOKEN'];
    if (!token) notes.push(`codecov: env var ${codecov.tokenEnv || 'CODECOV_TOKEN'} not set; trying anonymous access`);
    const entries = Object.entries(codecov.repos).filter(([path]) => wanted(path));
    const coverages = await Promise.all(
      entries.map(([, repo]) => codecovCoverage(codecov.service, codecov.owner, repo, token, notes)),
    );
    entries.forEach(([path], i) => {
      const coverage = coverages[i];
      workspaces.set(path, {
        path,
        coverage,
        confidence: coverage === null ? 'unknown' : confidenceFromCoverage(coverage),
        source: coverage === null ? 'none' : 'codecov',
      });
    });
  }

  // Manual testConfidence entries always win: an explicit human setting
  // overrides the automatic codecov number (and fills gaps when codecov is
  // absent or unreachable).
  for (const [path, value] of Object.entries(config.testConfidence)) {
    if (!wanted(path)) continue;
    workspaces.set(path, {
      path,
      coverage: workspaces.get(path)?.coverage ?? null,
      confidence: normalizeConfidence(String(value)),
      source: 'override',
    });
  }

  if (workspaces.size === 0) {
    notes.push('no codecov mapping or testConfidence entries configured');
  }
  return { workspaces: [...workspaces.values()], notes };
}

const HELP = `Usage:
  fetch-codecov.ts [--config <path|dir>] [--workspace <dir>]

Reads the codecov/testConfidence configuration from .dependency-risk.yaml and
reports per-workspace test confidence.`;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv.includes('--help')) {
      console.log(HELP);
      process.exit(0);
    }
    const args = parseArgs(process.argv.slice(2), { config: 'value', workspace: 'value' });
    const result = await fetchCodecov({
      configPath: args.config as string | undefined,
      workspace: args.workspace as string | undefined,
    });
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(`fetch-codecov: ${(err as Error).message}`);
    process.exit(1);
  }
}
