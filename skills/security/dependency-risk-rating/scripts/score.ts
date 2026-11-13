#!/usr/bin/env node
// Deterministic scorer: metrics + judgments + config -> per-package and overall
// risk. Claude never does score arithmetic; qualitative judgments enter only
// through the --judgments file. Same inputs always produce the same output.
//
//   score.ts --metrics <file|-> [--backstage <file>] [--codecov <file>]
//            [--judgments <file>] [--config <path|dir>] [--format json|md]
//
// Judgments file (written by Claude after reading the PR changelog):
//   { "<package>": { "changelog": "bugfix-only"|"routine"|"significant"|"unknown",
//                    "majorIsNodeDropOnly": true|false, "notes": "..." } }
//
// The internal score is 0-10 (clamped); it is displayed as 0-100.

import { pathToFileURL } from 'node:url';
import { parseArgs, readJsonInput } from './lib/cli.ts';
import { SIGNIFICANT_SEVERITIES, type PackageMetrics } from './collect-metrics.ts';
import type { WorkspaceCoverage } from './fetch-codecov.ts';
import { loadConfig, type RiskConfig } from './lib/yaml.ts';

export const DEFAULT_WEIGHTS: Record<string, number> = {
  deltaMinor: 1,
  deltaMajor: 3,
  majorNodeDropOnly: 1, // replaces deltaMajor when the only breaking change is a Node.js drop
  downgrade: 3,
  prereleaseTarget: 2,
  ageBelowMin: 3,
  ageUnder14Days: 1,
  downloadsUnder1k: 2,
  downloadsUnder100k: 1,
  osvIntroduced: 5, // only for GHSA HIGH/CRITICAL ("important or higher") or unresolved severity
  osvFixed: -2,
  deprecated: 3,
  installScriptAdded: 4,
  publisherChanged: 2,
  licenseChanged: 2,
  provenance: -1,
  backstageMatch: -2,
  backstageMismatch: 3,
  changelogBugfixOnly: -1,
  changelogSignificant: 2,
  scorecardLow: 0, // informational by default; set > 0 to penalize OpenSSF score < 4
};

export type Band = 'LOW' | 'MEDIUM' | 'HIGH';
const BAND_ORDER: Band[] = ['LOW', 'MEDIUM', 'HIGH'];

export interface Judgment {
  changelog?: 'bugfix-only' | 'routine' | 'significant' | 'unknown';
  majorIsNodeDropOnly?: boolean;
  notes?: string;
}

interface Reason {
  label: string;
  points: number;
}

export interface PackageScore {
  name: string;
  from: string | null;
  to: string | null;
  direct: boolean;
  analyzed: PackageMetrics['analyzed'];
  score: number; // 0-10 internal
  score100: number; // displayed
  band: Band;
  reasons: Reason[];
  flags: string[]; // trusted-cap, forced-high, data-gaps
  dataGaps: string[];
}

interface BackstageResult {
  skipped?: boolean;
  results?: Array<{ name: string; status: string; expected: string | null }>;
  release?: string;
}

function bandFor(score: number, bands: RiskConfig['bands']): Band {
  if (score >= bands.high) return 'HIGH';
  if (score >= bands.medium) return 'MEDIUM';
  return 'LOW';
}

function maxBand(bands: Band[]): Band {
  return bands.reduce((a, b) => (BAND_ORDER.indexOf(b) > BAND_ORDER.indexOf(a) ? b : a), 'LOW');
}

