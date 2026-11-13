// Fetch file contents from the GitHub Contents API, authenticating private
// repos with the credential the gh CLI already holds. Some environments hold a
// token scoped to specific repos which yields 404 elsewhere, so a 404 with a
// token is retried anonymously before concluding the file is absent. The
// token's validity is learned once per repo and cached, so real 404s (absent
// files) don't pay a second request forever after.
//
// api.github.com rather than raw.githubusercontent.com: sandboxed agent runners
// allowlist egress by hostname, and api.github.com is reachable where the raw
// host is not. The `application/vnd.github.raw` media type returns the file
// bytes themselves, byte-identical to the raw host, and is NOT subject to the
// 1 MB cap that silently empties the JSON representation of a large lockfile.
// Sending that Accept header is therefore load-bearing, not cosmetic.
//
// The credential comes from `gh auth token` rather than GITHUB_TOKEN/GH_TOKEN
// in the environment: gh is the native store, so nothing here owns a secret, and
// the value stays in memory for the request header only. It is never passed as a
// process argument, logged, or written to output.

import { execFileSync } from 'node:child_process';
import { fetchText } from './http.ts';

/** Percent-encode each path segment while leaving the separators intact. */
function encodePath(filePath: string): string {
  return filePath.split('/').map(encodeURIComponent).join('/');
}

/** Contents-API URL for one file at one ref. */
export function contentsUrl(repo: string, ref: string, filePath: string): string {
  return `https://api.github.com/repos/${repo}/contents/${encodePath(filePath)}?ref=${encodeURIComponent(ref)}`;
}

/** Media type that returns the file bytes rather than a JSON envelope. */
const RAW_ACCEPT = {
  accept: 'application/vnd.github.raw',
  'x-github-api-version': '2022-11-28',
};

export interface RawFetchResult {
  /** File content, or null when the file does not exist at that ref. */
  content: string | null;
  /** True when the provided token was rejected and the anonymous retry succeeded. */
  anonymousFallback: boolean;
}

/** Resolved once: gh is either absent, unauthenticated, or good for the session. */
let cachedToken: string | null | undefined;

export function githubToken(): string | undefined {
  if (cachedToken === undefined) {
    try {
      const token = execFileSync('gh', ['auth', 'token'], {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
        timeout: 10_000,
      }).trim();
      cachedToken = token || null;
    } catch {
      // gh missing, not on PATH, or not logged in. Public repos still work.
      cachedToken = null;
    }
  }
  return cachedToken ?? undefined;
}

/** Per-repo knowledge about whether the provided token works there. */
const tokenState = new Map<string, 'valid' | 'rejected'>();

/** repo is "owner/name". Throws on network/auth errors, returns content null on 404. */
export async function fetchGithubRaw(repo: string, ref: string, filePath: string): Promise<RawFetchResult> {
  const url = contentsUrl(repo, ref, filePath);
  const token = githubToken();
  const useToken = Boolean(token) && tokenState.get(repo) !== 'rejected';
  const headers: Record<string, string> = useToken
    ? { ...RAW_ACCEPT, authorization: `Bearer ${token}` }
    : { ...RAW_ACCEPT };
  let res = await fetchText(url, { headers, okStatuses: [404], timeoutMs: 30_000 });
  let anonymousFallback = false;
  if (res.ok && useToken) {
    if (res.status !== 404) {
      tokenState.set(repo, 'valid');
    } else if (tokenState.get(repo) !== 'valid') {
      // First 404 with an unproven token: probe anonymously to distinguish
      // "file absent" from "token rejected for this repo".
      const anon = await fetchText(url, { headers: { ...RAW_ACCEPT }, okStatuses: [404], timeoutMs: 30_000 });
      if (anon.ok && anon.status !== 404) {
        tokenState.set(repo, 'rejected');
        res = anon;
        anonymousFallback = true;
      }
    }
  }
  if (!res.ok) throw new Error(`failed to fetch ${url}: ${res.error}`);
  return { content: res.status === 404 ? null : res.data, anonymousFallback };
}
