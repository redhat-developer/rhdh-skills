#!/usr/bin/env node
// Core differ: compare OLD vs NEW lockfile (and/or package.json) content and
// emit the list of changed packages. Works on full file contents, never on
// unified diffs (yarn.lock hunks routinely omit the entry header).
//
// Usage:
//   compare-manifests.ts --old-lock <file|-> --new-lock <file|->
//                        [--old-pkg <file>] [--new-pkg <file>]
//                        [--format auto|yarn|yarn-berry|npm]
//   compare-manifests.ts --old-pkg <file> --new-pkg <file>   # manifest-only diff
//
// Output (JSON): { format, changes: [{name, from, to, kind, direct, delta}], counts }

import {
  classifyDelta,
  concreteVersion,
  compareVersionOrder,
  compareVersions,
  maxVersion,
  parseVersion,
  type Delta,
} from './lib/semver.ts';
import { parseArgs, readInput } from './lib/cli.ts';

export type LockFormat = 'yarn' | 'yarn-berry' | 'npm' | 'package-json';

export interface Change {
  name: string;
  /** Version before; null for an added resolution. One row per bump. */
  from: string | null;
  /** Version after; null for a removed resolution. */
  to: string | null;
  kind: 'added' | 'removed' | 'updated';
  /** True when the package appears in the old or new package.json. */
  direct: boolean;
  delta: Delta;
}

export interface CompareResult {
  format: LockFormat;
  changes: Change[];
  counts: {
    total: number;
    direct: number;
    added: number;
    removed: number;
    major: number;
    minor: number;
    patch: number;
    other: number;
  };
}

// --------------------------------------------------------------------------
// Lockfile parsers: file content -> Map<packageName, Set<resolvedVersion>>
// --------------------------------------------------------------------------

export function detectFormat(content: string): LockFormat {
  const head = content.slice(0, 2000);
  if (head.includes('# yarn lockfile v1')) return 'yarn';
  if (/^\s*[{]/.test(head)) return 'npm';
  if (head.includes('__metadata:') || /@npm:/.test(content.slice(0, 20_000))) return 'yarn-berry';
  // Unmarked yarn v1 files still follow the same entry syntax.
  return 'yarn';
}

/** Extract the package name from a dependency spec like "@scope/name@^1.0.0" or "name@npm:1.x". */
function nameFromSpec(spec: string): string | null {
  const at = spec.indexOf('@', spec.startsWith('@') ? 1 : 0);
  if (at <= 0) return null;
  return spec.slice(0, at);
}

function addVersion(map: Map<string, Set<string>>, name: string, version: string): void {
  let set = map.get(name);
  if (!set) map.set(name, (set = new Set()));
  set.add(version);
}

export function parseYarnV1(content: string): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  let currentNames: string[] = [];
  for (const line of content.split(/\r?\n/)) {
    if (line === '' || line.startsWith('#')) continue;
    if (!line.startsWith(' ')) {
      // Entry header: comma-separated (possibly quoted) specs ending with ":".
      const header = line.replace(/:\s*$/, '');
      currentNames = [];
      for (const part of header.split(/,\s*/)) {
        const spec = part.replace(/^"+|"+$/g, '');
        const name = nameFromSpec(spec);
        if (name && !currentNames.includes(name)) currentNames.push(name);
      }
    } else {
      // Anchor to the entry's own indent (2 spaces): a deeper-nested dependency
      // literally named "version" must not match.
      const m = line.match(/^ {2}version\s+"([^"]+)"/);
      if (m) for (const name of currentNames) addVersion(map, name, m[1]);
    }
  }
  return map;
}