export function scorePackage(
  p: PackageMetrics,
  judgment: Judgment | undefined,
  backstageStatus: { status: string; expected: string | null } | undefined,
  config: RiskConfig,
): PackageScore {
  const w = { ...DEFAULT_WEIGHTS, ...config.weights };
  const reasons: Reason[] = [];
  const flags: string[] = [];
  const dataGaps: string[] = [...p.errors];
  const add = (label: string, points: number) => {
    if (points !== 0) reasons.push({ label, points });
  };

  // --- version delta ------------------------------------------------------
  const effType = p.delta.effectiveType;
  if (effType === 'major') {
    if (judgment?.majorIsNodeDropOnly) {
      add('major bump, but only drops EOL Node.js support', w.majorNodeDropOnly);
    } else {
      add(p.delta.type === 'minor' ? 'minor bump on a 0.x version (breaking by convention)' : 'major version bump', w.deltaMajor);
    }
  } else if (effType === 'minor') {
    add(p.delta.type === 'patch' ? 'patch bump on a 0.x version' : 'minor version bump', w.deltaMinor);
  } else if (effType === 'unknown' && p.kind === 'added') {
    add('newly added dependency', w.deltaMinor);
  }
  if (p.delta.downgrade) add('version DOWNGRADE', w.downgrade);
  if (p.delta.prereleaseTarget) add('prerelease target version', w.prereleaseTarget);

  // --- freshness ----------------------------------------------------------
  if (p.ageDays !== null) {
    if (p.ageDays < config.minAgeDays) add(`published ${p.ageDays} days ago (< ${config.minAgeDays}d)`, w.ageBelowMin);
    else if (p.ageDays < 14) add(`published ${Math.round(p.ageDays)} days ago`, w.ageUnder14Days);
  } else if (p.analyzed !== 'none') {
    dataGaps.push('release age unknown');
  }

  // --- adoption -----------------------------------------------------------
  if (p.weeklyDownloads !== null) {
    if (p.weeklyDownloads < 1_000) add(`only ${p.weeklyDownloads} downloads/week`, w.downloadsUnder1k);
    else if (p.weeklyDownloads < 100_000) add(`${p.weeklyDownloads.toLocaleString('en-US')} downloads/week`, w.downloadsUnder100k);
  } else if (p.analyzed === 'detailed') {
    dataGaps.push('weekly downloads unknown');
  }

  // --- security -----------------------------------------------------------
  let forcedHigh = false;
  let securityOverride = false;
  if (p.osv) {
    if (p.osv.introduced.length > 0) {
      // Only "important or higher" (GHSA HIGH / CRITICAL) raises risk. An id
      // whose severity could not be resolved counts as significant: failing
      // open would let a lookup error silently downgrade a real regression.
      const sevOf = (id: string) => p.osv!.severities?.[id];
      const significant = p.osv.introduced.filter((id) => {
        const s = sevOf(id);
        return s === undefined || SIGNIFICANT_SEVERITIES.has(s);
      });
      // LOW/MODERATE introductions are dropped: they are the main source of
      // CVE-churn noise on transitive packages. They remain recorded in
      // metrics.json, so re-scoring under a different policy needs no refetch.
      if (significant.length > 0) {
        const label = significant.map((id) => `${id} (${sevOf(id) ?? 'severity unknown'})`).join(', ');
        add(`INTRODUCES known vulnerabilities: ${label}`, w.osvIntroduced);
        forcedHigh = true;
        securityOverride = true;
      }
    }
    if (p.osv.fixed.length > 0) {
      add(`fixes known vulnerabilities: ${p.osv.fixed.join(', ')}`, w.osvFixed);
    }
  } else if (p.analyzed !== 'none') {
    // OSV is queried for every analyzed package, so a null result here is a
    // real gap at any tier - not "we never looked".
    dataGaps.push('vulnerability data unavailable');
  }
  if (p.deprecated) add(`target version is deprecated: "${p.deprecated.slice(0, 80)}"`, w.deprecated);
  if (p.installScriptAdded) {
    add('adds an install script (pre/post/install)', w.installScriptAdded);
    securityOverride = true;
  }
  if (p.publisherChanged) add('published by a different npm user than the previous version', w.publisherChanged);
  if (p.licenseChange) add(`license changed ${p.licenseChange.from ?? '?'} -> ${p.licenseChange.to ?? '?'}`, w.licenseChanged);
  if (p.provenance) add('has npm provenance attestation', w.provenance);
  if (p.scorecard !== null && p.scorecard < 4) add(`OpenSSF Scorecard ${p.scorecard}`, w.scorecardLow);

  // --- ecosystem ----------------------------------------------------------
  if (backstageStatus) {
    if (backstageStatus.status === 'match') add('matches the pinned Backstage release manifest', w.backstageMatch);
    else if (backstageStatus.status === 'mismatch') {
      add(`does NOT match the Backstage release manifest (expected ${backstageStatus.expected})`, w.backstageMismatch);
    }
  }
  if (p.supportLevel !== null && p.supportScoreAdjust !== 0) {
    add(`support level: ${p.supportLevel}`, p.supportScoreAdjust);
  }

  // --- changelog judgment -------------------------------------------------
  if (judgment?.changelog === 'bugfix-only') add('changelog: bugfixes only', w.changelogBugfixOnly);
  else if (judgment?.changelog === 'significant') add('changelog: significant changes', w.changelogSignificant);

  let score = Math.max(0, Math.min(10, reasons.reduce((sum, r) => sum + r.points, 0)));
  let band = bandFor(score, config.bands);

  if (forcedHigh && (!p.trusted || config.trustedOverridesSecurity)) {
    band = 'HIGH';
    score = Math.max(score, config.bands.high);
    flags.push('forced-high');
  } else if (p.trusted) {
    if (securityOverride && config.trustedOverridesSecurity) {
      // A security signal (e.g. newly added install script) keeps its real
      // score even for trusted packages — the allowlist must not hide a
      // potential supply-chain compromise.
      flags.push('trusted-but-security-signal');
    } else {
      const cap = Math.max(0, config.bands.medium - 1);
      if (score > cap || band !== 'LOW') {
        score = Math.min(score, cap);
        band = 'LOW';
        flags.push('trusted-cap');
      }
    }
  }
  if (dataGaps.length > 0) flags.push('data-gaps');

  return {
    name: p.name,
    from: p.from,
    to: p.to,
    direct: p.direct,
    analyzed: p.analyzed,
    score,
    score100: Math.round(score * 10),
    band,
    reasons,
    flags,
    dataGaps,
  };
}

