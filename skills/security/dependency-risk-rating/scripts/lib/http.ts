// Shared HTTP helpers: fetch with timeout + retries, and a concurrency limiter.
// Uses Node's built-in fetch. In proxied environments where direct egress is
// blocked, run scripts with NODE_USE_ENV_PROXY=1 (Node >= 22.15) so fetch
// honors HTTPS_PROXY, and NODE_EXTRA_CA_CERTS for a custom proxy CA.

const USER_AGENT = 'dependency-risk-rating-skill (+https://github.com/redhat-developer/rhdh-skills)';

export interface HttpResult<T> {
  ok: boolean;
  status: number | null;
  data: T | null;
  /** Short human-readable error, set when ok is false. */
  error: string | null;
}

export interface FetchOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  timeoutMs?: number;
  retries?: number;
  /** Statuses that should NOT be retried and NOT be treated as failures (e.g. 404). */
  okStatuses?: number[];
}

async function fetchRaw(url: string, opts: FetchOptions): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? 10_000);
  try {
    return await fetch(url, {
      method: opts.method ?? 'GET',
      headers: { 'user-agent': USER_AGENT, ...opts.headers },
      body: opts.body,
      signal: controller.signal,
      redirect: 'follow',
    });
  } finally {
    clearTimeout(timer);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Fetch with retries on network errors and 5xx/429 responses.
 * Never throws: failures are reported in the result object.
 */
export async function fetchWithRetry(url: string, opts: FetchOptions = {}): Promise<HttpResult<Response>> {
  const retries = opts.retries ?? 2;
  let lastError = 'unknown error';
  let lastStatus: number | null = null;
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (attempt > 0) await sleep(500 * 3 ** (attempt - 1));
    try {
      const res = await fetchRaw(url, opts);
      lastStatus = res.status;
      if (res.ok || opts.okStatuses?.includes(res.status)) {
        return { ok: true, status: res.status, data: res, error: null };
      }
      lastError = `HTTP ${res.status}`;
      if (res.status < 500 && res.status !== 429) break; // 4xx: retrying won't help
    } catch (err) {
      const e = err as { cause?: { code?: string }; name?: string; message?: string };
      lastError = e.name === 'AbortError' ? 'timeout' : (e.cause?.code ?? e.message ?? String(err));
    }
  }
  return { ok: false, status: lastStatus, data: null, error: `${lastError} (${url})` };
}

export async function fetchJson<T = unknown>(url: string, opts: FetchOptions = {}): Promise<HttpResult<T>> {
  const res = await fetchWithRetry(url, opts);
  if (!res.ok || !res.data) return { ok: false, status: res.status, data: null, error: res.error };
  try {
    return { ok: true, status: res.status, data: (await res.data.json()) as T, error: null };
  } catch {
    return { ok: false, status: res.status, data: null, error: `invalid JSON (${url})` };
  }
}

export async function fetchText(url: string, opts: FetchOptions = {}): Promise<HttpResult<string>> {
  const res = await fetchWithRetry(url, opts);
  if (!res.ok || !res.data) return { ok: false, status: res.status, data: null, error: res.error };
  return { ok: true, status: res.status, data: await res.data.text(), error: null };
}

/** Simple promise concurrency limiter: const limit = pLimit(8); limit(() => ...). */
export function pLimit(concurrency: number): <T>(fn: () => Promise<T>) => Promise<T> {
  let active = 0;
  const queue: Array<() => void> = [];
  const next = () => {
    active--;
    queue.shift()?.();
  };
  return <T>(fn: () => Promise<T>): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const run = () => {
        active++;
        fn().then(resolve, reject).finally(next);
      };
      if (active < concurrency) run();
      else queue.push(run);
    });
}