export function parseYarnBerry(content: string): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  let currentNames: string[] = [];
  let skipEntry = false;
  for (const line of content.split(/\r?\n/)) {
    if (line === '' || line.startsWith('#')) continue;
    if (!line.startsWith(' ')) {
      const header = line.replace(/:\s*$/, '');
      currentNames = [];
      skipEntry = header === '__metadata';
      if (skipEntry) continue;
      for (const part of header.split(/,\s*/)) {
        const spec = part.replace(/^"+|"+$/g, '');
        // Specs look like "name@npm:^1.0.0", "name@workspace:packages/x", "name@patch:...".
        // Workspace entries are the repo's own packages, not registry dependencies.
        if (/@workspace:/.test(spec)) continue;
        const name = nameFromSpec(spec);
        if (name && !currentNames.includes(name)) currentNames.push(name);
      }
    } else if (!skipEntry) {
      const m = line.match(/^ {2}version:\s*"?([^"\s]+)"?\s*$/);
      if (m && m[1] !== '0.0.0-use.local') {
        for (const name of currentNames) addVersion(map, name, m[1]);
      }
    }
  }
  return map;
}

export function parsePackageLock(content: string): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  const lock = JSON.parse(content) as {
    lockfileVersion?: number;
    packages?: Record<string, { version?: string; link?: boolean }>;
    dependencies?: Record<string, unknown>;
  };
  if (lock.packages) {
    for (const [key, info] of Object.entries(lock.packages)) {
      if (key === '' || !info?.version || info.link) continue;
      const idx = key.lastIndexOf('node_modules/');
      if (idx === -1) continue; // workspace entries
      addVersion(map, key.slice(idx + 'node_modules/'.length), info.version);
    }
  } else if (lock.dependencies) {
    // lockfileVersion 1
    const walk = (deps: Record<string, unknown>) => {
      for (const [name, infoRaw] of Object.entries(deps)) {
        const info = infoRaw as { version?: string; dependencies?: Record<string, unknown> };
        if (info?.version) addVersion(map, name, info.version);
        if (info?.dependencies) walk(info.dependencies);
      }
    };
    walk(lock.dependencies);
  }
  return map;
}

export function parseLock(content: string, format: LockFormat): Map<string, Set<string>> {
  switch (format) {
    case 'yarn':
      return parseYarnV1(content);
    case 'yarn-berry':
      return parseYarnBerry(content);
    case 'npm':
      return parsePackageLock(content);
    default:
      throw new Error(`cannot parse lock format ${format}`);
  }
}

// --------------------------------------------------------------------------
// package.json helpers
// --------------------------------------------------------------------------

const DEP_SECTIONS = ['dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'] as const;

export function directDepNames(pkgJson: string | null): Set<string> {
  return new Set(directDepRanges(pkgJson).keys());
}

/** Range map (name -> range) across all dependency sections; later sections do not override. */
function directDepRanges(pkgJson: string | null): Map<string, string> {
  const ranges = new Map<string, string>();
  if (!pkgJson) return ranges;
  const pkg = JSON.parse(pkgJson) as Record<string, Record<string, string> | undefined>;
  for (const section of DEP_SECTIONS) {
    for (const [name, range] of Object.entries(pkg[section] ?? {})) {
      if (!ranges.has(name)) ranges.set(name, range);
    }
  }
  return ranges;
}

// --------------------------------------------------------------------------
// Diffing
// --------------------------------------------------------------------------

/**
 * Compatibility line. Releases on one line can move together; a second line
 * is a separate bump. For 0.x the minor is the breaking boundary.
 */
function lineKey(version: string): string {
  const parsed = parseVersion(version);
  if (!parsed) return `raw:${version}`;
  if (parsed.major === 0) return `0.${parsed.minor}`;
  return String(parsed.major);
}

function sortedVersions(versions: Iterable<string>): string[] {
  return [...versions].sort((a, b) => compareVersionOrder(a, b));
}

/** Prefer a short upgrade over an equal-distance downgrade. */
function pairDistance(from: string, to: string): number {
  const a = parseVersion(from);
  const b = parseVersion(to);
  if (!a || !b) return Number.MAX_SAFE_INTEGER / 4;
  const gap =
    Math.abs(b.major - a.major) * 1_000_000 + Math.abs(b.minor - a.minor) * 1_000 + Math.abs(b.patch - a.patch);
  const cmp = compareVersions(from, to);
  return (cmp !== null && cmp > 0 ? 500_000_000 : 0) + gap;
}

