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
 * Resolve a GitHub PAT for Dependabot REST calls.
 *
 * Sources (first wins):
 * 1. process.env.GITHUB_TOKEN / GH_TOKEN (already exported)
 * 2. `.env` file walking up from cwd (does not override existing env)
 *
 * Never uses: --token CLI, gh CLI, or git credential helpers.
 */

import { existsSync, readFileSync } from 'fs';
import { dirname, resolve as resolvePath } from 'path';

const TOKEN_KEYS = ['GITHUB_TOKEN', 'GH_TOKEN'];

/**
 * Parse simple KEY=VALUE lines from a .env file into an object.
 * Ignores comments and blank lines. Strips optional surrounding quotes.
 * @param {string} text
 * @returns {Record<string, string>}
 */
function parseEnvFile(text) {
  const out = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }
    const eq = line.indexOf('=');
    if (eq <= 0) {
      continue;
    }
    const key = line.slice(0, eq).trim().replace(/^export\s+/, '');
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key) {
      out[key] = value;
    }
  }
  return out;
}

/**
 * If GITHUB_TOKEN / GH_TOKEN are unset, load them from the nearest `.env`
 * walking up from cwd (max 8 parents). Never overwrites existing env vars.
 */
export function loadTokenFromDotEnv() {
  if (process.env.GITHUB_TOKEN || process.env.GH_TOKEN) {
    return;
  }

  let dir = process.cwd();
  for (let i = 0; i < 8; i += 1) {
    const envPath = resolvePath(dir, '.env');
    if (existsSync(envPath)) {
      let parsed = {};
      try {
        parsed = parseEnvFile(readFileSync(envPath, 'utf8'));
      } catch {
        return;
      }
      for (const key of TOKEN_KEYS) {
        if (!process.env[key] && parsed[key]) {
          process.env[key] = parsed[key];
        }
      }
      return;
    }
    const parent = dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
}

/**
 * @param {{ requiredFor?: string }} [opts]
 * @returns {string}
 */
export function resolveGithubToken(opts = {}) {
  loadTokenFromDotEnv();

  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  if (!token) {
    const purpose = opts.requiredFor ? ` (${opts.requiredFor})` : '';
    throw new Error(
      `GitHub PAT required${purpose}. Set GITHUB_TOKEN or GH_TOKEN in the ` +
        'environment or a .env file (walked from cwd). Do not use --token, ' +
        'the gh CLI, or git credential helpers — these scripts call ' +
        'api.github.com via REST.',
    );
  }
  return token;
}
