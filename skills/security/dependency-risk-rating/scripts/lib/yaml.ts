// Minimal YAML-subset parser + .dependency-risk config loader. Zero dependencies.
//
// Supported syntax (enough for .dependency-risk.yaml and support-levels.yaml):
//   - nested maps via indentation, keys optionally single/double quoted
//   - lists of scalars ("- item") and lists of maps ("- key: value" + siblings)
//   - inline flow collections: { a: 1, b: c } and [a, "b", 2]
//   - scalars: strings (quoted/unquoted), int/float, true/false, null/~
//   - full-line and trailing comments (#)
// NOT supported (use .dependency-risk.json instead): anchors/aliases, multiline
// block scalars (| and >), multi-document files, complex keys.

import * as fs from 'node:fs';
import * as path from 'node:path';

interface Line {
  indent: number;
  text: string;
  no: number;
}

export function parseYaml(source: string): unknown {
  const lines: Line[] = [];
  source.split(/\r?\n/).forEach((raw, i) => {
    const noComment = stripComment(raw);
    if (noComment.trim() === '') return;
    if (/\t/.test(noComment.match(/^\s*/)![0])) {
      throw new YamlError(`tabs are not allowed in indentation`, i + 1);
    }
    lines.push({ indent: noComment.match(/^ */)![0].length, text: noComment.trim(), no: i + 1 });
  });
  if (lines.length === 0) return null;
  const [value, next] = parseBlock(lines, 0, lines[0].indent);
  if (next !== lines.length) {
    throw new YamlError(`unexpected content`, lines[next].no);
  }
  return value;
}

export class YamlError extends Error {
  constructor(message: string, line: number) {
    super(`YAML parse error on line ${line}: ${message}`);
  }
}

function stripComment(raw: string): string {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (ch === "'" && !inDouble) inSingle = !inSingle;
    else if (ch === '"' && !inSingle) inDouble = !inDouble;
    else if (ch === '#' && !inSingle && !inDouble && (i === 0 || raw[i - 1] === ' ')) {
      return raw.slice(0, i);
    }
  }
  return raw;
}

function parseBlock(lines: Line[], start: number, indent: number): [unknown, number] {
  if (lines[start].text.startsWith('- ') || lines[start].text === '-') {
    return parseList(lines, start, indent);
  }
  return parseMap(lines, start, indent);
}

function parseList(lines: Line[], start: number, indent: number): [unknown[], number] {
  const out: unknown[] = [];
  let i = start;
  while (i < lines.length && lines[i].indent === indent && (lines[i].text.startsWith('- ') || lines[i].text === '-')) {
    const rest = lines[i].text === '-' ? '' : lines[i].text.slice(2).trim();
    if (rest === '') {
      // nested block belongs to this item
      if (i + 1 < lines.length && lines[i + 1].indent > indent) {
        const [value, next] = parseBlock(lines, i + 1, lines[i + 1].indent);
        out.push(value);
        i = next;
      } else {
        out.push(null);
        i++;
      }
    } else if (isMapEntry(rest)) {
      // "- key: value" — a map whose first entry is on the dash line.
      // Treat following lines indented past the dash as more entries of the same map.
      const virtualIndent = indent + 2;
      const item: Record<string, unknown> = {};
      let next = addMapEntry(item, rest, lines, i + 1, virtualIndent, lines[i].no);
      while (next < lines.length && lines[next].indent === virtualIndent && !lines[next].text.startsWith('- ') && isMapEntry(lines[next].text)) {
        next = addMapEntry(item, lines[next].text, lines, next + 1, virtualIndent, lines[next].no);
      }
      out.push(item);
      i = next;
    } else {
      out.push(parseScalar(rest, lines[i].no));
      i++;
    }
  }
  return [out, i];
}

function parseMap(lines: Line[], start: number, indent: number): [Record<string, unknown>, number] {
  const out: Record<string, unknown> = {};
  let i = start;
  while (i < lines.length && lines[i].indent === indent && !lines[i].text.startsWith('- ')) {
    if (!isMapEntry(lines[i].text)) {
      throw new YamlError(`expected "key: value"`, lines[i].no);
    }
    i = addMapEntry(out, lines[i].text, lines, i + 1, indent, lines[i].no);
  }
  return [out, i];
}

/** Parse one "key: value" entry (value possibly a nested block); returns next line index. */
function addMapEntry(
  target: Record<string, unknown>,
  entry: string,
  lines: Line[],
  next: number,
  indent: number,
  lineNo: number,
): number {
  const { key, rest } = splitKey(entry, lineNo);
  if (rest !== '') {
    target[key] = parseScalar(rest, lineNo);
    return next;
  }
  if (next < lines.length && lines[next].indent > indent) {
    const [value, after] = parseBlock(lines, next, lines[next].indent);
    target[key] = value;
    return after;
  }
  target[key] = null;
  return next;
}

function isMapEntry(text: string): boolean {
  try {
    splitKey(text, 0);
    return true;
  } catch {
    return false;
  }
}