export interface OverallScore {
  band: Band;
  score: number;
  score100: number;
  confidence: 'high' | 'medium' | 'low';
  testConfidence: 'high' | 'medium' | 'low' | 'unknown';
  recommendation: string;
  escalations: string[];
  drivers: string[];
}

export interface ScoreResult {
  overall: OverallScore;
  counts: Record<string, number> & { total: number };
  skipped: Record<string, number>;
  packages: PackageScore[];
  errors: string[];
  backstageRelease: string | null;
}

export function scoreAll(inputs: {
  metrics: {
    packages: PackageMetrics[];
    counts: Record<string, number> & { total: number };
    skipped: Record<string, number>;
    errors: string[];
  };
  backstage?: BackstageResult | null;
  codecov?: { workspaces: WorkspaceCoverage[] } | null;
  judgments?: Record<string, Judgment> | null;
  config: RiskConfig;
}): ScoreResult {
  const { metrics, config } = inputs;
  // backstage.enabled: false in the repo config opts out of the manifest check
  // entirely, even when a backstage result file was passed.
  const backstage = config.backstage.enabled ? inputs.backstage : null;
  const backstageByName = new Map(
    (backstage?.results ?? []).map((r) => [r.name, { status: r.status, expected: r.expected }]),
  );
  const packages = metrics.packages.map((p) =>
    scorePackage(p, inputs.judgments?.[p.name], backstageByName.get(p.name), config),
  );

  const total = metrics.counts.total;
  const fullyAnalyzed = metrics.packages.filter((p) => p.analyzed === 'detailed').length;
  const analyzedFraction = metrics.packages.length === 0 ? 1 : fullyAnalyzed / metrics.packages.length;

  let overallBand = maxBand(packages.map((p) => p.band));
  const escalations: string[] = [];
  if (total > config.manyPackagesThreshold && analyzedFraction < 0.8) {
    const idx = Math.min(BAND_ORDER.indexOf(overallBand) + 1, BAND_ORDER.length - 1);
    if (BAND_ORDER[idx] !== overallBand) {
      overallBand = BAND_ORDER[idx];
      escalations.push(
        `${total} packages changed and only ${Math.round(analyzedFraction * 100)}% were fully analyzed; escalated one band`,
      );
    }
  }
  const overallScore = Math.max(0, ...packages.map((p) => p.score));

  // Confidence in the assessment itself (data completeness).
  const gapCount = packages.filter((p) => p.dataGaps.length > 0).length + metrics.errors.length;
  const confidence: 'high' | 'medium' | 'low' =
    gapCount === 0 && analyzedFraction >= 0.8 ? 'high' : analyzedFraction >= 0.5 ? 'medium' : 'low';

  // Test confidence shapes the recommendation, not the score. Workspaces
  // whose confidence is 'unknown' carry no information — if nothing is known,
  // the result is 'unknown', never a fabricated 'medium'.
  const coverages = inputs.codecov?.workspaces ?? [];
  const known = coverages.filter((wc) => wc.confidence !== 'unknown');
  const testConfidence: 'high' | 'medium' | 'low' | 'unknown' =
    known.length === 0
      ? 'unknown'
      : known.some((wc) => wc.confidence === 'low')
        ? 'low'
        : known.every((wc) => wc.confidence === 'high')
          ? 'high'
          : 'medium';

  // Highest score first, same order as the markdown table.
  const drivers = [...packages]
    .sort((a, b) => b.score100 - a.score100 || a.name.localeCompare(b.name))
    .filter((p) => p.band !== 'LOW')
    .slice(0, 5)
    .map((p) => `${p.name}: ${p.reasons.map((r) => r.label).slice(0, 3).join('; ')}`);

  let recommendation: string;
  if (overallBand === 'LOW') {
    recommendation = 'Safe to merge.';
  } else if (overallBand === 'MEDIUM') {
    recommendation = `Review before merging: ${drivers.join(' | ') || escalations.join(' | ')}.`;
  } else {
    recommendation = `Hold - do not merge without investigation: ${drivers.join(' | ') || escalations.join(' | ')}.`;
  }
  if (testConfidence === 'high') recommendation += ' Test coverage is high; a green CI run is a strong signal.';
  else if (testConfidence === 'low') recommendation += ' Test coverage is low; do not rely on CI alone - verify manually.';
  else if (testConfidence === 'unknown' && overallBand !== 'LOW') {
    recommendation += ' Test coverage is unknown; consider a manual smoke test.';
  }

  return {
    overall: {
      band: overallBand,
      score: overallScore,
      score100: Math.round(overallScore * 10),
      confidence,
      testConfidence,
      recommendation,
      escalations,
      drivers,
    },
    counts: metrics.counts,
    skipped: metrics.skipped,
    packages,
    errors: metrics.errors,
    backstageRelease: backstage?.release ?? null,
  };
}

