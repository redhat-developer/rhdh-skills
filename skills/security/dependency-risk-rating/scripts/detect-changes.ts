#!/usr/bin/env node
// Mode-aware orchestrator: produce the changed-packages list for one of three inputs.
//
//   detect-changes.ts --git [--base <ref>] [--repo-root <dir>]
//       Diff manifest files between a git base and the working tree.
//       Default base: HEAD if manifest files have uncommitted changes, otherwise
//       the merge-base with the default branch.
//
//   detect-changes.ts --package <name> --from <version> --to <version>
//       Single named package update.
//
//   detect-changes.ts --github <owner/repo> --base-ref <sha> --head-ref <sha> --files <a,b,c>
//       Diff files between two refs, fetched through the GitHub Contents API
//       (the gh CLI credential is used for private repos). The changed-file
//       list comes from the PR metadata (small payload, no lockfile content).
//
// Output (JSON): { mode, base?, sourceFiles, notes, format, changes, counts }

import * as fs from 'node:fs';
import * as path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import {
  buildResult,
  detectFormat,
  diffManifests,
  diffVersionMaps,
  directDepNames,
  mergeChanges,
  parseLock,
  type Change,
  type CompareResult,
} from './compare-manifests.ts';
import { parseArgs } from './lib/cli.ts';
import { classifyDelta } from './lib/semver.ts';
import { fetchGithubRaw, githubToken } from './lib/github-raw.ts';

const LOCK_BASENAMES = new Set(['yarn.lock', 'package-lock.json', 'npm-shrinkwrap.json']);
const UNSUPPORTED_LOCKS = new Set(['pnpm-lock.yaml', 'bun.lockb', 'bun.lock']);

export interface DetectResult extends CompareResult {
  mode: 'git' | 'package' | 'github';
  base?: string;
  sourceFiles: string[];
  notes: string[];
}

interface FileContents {
  /** null = file absent on that side */
  old: string | null;
  new: string | null;
}

type ContentProvider = (filePath: string) => Promise<FileContents>;

/**
 * Shared core: given the changed manifest paths and a way to load old/new
 * contents, produce the merged change list. Sibling package.jsons of changed
 * lockfiles are loaded too (even when unchanged) for direct-dep detection.
 */
async function diffManifestFiles(
  changedPaths: string[],
  load: ContentProvider,
  notes: string[],
): Promise<CompareResult> {
  const lockPaths = changedPaths.filter((p) => LOCK_BASENAMES.has(path.posix.basename(p)));
  const pkgPaths = changedPaths.filter((p) => path.posix.basename(p) === 'package.json');
  const unsupported = changedPaths.filter((p) => UNSUPPORTED_LOCKS.has(path.posix.basename(p)));
  for (const p of unsupported) notes.push(`unsupported lockfile format skipped: ${p}`);
  if (lockPaths.length === 0 && pkgPaths.length === 0) {
    // Include the unsupported files in the error: a thrown error discards notes.
    const hint = unsupported.length > 0 ? ` (unsupported lockfiles found: ${unsupported.join(', ')})` : '';
    throw new Error(`no supported manifest files (package.json, yarn.lock, package-lock.json) in the change set${hint}`);
  }

  // Load everything concurrently: changed package.jsons, changed lockfiles,
  // and each lockfile's sibling package.json (needed for direct-dep tagging).
  const siblingPaths = lockPaths
    .map((lockPath) => path.posix.join(path.posix.dirname(lockPath), 'package.json'))
    .filter((sibling) => !pkgPaths.includes(sibling));
  const allPkgPaths = [...pkgPaths, ...new Set(siblingPaths)];
  const [pkgLoaded, lockLoaded] = await Promise.all([
    Promise.all(allPkgPaths.map((p) => load(p))),
    Promise.all(lockPaths.map((p) => load(p))),
  ]);
  const pkgContents = new Map<string, FileContents>(allPkgPaths.map((p, i) => [p, pkgLoaded[i]]));
  const lockContents = new Map<string, FileContents>(lockPaths.map((p, i) => [p, lockLoaded[i]]));

  // Direct deps = union over every involved package.json (both sides).
  const directNames = new Set<string>();
  for (const { old, new: neu } of pkgContents.values()) {
    for (const n of directDepNames(old)) directNames.add(n);
    for (const n of directDepNames(neu)) directNames.add(n);
  }

  let format: CompareResult['format'] = 'package-json';
  let lockChanges: Change[] = [];
  for (const lockPath of lockPaths) {
    const { old, new: neu } = lockContents.get(lockPath)!;
    const fmt = detectFormat(neu || old || '');
    format = fmt;
    lockChanges = mergeChanges(
      lockChanges,
      diffVersionMaps(
        old ? parseLock(old, fmt) : new Map(),
        neu ? parseLock(neu, fmt) : new Map(),
        directNames,
      ),
    );
  }

  let manifestChanges: Change[] = [];
  for (const p of pkgPaths) {
    const { old, new: neu } = pkgContents.get(p)!;
    manifestChanges = mergeChanges(manifestChanges, diffManifests(old, neu));
  }

  return buildResult(format, mergeChanges(lockChanges, manifestChanges));
}