function splitKey(text: string, lineNo: number): { key: string; rest: string } {
  let key: string;
  let after: number;
  if (text[0] === '"' || text[0] === "'") {
    const quote = text[0];
    const end = text.indexOf(quote, 1);
    if (end === -1) throw new YamlError('unterminated quoted key', lineNo);
    key = text.slice(1, end);
    after = end + 1;
  } else {
    // unquoted key: up to the first ": " or a colon at end of line
    const m = text.match(/^([^:]+?):(?: |$)/);
    if (!m) throw new YamlError('missing ":" after key', lineNo);
    key = m[1].trim();
    after = m[0].length - (m[0].endsWith(' ') ? 1 : 0);
  }
  const colon = text.slice(after).match(/^\s*:/);
  if (text[0] === '"' || text[0] === "'") {
    if (!colon) throw new YamlError('missing ":" after key', lineNo);
    after += colon[0].length;
  }
  return { key, rest: text.slice(after).trim() };
}

function parseScalar(text: string, lineNo: number): unknown {
  if (text === '' || text === '~' || text === 'null') return null;
  if (text === 'true') return true;
  if (text === 'false') return false;
  if (text[0] === '{') return parseFlow(text, lineNo);
  if (text[0] === '[') return parseFlow(text, lineNo);
  if (text[0] === '"' || text[0] === "'") {
    const quote = text[0];
    if (text[text.length - 1] !== quote || text.length < 2) {
      throw new YamlError('unterminated quoted string', lineNo);
    }
    const body = text.slice(1, -1);
    return quote === '"' ? body.replace(/\\(["\\/nrt])/g, (_, c) => ({ n: '\n', r: '\r', t: '\t' } as Record<string, string>)[c] ?? c) : body;
  }
  if (/^[+-]?\d+$/.test(text)) return Number(text);
  if (/^[+-]?\d*\.\d+$/.test(text)) return Number(text);
  return text;
}

/** Tiny recursive parser for inline { } and [ ] flow collections. */
function parseFlow(text: string, lineNo: number): unknown {
  let pos = 0;
  const fail = (msg: string): never => {
    throw new YamlError(`${msg} in flow collection "${text}"`, lineNo);
  };
  const skipWs = () => {
    while (pos < text.length && text[pos] === ' ') pos++;
  };
  const parseValue = (): unknown => {
    skipWs();
    const ch = text[pos];
    if (ch === '{') {
      pos++;
      const obj: Record<string, unknown> = {};
      skipWs();
      if (text[pos] === '}') { pos++; return obj; }
      for (;;) {
        skipWs();
        const key = String(parseToken(':'));
        skipWs();
        if (text[pos] !== ':') fail('expected ":"');
        pos++;
        obj[key] = parseValue();
        skipWs();
        if (text[pos] === ',') { pos++; continue; }
        if (text[pos] === '}') { pos++; return obj; }
        fail('expected "," or "}"');
      }
    }
    if (ch === '[') {
      pos++;
      const arr: unknown[] = [];
      skipWs();
      if (text[pos] === ']') { pos++; return arr; }
      for (;;) {
        arr.push(parseValue());
        skipWs();
        if (text[pos] === ',') { pos++; continue; }
        if (text[pos] === ']') { pos++; return arr; }
        fail('expected "," or "]"');
      }
    }
    return parseToken(',');
  };
  const parseToken = (extraStop: string): unknown => {
    skipWs();
    if (text[pos] === '"' || text[pos] === "'") {
      const quote = text[pos];
      const end = text.indexOf(quote, pos + 1);
      if (end === -1) fail('unterminated quoted string');
      const body = text.slice(pos + 1, end);
      pos = end + 1;
      return body;
    }
    let end = pos;
    while (end < text.length && !`,}]${extraStop}`.includes(text[end])) end++;
    const token = text.slice(pos, end).trim();
    pos = end;
    return parseScalar(token, lineNo);
  };
  const result = parseValue();
  skipWs();
  if (pos !== text.length) fail('trailing content');
  return result;
}

// ---------------------------------------------------------------------------
// .dependency-risk config loading
// ---------------------------------------------------------------------------

export interface RiskConfig {
  version: number;
  trustedPackages: string[];
  trustedOverridesSecurity: boolean;
  minAgeDays: number;
  manyPackagesThreshold: number;
  maxPackagesDetailed: number;
  bands: { medium: number; high: number };
  weights: Record<string, number>;
  backstage: { enabled: boolean };
  codecov: {
    service: string;
    owner: string;
    tokenEnv: string;
    repos: Record<string, string>;
  } | null;
  testConfidence: Record<string, string>;
  /** Where the config came from, for reporting. */
  configSource: string;
}

export const CONFIG_DEFAULTS: Omit<RiskConfig, 'configSource'> = {
  version: 1,
  trustedPackages: ['@red-hat-developer-hub/*'],
  trustedOverridesSecurity: true,
  minAgeDays: 3,
  manyPackagesThreshold: 100,
  maxPackagesDetailed: 20,
  bands: { medium: 3, high: 6 },
  weights: {},
  backstage: { enabled: true },
  codecov: null,
  testConfidence: {},
};

/**
 * Load .dependency-risk.yaml / .dependency-risk.json from a repo root (or an
 * explicit file path), merged over CONFIG_DEFAULTS. Missing file -> defaults.
 * The sentinel "none" forces pure defaults — use it when rating a remote repo
 * that has no config, so the local checkout's config cannot leak in.
 */
export function loadConfig(repoRootOrFile: string | null | undefined): RiskConfig {
  if (repoRootOrFile === 'none') {
    return { ...structuredClone(CONFIG_DEFAULTS), configSource: 'defaults (--config none)' };
  }
  let file: string | null = null;
  if (repoRootOrFile) {
    const stat = fs.existsSync(repoRootOrFile) ? fs.statSync(repoRootOrFile) : null;
    if (stat?.isFile()) {
      file = repoRootOrFile;
    } else if (stat?.isDirectory()) {
      for (const name of ['.dependency-risk.yaml', '.dependency-risk.yml', '.dependency-risk.json']) {
        const candidate = path.join(repoRootOrFile, name);
        if (fs.existsSync(candidate)) {
          file = candidate;
          break;
        }
      }
    }
  }
  if (!file) return { ...structuredClone(CONFIG_DEFAULTS), configSource: 'defaults (no config file found)' };

  const text = fs.readFileSync(file, 'utf8');
  const raw = file.endsWith('.json') ? JSON.parse(text) : parseYaml(text);
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error(`${file}: config must be a YAML/JSON object`);
  }
  const cfg = mergeConfig(structuredClone(CONFIG_DEFAULTS), raw as Record<string, unknown>, file);
  return { ...cfg, configSource: file };
}

function mergeConfig(
  base: Omit<RiskConfig, 'configSource'>,
  raw: Record<string, unknown>,
  file: string,
): Omit<RiskConfig, 'configSource'> {
  const expect = (cond: boolean, key: string, type: string) => {
    if (!cond) throw new Error(`${file}: "${key}" must be ${type}`);
  };
  for (const [key, value] of Object.entries(raw)) {
    if (value === null || value === undefined) continue;
    switch (key) {
      case 'version':
        expect(typeof value === 'number', key, 'a number');
        base.version = value as number;
        break;
      case 'trustedPackages':
        expect(Array.isArray(value) && (value as unknown[]).every((v) => typeof v === 'string'), key, 'a list of strings');
        base.trustedPackages = value as string[];
        break;
      case 'trustedOverridesSecurity':
        expect(typeof value === 'boolean', key, 'a boolean');
        base.trustedOverridesSecurity = value as boolean;
        break;
      case 'minAgeDays':
      case 'manyPackagesThreshold':
      case 'maxPackagesDetailed':
        expect(typeof value === 'number', key, 'a number');
        (base as unknown as Record<string, unknown>)[key] = value;
        break;
      case 'bands': {
        expect(typeof value === 'object' && !Array.isArray(value), key, 'a map');
        const bands = value as Record<string, unknown>;
        for (const k of ['medium', 'high']) {
          if (bands[k] !== undefined) {
            expect(typeof bands[k] === 'number', `bands.${k}`, 'a number');
            (base.bands as Record<string, number>)[k] = bands[k] as number;
          }
        }
        break;
      }
      case 'weights':
        expect(typeof value === 'object' && !Array.isArray(value), key, 'a map');
        for (const [wk, wv] of Object.entries(value as Record<string, unknown>)) {
          expect(typeof wv === 'number', `weights.${wk}`, 'a number');
          base.weights[wk] = wv as number;
        }
        break;
      case 'backstage':
        expect(typeof value === 'object' && !Array.isArray(value), key, 'a map');
        if ((value as Record<string, unknown>).enabled !== undefined) {
          expect(typeof (value as Record<string, unknown>).enabled === 'boolean', 'backstage.enabled', 'a boolean');
          base.backstage.enabled = (value as Record<string, unknown>).enabled as boolean;
        }
        break;
      case 'codecov': {
        expect(typeof value === 'object' && !Array.isArray(value), key, 'a map');
        const c = value as Record<string, unknown>;
        base.codecov = {
          service: typeof c.service === 'string' ? c.service : 'github',
          owner: String(c.owner ?? ''),
          tokenEnv: typeof c.tokenEnv === 'string' ? c.tokenEnv : 'CODECOV_TOKEN',
          repos: (typeof c.repos === 'object' && c.repos ? c.repos : {}) as Record<string, string>,
        };
        break;
      }
      case 'testConfidence':
        expect(typeof value === 'object' && !Array.isArray(value), key, 'a map');
        base.testConfidence = value as Record<string, string>;
        break;
      default:
        throw new Error(`${file}: unknown config key "${key}" (see references/config.md)`);
    }
  }
  return base;
}