// --------------------------------------------------------------------------
// Markdown rendering
// --------------------------------------------------------------------------

const MAX_TABLE_ROWS = 30;

function mdEscape(s: string): string {
  // Registry-supplied text (e.g. deprecation messages) may contain newlines,
  // which would terminate the markdown table row mid-cell.
  return s.replace(/\s*\r?\n\s*/g, ' ').replace(/\|/g, '\\|');
}

export function renderMarkdown(r: ScoreResult): string {
  const lines: string[] = [];
  lines.push(`## Dependency update risk: ${r.overall.band} (${r.overall.score100}/100)`);
  lines.push('');
  lines.push(`${r.counts.total} package(s) changed - ${r.counts.direct} direct, ${r.counts.major} major, ${r.counts.minor} minor, ${r.counts.patch} patch, ${r.counts.added} added, ${r.counts.removed} removed.`);
  if (r.backstageRelease) lines.push(`Backstage release pinned by the repo: ${r.backstageRelease}.`);
  lines.push('');
  lines.push('| Package | Change | Risk | Score | Why |');
  lines.push('|---|---|---|---|---|');
  const sorted = [...r.packages].sort((a, b) => b.score100 - a.score100 || a.name.localeCompare(b.name));
  const shown = sorted.slice(0, MAX_TABLE_ROWS);
  for (const p of shown) {
    const change = `${p.from ?? '-'} -> ${p.to ?? '-'}`;
    const why = p.reasons.length
      ? p.reasons.map((re) => `${re.label} (${re.points > 0 ? '+' : ''}${re.points})`).join('; ')
      : 'no risk signals';
    // Compact gap labels for the table: drop URLs and duplicates; full detail stays in JSON.
    const gaps = [...new Set(p.dataGaps.map((g) => g.replace(/\s*\(https?:[^)]*\)/g, '').replace(/: HTTP \d+$/, ' unavailable')))];
    const flagText = [
      p.flags.includes('trusted-cap') ? 'trusted package - capped at LOW' : '',
      p.flags.includes('forced-high') ? 'FORCED HIGH (security)' : '',
      gaps.length > 0 ? `data gaps: ${gaps.join(', ')}` : '',
    ].filter(Boolean).join('; ');
    lines.push(
      `| ${mdEscape(p.name)}${p.direct ? '' : ' (transitive)'} | ${mdEscape(change)} | ${p.band} | ${p.score100} | ${mdEscape([why, flagText].filter(Boolean).join(' - '))} |`,
    );
  }
  if (r.packages.length > shown.length) {
    lines.push('');
    lines.push(`... and ${r.packages.length - shown.length} more package(s) (see JSON output).`);
  }
  const lightTotal = (r.skipped.lightAnalysis ?? 0) + (r.skipped.notAnalyzed ?? 0);
  if (lightTotal > 0) {
    lines.push('');
    lines.push(`Note: ${r.skipped.lightAnalysis ?? 0} package(s) got a lightweight pass (age, delta and vulnerabilities; no downloads/publisher/license checks) and ${r.skipped.notAnalyzed ?? 0} were classified by version delta alone.`);
  }
  lines.push('');
  lines.push(`**Recommendation:** ${r.overall.recommendation}`);
  lines.push('');
  lines.push(`Assessment confidence: ${r.overall.confidence}. Test confidence: ${r.overall.testConfidence}.`);
  for (const e of r.overall.escalations) lines.push(`- ${e}`);
  if (r.errors.length > 0) {
    lines.push('');
    lines.push('Data gaps (APIs unreachable):');
    for (const e of r.errors) lines.push(`- ${e}`);
  }
  return lines.join('\n');
}

