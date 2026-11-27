// Shared CLI plumbing: argument parsing and stdin-or-file input.

import * as fs from 'node:fs';

export function parseArgs(
  argv: string[],
  flags: Record<string, 'value' | 'flag'>,
): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) throw new Error(`unexpected argument: ${arg}`);
    const key = arg.slice(2);
    if (!(key in flags)) throw new Error(`unknown option: ${arg}`);
    if (flags[key] === 'flag') out[key] = true;
    else {
      const value = argv[++i];
      if (value === undefined) throw new Error(`missing value for ${arg}`);
      out[key] = value;
    }
  }
  return out;
}

/** Read a file, or stdin when the path is "-". */
export function readInput(pathOrDash: string): string {
  return pathOrDash === '-' ? fs.readFileSync(0, 'utf8') : fs.readFileSync(pathOrDash, 'utf8');
}

export function readJsonInput<T = unknown>(pathOrDash: string): T {
  return JSON.parse(readInput(pathOrDash)) as T;
}