function closest(from: string, versions: string[]): string {
  return sortedVersions(versions).sort((a, b) => {
    const d = pairDistance(from, a) - pairDistance(from, b);
    return d !== 0 ? d : compareVersionOrder(a, b);
  })[0];
}

interface Pairing {
  updates: Array<[string, string]>;
  removed: string[];
  added: string[];
}

/** Pair versions that already share a compatibility line, or a line that moved. */
function matchVersions(oldVersions: string[], newVersions: string[]): Pairing {
  const olds = sortedVersions(oldVersions);
  const news = sortedVersions(newVersions);
  if (olds.length === 0) return { updates: [], removed: [], added: news };
  if (news.length === 0) return { updates: [], removed: olds, added: [] };
  // Several copies deduped onto one version are several bumps, not one.
  if (news.length === 1) return { updates: olds.map((from) => [from, news[0]]), removed: [], added: [] };
  if (olds.length === 1) {
    const target = closest(olds[0], news);
    return { updates: [[olds[0], target]], removed: [], added: news.filter((v) => v !== target) };
  }
  const candidates = olds.flatMap((from) => news.map((to) => ({ from, to, dist: pairDistance(from, to) })));
  candidates.sort(
    (a, b) => a.dist - b.dist || compareVersionOrder(a.from, b.from) || compareVersionOrder(a.to, b.to),
  );
  const usedFrom = new Set<string>();
  const usedTo = new Set<string>();
  const updates: Array<[string, string]> = [];
  for (const c of candidates) {
    if (usedFrom.has(c.from) || usedTo.has(c.to)) continue;
    usedFrom.add(c.from);
    usedTo.add(c.to);
    updates.push([c.from, c.to]);
  }
  return {
    updates,
    removed: olds.filter((v) => !usedFrom.has(v)),
    added: news.filter((v) => !usedTo.has(v)),
  };
}

interface VersionLine {
  key: string;
  versions: string[];
}

function groupByLine(versions: string[]): Map<string, string[]> {
  const groups = new Map<string, string[]>();
  for (const version of versions) {
    const key = lineKey(version);
    const list = groups.get(key);
    if (list) list.push(version);
    else groups.set(key, [version]);
  }
  return groups;
}

/** A disappeared line and an appeared line are one major move when nothing closer explains them. */
function pairLines(removed: VersionLine[], added: VersionLine[]): Pairing {
  const candidates: Array<{ removed: VersionLine; added: VersionLine; dist: number }> = [];
  for (const oldLine of removed) {
    for (const newLine of added) {
      const from = maxVersion(oldLine.versions);
      const to = maxVersion(newLine.versions);
      candidates.push({
        removed: oldLine,
        added: newLine,
        dist: from && to ? pairDistance(from, to) : Number.MAX_SAFE_INTEGER / 4,
      });
    }
  }
  candidates.sort(
    (a, b) => a.dist - b.dist || a.removed.key.localeCompare(b.removed.key) || a.added.key.localeCompare(b.added.key),
  );
  const usedOld = new Set<string>();
  const usedNew = new Set<string>();
  const updates: Array<[string, string]> = [];
  const extraRemoved: string[] = [];
  const extraAdded: string[] = [];
  for (const c of candidates) {
    if (usedOld.has(c.removed.key) || usedNew.has(c.added.key)) continue;
    usedOld.add(c.removed.key);
    usedNew.add(c.added.key);
    const paired = matchVersions(c.removed.versions, c.added.versions);
    updates.push(...paired.updates);
    extraRemoved.push(...paired.removed);
    extraAdded.push(...paired.added);
  }
  return {
    updates,
    removed: [
      ...extraRemoved,
      ...removed.filter((l) => !usedOld.has(l.key)).flatMap((l) => sortedVersions(l.versions)),
    ],
    added: [
      ...extraAdded,
      ...added.filter((l) => !usedNew.has(l.key)).flatMap((l) => sortedVersions(l.versions)),
    ],
  };
}

