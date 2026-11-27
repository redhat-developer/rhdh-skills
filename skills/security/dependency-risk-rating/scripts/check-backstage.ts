#!/usr/bin/env node
// Check changed @backstage/* packages against the official release manifest for
// the Backstage version pinned in the target repo's backstage.json.
//
//   check-backstage.ts --changes <file|-> [--backstage-json <path|url>]
//                      [--repo <owner/name> --ref <ref>] [--release <version>]
//
// The release manifest is fetched from versions.backstage.io, falling back to
// its GitHub mirror (backstage/versions) through the Contents API when that
// host is unreachable — which is the normal path inside a sandboxed runner
// that allowlists egress by hostname.
//
// Output (JSON): { release, manifestSource, results: [{name, to, expected, status}], notes }
// or { skipped: true, reason } when the repo pins no Backstage version.

import * as fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import type { Change } from './compare-manifests.ts';
import { concreteVersion } from './lib/semver.ts';
import { parseArgs, readJsonInput } from './lib/cli.ts';
import { fetchJson } from './lib/http.ts';
import { contentsUrl, fetchGithubRaw, githubToken } from './lib/github-raw.ts';

interface Manifest {
  releaseVersion?: string;
  packages?: Array<{ name: string; version: string }>;
}

async function resolveRelease(args: {
  release?: string;
  backstageJson?: string;
  repo?: string;
  ref?: string;
}, notes: string[]): Promise<string | null> {
  if (args.release) return args.release;

  let content: string | null = null;
  if (args.backstageJson?.startsWith('http')) {
    const res = await fetchJson<{ version?: string }>(args.backstageJson);
    if (!res.ok) throw new Error(`failed to fetch ${args.backstageJson}: ${res.error}`);
    return res.data?.version ?? null;
  }
  if (args.backstageJson) {
    if (!fs.existsSync(args.backstageJson)) return null;
    content = fs.readFileSync(args.backstageJson, 'utf8');
  } else if (args.repo) {
    const res = await fetchGithubRaw(args.repo, args.ref ?? 'HEAD', 'backstage.json');
    if (res.anonymousFallback) notes.push('gh credential rejected for this repo; fetched backstage.json anonymously');
    content = res.content;
  } else if (fs.existsSync('backstage.json')) {
    content = fs.readFileSync('backstage.json', 'utf8');
  }
  if (content === null) return null;
  return (JSON.parse(content) as { version?: string }).version ?? null;
}

async function fetchManifest(release: string, notes: string[]): Promise<{ manifest: Manifest; source: string }> {
  const manifestPath = `v1/releases/${release}/manifest.json`;
  const primary = `https://versions.backstage.io/${manifestPath}`;
  // One attempt, short timeout. A sandboxed runner that allowlists egress by
  // hostname blocks this host, and the mirror below serves the same bytes, so
  // spending the default retry budget here only delays a fetch that will work.
  const res = await fetchJson<Manifest>(primary, { retries: 0, timeoutMs: 5_000 });
  if (res.ok && res.data?.packages) return { manifest: res.data, source: primary };

  // The mirror goes through the Contents API, not raw.githubusercontent.com,
  // so it stays reachable wherever api.github.com is allowlisted.
  const mirror = contentsUrl('backstage/versions', 'main', manifestPath);
  const token = githubToken();
  const fallback = await fetchJson<Manifest>(mirror, {
    headers: {
      accept: 'application/vnd.github.raw',
      'x-github-api-version': '2022-11-28',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
  });
  if (fallback.ok && fallback.data?.packages) {
    notes.push(`versions.backstage.io unreachable (${res.error}); used the backstage/versions mirror`);
    return { manifest: fallback.data, source: mirror };
  }
  throw new Error(`could not fetch the Backstage ${release} release manifest: ${fallback.error ?? res.error}`);
}

export async function checkBackstage(args: {
  changes: { changes: Change[] };
  release?: string;
  backstageJson?: string;
  repo?: string;
  ref?: string;
}): Promise<Record<string, unknown>> {
  const notes: string[] = [];
  const backstageChanges = args.changes.changes.filter(
    (c) => c.name.startsWith('@backstage/') && c.kind !== 'removed',
  );
  if (backstageChanges.length === 0) {
    return { skipped: true, reason: 'no @backstage/* packages in the change set' };
  }
  const release = await resolveRelease(args, notes);
  if (!release) {
    return { skipped: true, reason: 'no backstage.json found (repo does not pin a Backstage release)' };
  }
  const { manifest, source } = await fetchManifest(release, notes);
  const expected = new Map((manifest.packages ?? []).map((p) => [p.name, p.version]));

  const results = backstageChanges.map((c) => {
    const to = concreteVersion(c.to);
    const want = expected.get(c.name) ?? null;
    return {
      name: c.name,
      to: c.to,
      expected: want,
      status: !want ? 'not-in-manifest' : to === want ? 'match' : 'mismatch',
    };
  });
  return {
    release,
    manifestSource: source,
    counts: {
      match: results.filter((r) => r.status === 'match').length,
      mismatch: results.filter((r) => r.status === 'mismatch').length,
      notInManifest: results.filter((r) => r.status === 'not-in-manifest').length,
    },
    results,
    notes,
  };
}

const HELP = `Usage:
  check-backstage.ts --changes <file|-> [--backstage-json <path|url>] [--repo <owner/name> --ref <ref>] [--release <version>]

Compares changed @backstage/* package versions against the official release
manifest for the Backstage version pinned in backstage.json.`;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv.includes('--help')) {
      console.log(HELP);
      process.exit(0);
    }
    const args = parseArgs(process.argv.slice(2), {
      changes: 'value',
      'backstage-json': 'value',
      repo: 'value',
      ref: 'value',
      release: 'value',
    });
    if (!args.changes) throw new Error('--changes is required');
    const result = await checkBackstage({
      changes: readJsonInput(args.changes as string),
      release: args.release as string | undefined,
      backstageJson: args['backstage-json'] as string | undefined,
      repo: args.repo as string | undefined,
      ref: args.ref as string | undefined,
    });
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(`check-backstage: ${(err as Error).message}`);
    process.exit(1);
  }
}
