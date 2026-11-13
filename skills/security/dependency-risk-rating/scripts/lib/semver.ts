// Minimal semver handling for lockfile version comparison. Zero dependencies.

export interface ParsedVersion {
  major: number;
  minor: number;
  patch: number;
  prerelease: string[];
}

export type DeltaType =
  | 'major'
  | 'minor'
  | 'patch'
  | 'prerelease'
  | 'same'
  | 'unknown';

export function parseVersion(raw: string | null | undefined): ParsedVersion | null {
  if (!raw) return null;
  const cleaned = raw.trim().replace(/^[v=]+/, '');
  const m = cleaned.match(/^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/);
  if (!m) return null;
  return {
    major: Number(m[1]),
    minor: Number(m[2]),
    patch: Number(m[3]),
    prerelease: m[4] ? m[4].split('.') : [],
  };
}

function compareIdentifiers(a: string, b: string): number {
  const an = /^\d+$/.test(a);
  const bn = /^\d+$/.test(b);
  if (an && bn) return Number(a) - Number(b);
  if (an) return -1; // numeric identifiers sort before alphanumeric
  if (bn) return 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Standard semver precedence: negative if a < b, positive if a > b, 0 if equal. */
export function compareVersions(aRaw: string, bRaw: string): number | null {
  const a = parseVersion(aRaw);
  const b = parseVersion(bRaw);
  if (!a || !b) return null;
  for (const key of ['major', 'minor', 'patch'] as const) {
    if (a[key] !== b[key]) return a[key] - b[key];
  }
  if (a.prerelease.length === 0 && b.prerelease.length === 0) return 0;
  if (a.prerelease.length === 0) return 1; // release > prerelease
  if (b.prerelease.length === 0) return -1;
  const len = Math.max(a.prerelease.length, b.prerelease.length);
  for (let i = 0; i < len; i++) {
    if (a.prerelease[i] === undefined) return -1;
    if (b.prerelease[i] === undefined) return 1;
    const c = compareIdentifiers(a.prerelease[i], b.prerelease[i]);
    if (c !== 0) return c;
  }
  return 0;
}

/** Semver-aware maximum; falls back to string comparison for unparseable entries. */
export function maxVersion(versions: Iterable<string>): string | null {
  let best: string | null = null;
  for (const v of versions) {
    if (best === null) {
      best = v;
      continue;
    }
    const cmp = compareVersions(best, v);
    if (cmp === null ? v > best : cmp < 0) best = v;
  }
  return best;
}

/**
 * Pick the highest concrete version out of values like "2.0.0, 2.1.2" (multiple
 * resolved versions) or "^4.1.0" (a range). Returns null when nothing parses.
 */
export function concreteVersion(value: string | null | undefined): string | null {
  if (!value) return null;
  const candidates = value
    .split(',')
    .map((part) => part.trim().match(/\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?/)?.[0])
    .filter((v): v is string => Boolean(v) && parseVersion(v!) !== null);
  return maxVersion(candidates);
}

export interface Delta {
  /** Highest version component that changed. */
  type: DeltaType;
  /**
   * 0.x-adjusted severity: for 0.x versions a minor bump is treated as major
   * and a patch bump as minor (the semver spec makes no compatibility promise
   * for 0.x, and the Backstage ecosystem bumps minor for breaking changes).
   */
  effectiveType: DeltaType;
  /** True when `to` sorts below `from`. */
  downgrade: boolean;
  /** True when the target version is a prerelease (e.g. 1.0.0-beta.1). */
  prereleaseTarget: boolean;
}

export function classifyDelta(from: string | null | undefined, to: string | null | undefined): Delta {
  const a = parseVersion(from);
  const b = parseVersion(to);
  const unknown: Delta = { type: 'unknown', effectiveType: 'unknown', downgrade: false, prereleaseTarget: false };
  if (!a || !b) return unknown;

  const cmp = compareVersions(from as string, to as string) ?? 0;
  const downgrade = cmp > 0;
  const prereleaseTarget = b.prerelease.length > 0;

  let type: DeltaType;
  if (a.major !== b.major) type = 'major';
  else if (a.minor !== b.minor) type = 'minor';
  else if (a.patch !== b.patch) type = 'patch';
  else if (a.prerelease.join('.') !== b.prerelease.join('.')) type = 'prerelease';
  else type = 'same';

  let effectiveType = type;
  if (b.major === 0 && a.major === 0) {
    if (type === 'minor') effectiveType = 'major';
    else if (type === 'patch') effectiveType = 'minor';
  }
  return { type, effectiveType, downgrade, prereleaseTarget };
}
