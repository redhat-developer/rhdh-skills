#!/usr/bin/env node
// Fan out to public APIs and collect risk metrics for each changed package.
//
//   collect-metrics.ts --changes <file|-> [--config <path|dir>] [--max <n>] [--now <iso>]
//
// APIs used (all best-effort; failures land in each package's errors[], never fatal):
//   - registry.npmjs.org/<name>            packument: version age, deprecation, license,
//                                          install scripts, publisher, provenance, deps
//   - api.npmjs.org/downloads/...          weekly downloads
//   - api.osv.dev/v1/querybatch            known vulnerabilities for from + to versions
//                                          (every analyzed package, not just the
//                                          detailed tier - it can force a band)
//   - api.securityscorecards.dev           OpenSSF Scorecard (informational)
//
// Output (JSON): { config: {...}, packages: [...], skipped: {...}, errors: [...] }

import { pathToFileURL } from 'node:url';
import type { Change } from './compare-manifests.ts';
import { concreteVersion } from './lib/semver.ts';
import { parseArgs, readJsonInput } from './lib/cli.ts';
import { fetchJson, pLimit } from './lib/http.ts';
import { loadConfig } from './lib/yaml.ts';
import { matchAny } from './lib/match.ts';
import { loadSupportData, resolveSupportLevel } from './lib/support.ts';

const PACKUMENT_HARD_CAP = 150;

export interface PackageMetrics {
  name: string;
  from: string | null;
  to: string | null;
  kind: Change['kind'];
  direct: boolean;
  delta: Change['delta'];
  /** detailed = all APIs, light = packument + OSV, none = delta only */
  analyzed: 'detailed' | 'light' | 'none';
  trusted: boolean;
  supportLevel: string | null;
  supportScoreAdjust: number;
  publishedAt: string | null;
  ageDays: number | null;
  weeklyDownloads: number | null;
  deprecated: string | null;
  provenance: boolean | null;
  installScriptAdded: boolean | null;
  publisherChanged: boolean | null;
  licenseChange: { from: string | null; to: string | null } | null;
  depCountDelta: number | null;
  repositoryUrl: string | null;
  scorecard: number | null;
  /**
   * `severities` maps an *introduced* vuln id to its GHSA severity
   * (LOW | MODERATE | HIGH | CRITICAL). Only introduced ids are looked up -
   * severity does not change how a fixed advisory is credited. An id missing
   * from the map means the severity lookup failed; score.ts treats that as
   * significant (fail closed) rather than silently downgrading it.
   */
  osv: { fixed: string[]; introduced: string[]; severities?: Record<string, string> } | null;
  errors: string[];
}

/** GHSA severity strings that count as "important or higher". */
export const SIGNIFICANT_SEVERITIES = new Set(['HIGH', 'CRITICAL']);

interface Packument {
  time?: Record<string, string>;
  versions?: Record<string, PackumentVersion>;
}

interface PackumentVersion {
  license?: string | { type?: string };
  deprecated?: string;
  scripts?: Record<string, string>;
  dependencies?: Record<string, string>;
  repository?: string | { url?: string };
  dist?: { attestations?: unknown; signatures?: unknown };
  _npmUser?: { name?: string };
}

/** npm API path segment for a package name: keep the scope's "@" literal. */
function npmUrlName(name: string): string {
  return encodeURIComponent(name).replace('%40', '@');
}

function licenseString(v: PackumentVersion | undefined): string | null {
  const l = v?.license;
  if (!l) return null;
  return typeof l === 'string' ? l : (l.type ?? null);
}

function hasInstallScript(v: PackumentVersion | undefined): boolean {
  const scripts = v?.scripts ?? {};
  return ['preinstall', 'install', 'postinstall'].some((k) => k in scripts);
}

function repoUrl(v: PackumentVersion | undefined): string | null {
  const r = v?.repository;
  if (!r) return null;
  return typeof r === 'string' ? r : (r.url ?? null);
}