// --------------------------------------------------------------------------
// git mode
// --------------------------------------------------------------------------

function git(repoRoot: string, args: string[]): string {
  return execFileSync('git', ['-C', repoRoot, ...args], { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });
}

function gitShow(repoRoot: string, ref: string, filePath: string): string | null {
  try {
    return git(repoRoot, ['show', `${ref}:${filePath}`]);
  } catch {
    return null; // file does not exist at that ref
  }
}

function isManifestPath(p: string): boolean {
  const base = path.posix.basename(p);
  return base === 'package.json' || LOCK_BASENAMES.has(base) || UNSUPPORTED_LOCKS.has(base);
}

function defaultBase(repoRoot: string, notes: string[]): string {
  const dirty = git(repoRoot, ['diff', '--name-only', 'HEAD'])
    .split('\n')
    .filter((p) => p && isManifestPath(p));
  if (dirty.length > 0) {
    notes.push('uncommitted manifest changes found; comparing against HEAD');
    return 'HEAD';
  }
  for (const candidate of ['refs/remotes/origin/HEAD', 'origin/main', 'origin/master', 'main', 'master']) {
    try {
      const ref =
        candidate === 'refs/remotes/origin/HEAD'
          ? git(repoRoot, ['symbolic-ref', '--short', candidate]).trim()
          : candidate;
      git(repoRoot, ['rev-parse', '--verify', '--quiet', ref]);
      const mergeBase = git(repoRoot, ['merge-base', 'HEAD', ref]).trim();
      notes.push(`comparing against merge-base with ${ref} (${mergeBase.slice(0, 12)})`);
      return mergeBase;
    } catch {
      continue;
    }
  }
  notes.push('no default branch found; comparing against HEAD~1');
  return 'HEAD~1';
}

async function runGitMode(repoRoot: string, baseArg: string | undefined): Promise<DetectResult> {
  const notes: string[] = [];
  const base = baseArg ?? defaultBase(repoRoot, notes);
  const changed = git(repoRoot, ['diff', '--name-only', base])
    .split('\n')
    .filter((p) => p && isManifestPath(p));
  if (changed.length === 0) {
    throw new Error(`no changed manifest files between ${base} and the working tree`);
  }
  const load: ContentProvider = async (filePath) => {
    const abs = path.join(repoRoot, filePath);
    return {
      old: gitShow(repoRoot, base, filePath),
      new: fs.existsSync(abs) ? fs.readFileSync(abs, 'utf8') : null,
    };
  };
  const result = await diffManifestFiles(changed, load, notes);
  return { mode: 'git', base, sourceFiles: changed, notes, ...result };
}