function diffPackageVersions(oldSet: Set<string> | undefined, newSet: Set<string> | undefined): Pairing {
  const oldVersions = oldSet ?? new Set<string>();
  const newVersions = newSet ?? new Set<string>();
  const oldLines = groupByLine([...oldVersions].filter((v) => !newVersions.has(v)));
  const newLines = groupByLine([...newVersions].filter((v) => !oldVersions.has(v)));
  const updates: Array<[string, string]> = [];
  const removed: string[] = [];
  const added: string[] = [];
  const removedLines: VersionLine[] = [];
  const addedLines: VersionLine[] = [];
  for (const key of new Set([...oldLines.keys(), ...newLines.keys()])) {
    const olds = oldLines.get(key) ?? [];
    const news = newLines.get(key) ?? [];
    if (olds.length > 0 && news.length > 0) {
      // Leftovers inside a line stay removed or added. They are not a major move.
      const paired = matchVersions(olds, news);
      updates.push(...paired.updates);
      removed.push(...paired.removed);
      added.push(...paired.added);
    } else if (olds.length > 0) {
      removedLines.push({ key, versions: olds });
    } else {
      addedLines.push({ key, versions: news });
    }
  }
  const crossed = pairLines(removedLines, addedLines);
  return {
    updates: [...updates, ...crossed.updates],
    removed: [...removed, ...crossed.removed],
    added: [...added, ...crossed.added],
  };
}

export function diffVersionMaps(
  oldMap: Map<string, Set<string>>,
  newMap: Map<string, Set<string>>,
  direct: Set<string>,
): Change[] {
  const changes: Change[] = [];
  for (const name of new Set([...oldMap.keys(), ...newMap.keys()])) {
    const paired = diffPackageVersions(oldMap.get(name), newMap.get(name));
    const isDirect = direct.has(name);
    for (const [from, to] of paired.updates) {
      changes.push({ name, from, to, kind: 'updated', direct: isDirect, delta: classifyDelta(from, to) });
    }
    for (const from of paired.removed) {
      changes.push({ name, from, to: null, kind: 'removed', direct: isDirect, delta: classifyDelta(null, null) });
    }
    for (const to of paired.added) {
      changes.push({ name, from: null, to, kind: 'added', direct: isDirect, delta: classifyDelta(null, null) });
    }
  }
  return sortChanges(changes);
}

/** Diff two package.json contents by declared ranges (used when no lockfile changed). */
export function diffManifests(oldPkg: string | null, newPkg: string | null): Change[] {
  const oldRanges = directDepRanges(oldPkg);
  const newRanges = directDepRanges(newPkg);
  const changes: Change[] = [];
  for (const name of new Set([...oldRanges.keys(), ...newRanges.keys()])) {
    const from = oldRanges.get(name) ?? null;
    const to = newRanges.get(name) ?? null;
    if (from === to) continue;
    // workspace:/file:/link: ranges point at the repo's own packages, not registry updates
    if (/^(workspace|file|link|portal):/.test(to ?? from ?? '')) continue;
    changes.push({
      name,
      from,
      to,
      kind: !from ? 'added' : !to ? 'removed' : 'updated',
      direct: true,
      delta: classifyDelta(concreteVersion(from), concreteVersion(to)),
    });
  }
  return sortChanges(changes);
}

function sortChanges(changes: Change[]): Change[] {
  return changes.sort(
    (a, b) =>
      Number(b.direct) - Number(a.direct) ||
      a.name.localeCompare(b.name) ||
      compareVersionOrder(a.from, b.from) ||
      compareVersionOrder(a.to, b.to),
  );
}