function githubSlug(url: string | null): string | null {
  if (!url) return null;
  const m = url.match(/github\.com[/:]([^/]+)\/([^/#?]+)/);
  if (!m) return null;
  return `${m[1]}/${m[2].replace(/\.git$/, '')}`;
}

const severityRank: Record<string, number> = { major: 3, minor: 2, patch: 1 };

export async function collectMetrics(args: {
  changes: { changes: Change[]; counts: { total: number } };
  configPath?: string | null;
  maxDetailed?: number | null;
  now?: Date;
}): Promise<Record<string, unknown>> {
  const config = loadConfig(args.configPath ?? process.cwd());
  const supportData = loadSupportData();
  const now = args.now ?? new Date();
  const topErrors: string[] = [];
  const limit = pLimit(8);

  // Removed packages carry no forward risk to rate; note them and move on.
  const candidates = args.changes.changes.filter((c) => c.kind !== 'removed');
  const removed = args.changes.changes.length - candidates.length;

  const ranked = [...candidates].sort(
    (a, b) =>
      Number(b.direct) - Number(a.direct) ||
      (severityRank[b.delta.effectiveType] ?? 0) - (severityRank[a.delta.effectiveType] ?? 0) ||
      a.name.localeCompare(b.name),
  );
  const maxDetailed = args.maxDetailed ?? config.maxPackagesDetailed;

  const packages: PackageMetrics[] = ranked.map((c, i) => {
    const support = resolveSupportLevel(c.name, supportData);
    return {
      name: c.name,
      from: c.from,
      to: c.to,
      kind: c.kind,
      direct: c.direct,
      delta: c.delta,
      analyzed: i < maxDetailed ? 'detailed' : i < PACKUMENT_HARD_CAP ? 'light' : 'none',
      trusted: matchAny(c.name, config.trustedPackages),
      supportLevel: support.level,
      supportScoreAdjust: support.scoreAdjust,
      publishedAt: null,
      ageDays: null,
      weeklyDownloads: null,
      deprecated: null,
      provenance: null,
      installScriptAdded: null,
      publisherChanged: null,
      licenseChange: null,
      depCountDelta: null,
      repositoryUrl: null,
      scorecard: null,
      osv: null,
      errors: [],
    };
  });

  const detailed = packages.filter((p) => p.analyzed === 'detailed');
  // OSV covers every analyzed package, not just the detailed tier. It is the
  // only signal that can force a band (an introduced vulnerability), so
  // rationing it by maxPackagesDetailed means a supply-chain regression is
  // caught or missed depending on where the package happens to sort. The cap
  // exists to bound per-package HTTP fan-out (packument + downloads +
  // scorecard = 3 requests each); OSV is a batch endpoint at 500 queries per
  // request, so widening its scope costs no extra round trips in practice.
  const osvScope = packages.filter((p) => p.analyzed !== 'none');

  // The packument, downloads and OSV phases are independent of each other —
  // run them concurrently (bounded by the shared limiter); only the Scorecard
  // phase needs packument output (repository URLs).

  // --- packuments (detailed + light) --------------------------------------
  const packumentsDone = Promise.all(
    packages
      .filter((p) => p.analyzed !== 'none')
      .map((p) =>
        limit(async () => {
          const to = concreteVersion(p.to);
          const from = concreteVersion(p.from);
          if (!to) {
            p.errors.push(`no concrete target version in "${p.to}"`);
            return;
          }
          const res = await fetchJson<Packument>(`https://registry.npmjs.org/${npmUrlName(p.name)}`);
          if (!res.ok || !res.data) {
            p.errors.push(`registry: ${res.error}`);
            return;
          }
          const packument = res.data;
          const toVersion = packument.versions?.[to];
          const fromVersion = from ? packument.versions?.[from] : undefined;
          if (!toVersion) {
            p.errors.push(`version ${to} not found on npm registry`);
            return;
          }
          const published = packument.time?.[to];
          if (published) {
            p.publishedAt = published;
            p.ageDays = Math.round(((now.getTime() - Date.parse(published)) / 86_400_000) * 10) / 10;
          }
          p.deprecated = toVersion.deprecated ?? null;
          p.provenance = Boolean(toVersion.dist?.attestations);
          p.repositoryUrl = repoUrl(toVersion);
          if (p.analyzed === 'detailed') {
            const toInstall = hasInstallScript(toVersion);
            p.installScriptAdded = fromVersion ? toInstall && !hasInstallScript(fromVersion) : toInstall;
            const fromLicense = licenseString(fromVersion);
            const toLicense = licenseString(toVersion);
            if (fromVersion && fromLicense !== toLicense) {
              p.licenseChange = { from: fromLicense, to: toLicense };
            }
            if (fromVersion) {
              p.depCountDelta =
                Object.keys(toVersion.dependencies ?? {}).length -
                Object.keys(fromVersion.dependencies ?? {}).length;
              const fromUser = fromVersion._npmUser?.name;
              const toUser = toVersion._npmUser?.name;
              p.publisherChanged = fromUser && toUser ? fromUser !== toUser : null;
            }
          }
        }),
      ),
  );

  // --- weekly downloads (detailed) ----------------------------------------
  const downloadsDone = Promise.all(
    detailed.map((p) =>
      limit(async () => {
        const res = await fetchJson<{ downloads?: number }>(
          `https://api.npmjs.org/downloads/point/last-week/${npmUrlName(p.name)}`,
        );
        // A 404 (package unknown to the downloads API) is a data gap, not zero adoption.
        if (!res.ok || typeof res.data?.downloads !== 'number') {
          p.errors.push(`downloads: ${res.error ?? 'no downloads figure in response'}`);
        } else {
          p.weeklyDownloads = res.data.downloads;
        }
      }),
    ),
  );

  // --- OSV vulnerabilities (all analyzed packages, from + to, batched) ----
  const osvQueries: Array<{ pkg: PackageMetrics; side: 'from' | 'to'; version: string }> = [];
  for (const p of osvScope) {
    const from = concreteVersion(p.from);
    const to = concreteVersion(p.to);
    if (to) osvQueries.push({ pkg: p, side: 'to', version: to });
    if (from) osvQueries.push({ pkg: p, side: 'from', version: from });
  }
  const osvResults = new Map<string, string[]>(); // "name@version" -> vuln ids
  const osvDone = (async () => {
    for (let i = 0; i < osvQueries.length; i += 500) {
      const chunk = osvQueries.slice(i, i + 500);
      const res = await fetchJson<{ results?: Array<{ vulns?: Array<{ id: string }> }> }>(
        'https://api.osv.dev/v1/querybatch',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            queries: chunk.map((q) => ({
              package: { ecosystem: 'npm', name: q.pkg.name },
              version: q.version,
            })),
          }),
          timeoutMs: 30_000,
        },
      );
      if (!res.ok || !res.data?.results) {
        topErrors.push(`osv: ${res.error ?? 'no results'}`);
        continue;
      }
      res.data.results.forEach((r, j) => {
        const q = chunk[j];
        osvResults.set(`${q.pkg.name}@${q.version}`, (r.vulns ?? []).map((v) => v.id));
      });
    }
  })();

  await Promise.all([packumentsDone, downloadsDone, osvDone]);

  for (const p of osvScope) {
    const from = concreteVersion(p.from);
    const to = concreteVersion(p.to);
    if (!to) continue;
    const toVulns = osvResults.get(`${p.name}@${to}`);
    const fromVulns = from ? osvResults.get(`${p.name}@${from}`) : [];
    // Both sides must have answered: a failed "from" lookup treated as "no
    // vulns" would misreport shared advisories as introduced (forced HIGH).
    if (toVulns === undefined || (from && fromVulns === undefined)) {
      // Total OSV outage is already in topErrors; only note partial gaps here.
      if (osvResults.size > 0) p.errors.push('osv: lookup incomplete');
      continue; // leave osv null (data gap)
    }
    const toSet = new Set(toVulns);
    const fromSet = new Set(fromVulns ?? []);
    p.osv = {
      fixed: [...fromSet].filter((id) => !toSet.has(id)),
      introduced: [...toSet].filter((id) => !fromSet.has(id)),
    };
  }

  // --- severity for introduced vulns only ---------------------------------
  // querybatch returns just {id, modified}, so severity needs a per-id lookup.
  // Only introduced ids are fetched: severity gates whether a vulnerability
  // raises risk, and a fixed advisory is credited regardless of how severe it
  // was. Introduced vulns are rare (4 across 93 packages in a real sample), and
  // ids are deduplicated across packages, so this is a handful of requests.
  const severityCache = new Map<string, Promise<string | null>>();
  const fetchSeverity = (id: string): Promise<string | null> => {
    let hit = severityCache.get(id);
    if (!hit) {
      hit = limit(async () => {
        const res = await fetchJson<{ database_specific?: { severity?: string } }>(
          `https://api.osv.dev/v1/vulns/${encodeURIComponent(id)}`,
        );
        const sev = res.data?.database_specific?.severity;
        return res.ok && typeof sev === 'string' ? sev.toUpperCase() : null;
      });
      severityCache.set(id, hit);
    }
    return hit;
  };
  await Promise.all(
    osvScope
      .filter((p) => p.osv && p.osv.introduced.length > 0)
      .map(async (p) => {
        const severities: Record<string, string> = {};
        await Promise.all(
          p.osv!.introduced.map(async (id) => {
            const sev = await fetchSeverity(id);
            if (sev) severities[id] = sev;
            else p.errors.push(`osv: severity unavailable for ${id}`);
          }),
        );
        p.osv!.severities = severities;
      }),
  );

  // --- OpenSSF Scorecard (detailed direct packages, informational) --------
  const scorecardCache = new Map<string, Promise<number | null>>();
  await Promise.all(
    detailed
      .filter((p) => p.direct)
      .map((p) =>
        limit(async () => {
          const slug = githubSlug(p.repositoryUrl);
          if (!slug) return;
          if (!scorecardCache.has(slug)) {
            scorecardCache.set(
              slug,
              fetchJson<{ score?: number }>(`https://api.securityscorecards.dev/projects/github.com/${slug}`, {
                okStatuses: [404],
              }).then((res) => (res.ok && res.status !== 404 ? (res.data?.score ?? null) : null)),
            );
          }
          p.scorecard = await scorecardCache.get(slug)!;
        }),
      ),
  );

  return {
    config: {
      source: config.configSource,
      minAgeDays: config.minAgeDays,
      maxPackagesDetailed: maxDetailed,
      trustedPackages: config.trustedPackages,
      supportDataFile: supportData.dataFile,
    },
    counts: args.changes.counts,
    packages,
    skipped: {
      removedPackages: removed,
      lightAnalysis: packages.filter((p) => p.analyzed === 'light').length,
      notAnalyzed: packages.filter((p) => p.analyzed === 'none').length,
    },
    errors: topErrors,
  };
}

// --------------------------------------------------------------------------
// CLI
// --------------------------------------------------------------------------

const HELP = `Usage:
  collect-metrics.ts --changes <file|-> [--config <path|dir>] [--max <n>] [--now <iso-date>]

Reads a change list (output of detect-changes.ts / compare-manifests.ts) and
collects npm registry, download, OSV and Scorecard metrics for each package.`;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv.includes('--help')) {
      console.log(HELP);
      process.exit(0);
    }
    const args = parseArgs(process.argv.slice(2), {
      changes: 'value',
      config: 'value',
      max: 'value',
      now: 'value',
    });
    if (!args.changes) throw new Error('--changes is required');
    const result = await collectMetrics({
      changes: readJsonInput(args.changes as string),
      configPath: args.config as string | undefined,
      maxDetailed: args.max ? Number(args.max) : null,
      now: args.now ? new Date(args.now as string) : undefined,
    });
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(`collect-metrics: ${(err as Error).message}`);
    process.exit(1);
  }
}