// --------------------------------------------------------------------------
// github mode
// --------------------------------------------------------------------------

async function runGithubMode(
  repo: string,
  baseRef: string,
  headRef: string,
  files: string[],
): Promise<DetectResult> {
  if (!/^[^/]+\/[^/]+$/.test(repo)) throw new Error(`--github expects "owner/repo", got "${repo}"`);
  const notes: string[] = [];
  if (!githubToken()) notes.push('no gh credential available; only public repos are reachable');

  let anonymousFallbackUsed = false;
  const load: ContentProvider = async (filePath) => {
    const fetchAt = async (ref: string): Promise<string | null> => {
      const res = await fetchGithubRaw(repo, ref, filePath);
      anonymousFallbackUsed ||= res.anonymousFallback;
      return res.content;
    };
    const [old, neu] = await Promise.all([fetchAt(baseRef), fetchAt(headRef)]);
    return { old, new: neu };
  };

  const changed = files.filter(isManifestPath);
  const skipped = files.filter((f) => !isManifestPath(f));
  if (skipped.length > 0) notes.push(`non-manifest files ignored: ${skipped.join(', ')}`);
  const result = await diffManifestFiles(changed, load, notes);
  if (anonymousFallbackUsed) {
    notes.push('gh credential was rejected for this repo; fell back to anonymous fetches');
  }
  if (result.changes.length === 0) {
    notes.push('no package changes found — verify the refs and file paths are correct (a wrong ref reads as an absent file)');
  }
  return { mode: 'github', base: baseRef, sourceFiles: changed, notes, ...result };
}

// --------------------------------------------------------------------------
// package mode
// --------------------------------------------------------------------------

function runPackageMode(name: string, from: string, to: string): DetectResult {
  const change: Change = {
    name,
    from,
    to,
    kind: 'updated',
    direct: true,
    delta: classifyDelta(from, to),
  };
  return {
    mode: 'package',
    sourceFiles: [],
    notes: ['single-package mode: no repository context (direct/transitive and workspace checks unavailable)'],
    ...buildResult('package-json', [change]),
  };
}

// --------------------------------------------------------------------------
// CLI
// --------------------------------------------------------------------------

const HELP = `Usage:
  detect-changes.ts --git [--base <ref>] [--repo-root <dir>]
  detect-changes.ts --package <name> --from <version> --to <version>
  detect-changes.ts --github <owner/repo> --base-ref <sha> --head-ref <sha> --files <a,b,c>

Prints the changed npm packages as JSON (same schema as compare-manifests.ts,
plus mode/sourceFiles/notes). The gh CLI credential is used for private repos.`;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv.includes('--help')) {
      console.log(HELP);
      process.exit(0);
    }
    const args = parseArgs(process.argv.slice(2), {
      git: 'flag',
      base: 'value',
      'repo-root': 'value',
      package: 'value',
      from: 'value',
      to: 'value',
      github: 'value',
      'base-ref': 'value',
      'head-ref': 'value',
      files: 'value',
    });

    let result: DetectResult;
    if (args.git) {
      result = await runGitMode((args['repo-root'] as string) ?? process.cwd(), args.base as string | undefined);
    } else if (args.package) {
      if (!args.from || !args.to) throw new Error('--package requires --from and --to');
      result = runPackageMode(args.package as string, args.from as string, args.to as string);
    } else if (args.github) {
      if (!args['base-ref'] || !args['head-ref'] || !args.files) {
        throw new Error('--github requires --base-ref, --head-ref and --files');
      }
      result = await runGithubMode(
        args.github as string,
        args['base-ref'] as string,
        args['head-ref'] as string,
        (args.files as string).split(',').map((f) => f.trim()).filter(Boolean),
      );
    } else {
      throw new Error('pick a mode: --git, --package or --github (see --help)');
    }
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(`detect-changes: ${(err as Error).message}`);
    process.exit(1);
  }
}