export function buildResult(format: LockFormat, changes: Change[]): CompareResult {
  const counts = { total: changes.length, direct: 0, added: 0, removed: 0, major: 0, minor: 0, patch: 0, other: 0 };
  for (const c of changes) {
    if (c.direct) counts.direct++;
    if (c.kind === 'added') counts.added++;
    else if (c.kind === 'removed') counts.removed++;
    else {
      const t = c.delta.effectiveType;
      if (t === 'major') counts.major++;
      else if (t === 'minor') counts.minor++;
      else if (t === 'patch') counts.patch++;
      else counts.other++;
    }
  }
  return { format, changes, counts };
}

/** Merge change lists from several files; lockfile-derived entries win over manifest-derived. */
export function mergeChanges(primary: Change[], secondary: Change[]): Change[] {
  const seen = new Set(primary.map((c) => c.name));
  return sortChanges([...primary, ...secondary.filter((c) => !seen.has(c.name))]);
}

// --------------------------------------------------------------------------
// CLI
// --------------------------------------------------------------------------

/** Compare in-memory contents (empty string / null = file absent on that side). */
export function compareContents(args: {
  oldLock?: string | null;
  newLock?: string | null;
  oldPkg?: string | null;
  newPkg?: string | null;
  format?: string;
}): CompareResult {
  const { oldPkg = null, newPkg = null } = args;

  if (args.oldLock || args.newLock) {
    const oldContent = args.oldLock ?? '';
    const newContent = args.newLock ?? '';
    const format =
      args.format && args.format !== 'auto'
        ? (args.format as LockFormat)
        : detectFormat(newContent || oldContent);
    const direct = new Set([...directDepNames(oldPkg), ...directDepNames(newPkg)]);
    const lockChanges = diffVersionMaps(
      oldContent ? parseLock(oldContent, format) : new Map(),
      newContent ? parseLock(newContent, format) : new Map(),
      direct,
    );
    // package.json may declare bumps the lockfile diff already covers; merge for completeness.
    const manifestChanges = oldPkg || newPkg ? diffManifests(oldPkg, newPkg) : [];
    return buildResult(format, mergeChanges(lockChanges, manifestChanges));
  }

  if (oldPkg || newPkg) {
    return buildResult('package-json', diffManifests(oldPkg, newPkg));
  }
  throw new Error('nothing to compare: pass --old-lock/--new-lock and/or --old-pkg/--new-pkg');
}

export function compareFiles(args: {
  oldLock?: string | null;
  newLock?: string | null;
  oldPkg?: string | null;
  newPkg?: string | null;
  format?: string;
}): CompareResult {
  return compareContents({
    oldLock: args.oldLock ? readInput(args.oldLock) : null,
    newLock: args.newLock ? readInput(args.newLock) : null,
    oldPkg: args.oldPkg ? readInput(args.oldPkg) : null,
    newPkg: args.newPkg ? readInput(args.newPkg) : null,
    format: args.format,
  });
}

const HELP = `Usage:
  compare-manifests.ts --old-lock <file|-> --new-lock <file|-> [--old-pkg <file>] [--new-pkg <file>] [--format auto|yarn|yarn-berry|npm]
  compare-manifests.ts --old-pkg <file> --new-pkg <file>

Compares old vs new lockfile (yarn v1, yarn berry, package-lock) and/or
package.json contents and prints the changed packages as JSON.`;

import { pathToFileURL } from 'node:url';

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv.includes('--help')) {
      console.log(HELP);
      process.exit(0);
    }
    const args = parseArgs(process.argv.slice(2), {
      'old-lock': 'value',
      'new-lock': 'value',
      'old-pkg': 'value',
      'new-pkg': 'value',
      format: 'value',
    });
    const result = compareFiles({
      oldLock: args['old-lock'] as string | undefined,
      newLock: args['new-lock'] as string | undefined,
      oldPkg: args['old-pkg'] as string | undefined,
      newPkg: args['new-pkg'] as string | undefined,
      format: args.format as string | undefined,
    });
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(`compare-manifests: ${(err as Error).message}`);
    process.exit(1);
  }
}
