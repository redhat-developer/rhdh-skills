// Support-level resolver. v1 reads the data file shipped with the skill
// (scripts/data/support-levels.yaml). The lookup goes through this module so a
// future version can fetch the data from a remote source (the file's `source`
// and `remoteUrl` fields are reserved for that), always falling back to the
// shipped file when the remote is unreachable.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseYaml } from './yaml.ts';
import { matchAny, matchPattern } from './match.ts';

export interface SupportData {
  source: string;
  ecosystemScopes: string[];
  levels: Record<string, string>;
  scoreAdjust: Record<string, number>;
  dataFile: string;
}

export interface SupportLevel {
  /** production | tech-preview | dev-preview | unknown, or null when the package
   *  is outside the configured ecosystem scopes (no support concept applies). */
  level: string | null;
  /** Score adjustment for score.ts (0 for out-of-scope packages). */
  scoreAdjust: number;
}

const DEFAULT_DATA_FILE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  'data',
  'support-levels.yaml',
);

export function loadSupportData(dataFile: string = DEFAULT_DATA_FILE): SupportData {
  const raw = parseYaml(fs.readFileSync(dataFile, 'utf8')) as Record<string, unknown>;
  if (!raw || typeof raw !== 'object') {
    throw new Error(`${dataFile}: support-level data must be a YAML object`);
  }
  return {
    source: typeof raw.source === 'string' ? raw.source : 'file',
    ecosystemScopes: (raw.ecosystemScopes as string[]) ?? [],
    levels: (raw.levels as Record<string, string>) ?? {},
    scoreAdjust: (raw.scoreAdjust as Record<string, number>) ?? { unknown: 1 },
    dataFile,
  };
}

export function resolveSupportLevel(name: string, data: SupportData): SupportLevel {
  if (!matchAny(name, data.ecosystemScopes)) {
    return { level: null, scoreAdjust: 0 };
  }
  // Exact entries win over glob entries; among globs, the longest pattern wins.
  let best: { pattern: string; level: string } | null = null;
  for (const [pattern, level] of Object.entries(data.levels)) {
    if (!matchPattern(name, pattern)) continue;
    if (pattern === name) {
      best = { pattern, level };
      break;
    }
    if (!best || pattern.length > best.pattern.length) best = { pattern, level };
  }
  const level = best?.level ?? 'unknown';
  return { level, scoreAdjust: data.scoreAdjust[level] ?? 0 };
}