// --------------------------------------------------------------------------
// CLI
// --------------------------------------------------------------------------

const HELP = `Usage:
  score.ts --metrics <file|-> [--backstage <file>] [--codecov <file>] [--judgments <file>] [--config <path|dir>] [--format json|md]

Combines collected metrics, the Backstage manifest check, codecov confidence
and Claude's changelog judgments into a deterministic risk score.`;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv.includes('--help')) {
      console.log(HELP);
      process.exit(0);
    }
    const args = parseArgs(process.argv.slice(2), {
      metrics: 'value',
      backstage: 'value',
      codecov: 'value',
      judgments: 'value',
      config: 'value',
      format: 'value',
    });
    if (!args.metrics) throw new Error('--metrics is required');
    const result = scoreAll({
      metrics: readJsonInput<Parameters<typeof scoreAll>[0]['metrics']>(args.metrics as string),
      backstage: args.backstage ? readJsonInput<BackstageResult>(args.backstage as string) : null,
      codecov: args.codecov ? readJsonInput<{ workspaces: WorkspaceCoverage[] }>(args.codecov as string) : null,
      judgments: args.judgments ? readJsonInput<Record<string, Judgment>>(args.judgments as string) : null,
      config: loadConfig((args.config as string) ?? process.cwd()),
    });
    console.log(args.format === 'md' ? renderMarkdown(result) : JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(`score: ${(err as Error).message}`);
    process.exit(1);
  }
}
