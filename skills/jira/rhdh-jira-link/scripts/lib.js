'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const MERGED_PREFIX = '[x] merged: ';
const CLOSED_PREFIX = '[!] closed: ';
const MOVEABLE_RHDHPLAN_TYPES = new Set(['Epic', 'Story', 'Task']);
const RHDHPLAN_PROJECT = 'RHDHPLAN';
const RHIDP_PROJECT = 'RHIDP';
const DEFAULT_JIRA_SERVER = 'https://redhat.atlassian.net';

const ADJUSTED_FIELD_LABELS = {
  storyPoints: 'Story points',
  team: 'Team',
  sprint: 'Sprint',
  assignee: 'Assignee',
  priority: 'Priority',
};

const REQUIRED_DEFAULT_KEYS = [
  'assigneeEmail',
  'teamId',
  'teamName',
  'boardId',
  'storyPoints',
  'priorityName',
  'storyPointsField',
  'teamField',
  'sprintField',
];

/** Keys only required when team/sprint defaults are enabled. */
const TEAM_SPRINT_DEFAULT_KEYS = [
  'teamId',
  'teamName',
  'boardId',
  'teamField',
  'sprintField',
];

/** Config/CLI sentinel values that mean “skip this field group”. */
const SKIP_SENTINELS = new Set(['none', 'null', 'skip', '-']);

function isSkipSentinel(value) {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return false;
  }
  return SKIP_SENTINELS.has(String(value).trim().toLowerCase());
}

/** Skip team + sprint when teamId or teamName is NONE (or another sentinel). */
function shouldSkipTeamAndSprint(defaults = {}) {
  return isSkipSentinel(defaults.teamId) || isSkipSentinel(defaults.teamName);
}

function pickDefined(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj || {})) {
    if (v !== undefined && v !== null && v !== '') {
      out[k] = v;
    }
  }
  return out;
}

function detectHost(url, explicit) {
  if (explicit === 'gitlab' || explicit === 'github') {
    return explicit;
  }
  if (/github\.com/i.test(url || '')) {
    return 'github';
  }
  return 'gitlab';
}

function stripOutcomePrefix(title) {
  return String(title || '')
    .replace(/^\[x\]\s*merged:\s*/i, '')
    .replace(/^\[!\]\s*closed:\s*/i, '')
    .replace(/^merged:\s*/i, '')
    .replace(/^closed:\s*/i, '')
    .trim();
}

function stripMergedPrefix(title) {
  return stripOutcomePrefix(title);
}

function withMergedPrefix(title) {
  return `${MERGED_PREFIX}${stripOutcomePrefix(title)}`;
}

function withClosedPrefix(title) {
  return `${CLOSED_PREFIX}${stripOutcomePrefix(title)}`;
}

/**
 * Classify a GitHub PR or GitLab MR from API fields.
 * Merged wins over closed (`state: closed` is also used for merged GitHub PRs).
 * @returns {'merged'|'closed'|'open'}
 */
function classifyPrMrState({ merged, state, mergedAt } = {}) {
  if (merged === true || merged === 'true') {
    return 'merged';
  }
  if (mergedAt) {
    return 'merged';
  }
  const s = String(state || '').toLowerCase();
  if (s === 'merged') {
    return 'merged';
  }
  if (s === 'closed') {
    return 'closed';
  }
  return 'open';
}

function prefixForPrMrState(prMrState, title) {
  if (prMrState === 'merged') {
    return withMergedPrefix(title);
  }
  if (prMrState === 'closed') {
    return withClosedPrefix(title);
  }
  return String(title || '').trim();
}

/** Human title from linker title `repo #N: <title>` (optional merged/closed prefix). */
function displayTitleFromLinkTitle(title) {
  return (
    stripOutcomePrefix(title)
      .replace(/^[^#\n]+#\d+:\s*/, '')
      .trim() || String(title || '').trim()
  );
}

/** Only fields newly set by this run (ignore kept/unchanged). */
function collectAdjustedFieldLines(defaults, statusLine) {
  const items = [];
  if (defaults) {
    for (const [key, value] of Object.entries(defaults)) {
      if (typeof value === 'string' && value.startsWith('set ')) {
        const label = ADJUSTED_FIELD_LABELS[key] || key;
        items.push(`${label}: ${value.slice(4)}`);
      }
    }
  }
  if (typeof statusLine === 'string' && statusLine.startsWith('transitioned ')) {
    const to = (statusLine.match(/→\s*(.+)$/) || [])[1]?.trim() || 'In Progress';
    items.push(`Status: ${to}`);
  }
  return items;
}

/**
 * Merge defaults: jira CLI hints < config file < env < CLI.
 * Explicit config/env/CLI must win over go-jira board/login hints.
 */
function mergeDefaultsLayers({ fromJiraCli = {}, fromFile = {}, fromEnv = {}, fromCli = {} } = {}) {
  return {
    ...fromJiraCli,
    ...fromFile,
    ...fromEnv,
    ...fromCli,
  };
}

function missingDefaultKeys(merged) {
  const skipTeamSprint = shouldSkipTeamAndSprint(merged);
  return REQUIRED_DEFAULT_KEYS.filter((k) => {
    if (skipTeamSprint && TEAM_SPRINT_DEFAULT_KEYS.includes(k)) {
      return false;
    }
    const v = merged[k];
    if (isSkipSentinel(v)) {
      return false;
    }
    return v === undefined || v === null || v === '';
  });
}

function shouldMoveRhdhplanDeliveryIssue(projectKey, issueTypeName) {
  return (
    String(projectKey || '').toUpperCase() === RHDHPLAN_PROJECT &&
    MOVEABLE_RHDHPLAN_TYPES.has(String(issueTypeName || ''))
  );
}

function buildBulkMovePayload(issueKey, targetProject, issueTypeId) {
  return {
    sendBulkNotification: false,
    targetToSourcesMapping: {
      [`${targetProject},${issueTypeId}`]: {
        inferClassificationDefaults: true,
        inferFieldDefaults: true,
        inferStatusDefaults: true,
        inferSubtaskTypeDefault: true,
        issueIdsOrKeys: [issueKey],
      },
    },
  };
}

/**
 * Append Jira browse Ref unless disabled or the remote is community-plugins
 * (raise-pr keeps Jira out of that repo's git history / PR bodies).
 */
function shouldAppendJiraRef({ noJiraRef = false, remoteUrl = '' } = {}) {
  if (noJiraRef) {
    return false;
  }
  if (/community-plugins/i.test(remoteUrl || '')) {
    return false;
  }
  return true;
}

function parseEmailToken(raw) {
  const text = String(raw || '').trim();
  if (!text) {
    return null;
  }
  // Prefer splitting on the first colon after an email-shaped left side.
  const at = text.indexOf('@');
  const colon = text.indexOf(':', at > 0 ? at : 0);
  if (at > 0 && colon > at) {
    return { login: text.slice(0, colon), token: text.slice(colon + 1) };
  }
  return null;
}

function findJiraTokenFile() {
  const candidates = [];
  const which = spawnSync('which', ['acli'], { encoding: 'utf8' });
  if (which.status === 0 && which.stdout.trim()) {
    const acliPath = which.stdout.trim();
    const resolved = spawnSync('readlink', ['-f', acliPath], { encoding: 'utf8' });
    const real = (resolved.status === 0 && resolved.stdout.trim()) || acliPath;
    candidates.push(path.join(path.dirname(real), '.jira-token'));
    candidates.push(path.join(path.dirname(acliPath), '.jira-token'));
  }
  candidates.push(path.join(os.homedir(), '.local', 'bin', '.jira-token'));
  candidates.push(path.join(os.homedir(), '.jira-token'));
  for (const p of candidates) {
    if (p && fs.existsSync(p)) {
      return p;
    }
  }
  return null;
}

/**
 * Resolve Jira Basic auth from (in order of preference for token/login):
 * - JIRA_API_TOKEN (+ login from go-jira config / JIRA_EMAIL)
 * - .jira-token next to acli (email:token) — same as rhdh-jira REST fallback
 * Server from go-jira config, JIRA_SERVER, or redhat.atlassian.net.
 */
function resolveJiraAuth({
  env = process.env,
  jiraConfigPath = path.join(os.homedir(), '.config', '.jira', '.config.yml'),
  tokenFilePath = undefined,
} = {}) {
  let fileLogin;
  let fileServer;
  let boardId;
  if (fs.existsSync(jiraConfigPath)) {
    const text = fs.readFileSync(jiraConfigPath, 'utf8');
    fileLogin = (text.match(/^login:\s*(.+)$/m) || [])[1]?.trim();
    fileServer = (text.match(/^server:\s*(.+)$/m) || [])[1]?.trim()?.replace(/\/$/, '');
    const boardMatch = text.match(/board:\s*\n\s*id:\s*(\d+)/);
    boardId = boardMatch ? Number(boardMatch[1]) : undefined;
  }

  let login = env.JIRA_EMAIL || fileLogin || '';
  let token = env.JIRA_API_TOKEN || '';
  let server = (env.JIRA_SERVER || fileServer || DEFAULT_JIRA_SERVER).replace(/\/$/, '');
  let authSource = token ? 'JIRA_API_TOKEN' : null;

  const embedded = parseEmailToken(token);
  if (embedded) {
    login = embedded.login;
    token = embedded.token;
    authSource = 'JIRA_API_TOKEN (email:token)';
  }

  if (!token || !login) {
    const tokenPath = tokenFilePath !== undefined ? tokenFilePath : findJiraTokenFile();
    if (tokenPath && fs.existsSync(tokenPath)) {
      const parsed = parseEmailToken(fs.readFileSync(tokenPath, 'utf8'));
      if (parsed) {
        login = login || parsed.login;
        token = token || parsed.token;
        authSource = `.jira-token (${tokenPath})`;
      }
    }
  }

  if (!token || !login) {
    const err = new Error(
      [
        'Jira auth missing.',
        '',
        'Option A (go-jira): set JIRA_API_TOKEN and ensure ~/.config/.jira/.config.yml has login/server.',
        'Option B (rhdh-jira): create email:token at .jira-token next to acli',
        '  (run /setup-rhdh-skills jira, or ask /rhdh-jira-api for the auth setup).',
        'Option C: export JIRA_EMAIL and JIRA_API_TOKEN.',
      ].join('\n'),
    );
    err.code = 'JIRA_AUTH_MISSING';
    throw err;
  }

  return {
    login,
    token,
    server,
    boardId,
    authSource,
  };
}

function parsePrMrUrl(url) {
  let m = String(url || '').match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/i);
  if (m) {
    return { kind: 'github', owner: m[1], repo: m[2], id: m[3] };
  }
  m = String(url || '').match(/https?:\/\/(gitlab[^/]*)\/(.+?)\/-\/merge_requests\/(\d+)/i);
  if (m) {
    return { kind: 'gitlab', host: m[1], project: m[2], id: m[3] };
  }
  return null;
}

/** kebab-case flag → camelCase property (`no-defaults` → `noDefaults`). */
function flagToCamel(flag) {
  return String(flag).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

/**
 * Minimal argv parser.
 * @param {string[]} argv
 * @param {{ booleanFlags?: string[], onHelp?: () => void }} [opts]
 */
function parseArgs(argv, { booleanFlags = [], onHelp } = {}) {
  const bool = new Set(booleanFlags);
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '-h' || a === '--help') {
      if (typeof onHelp === 'function') onHelp();
      continue;
    }
    if (!a.startsWith('--')) {
      args._.push(a);
      continue;
    }
    const key = a.slice(2);
    if (bool.has(key)) {
      args[flagToCamel(key)] = true;
      continue;
    }
    const val = argv[i + 1];
    if (!val || val.startsWith('--')) {
      throw new Error(`Missing value for --${key}`);
    }
    args[key] = val;
    i += 1;
  }
  return args;
}

module.exports = {
  ADJUSTED_FIELD_LABELS,
  CLOSED_PREFIX,
  DEFAULT_JIRA_SERVER,
  MERGED_PREFIX,
  MOVEABLE_RHDHPLAN_TYPES,
  REQUIRED_DEFAULT_KEYS,
  RHDHPLAN_PROJECT,
  RHIDP_PROJECT,
  buildBulkMovePayload,
  classifyPrMrState,
  collectAdjustedFieldLines,
  detectHost,
  displayTitleFromLinkTitle,
  findJiraTokenFile,
  flagToCamel,
  isSkipSentinel,
  mergeDefaultsLayers,
  missingDefaultKeys,
  parseArgs,
  parseEmailToken,
  parsePrMrUrl,
  pickDefined,
  prefixForPrMrState,
  resolveJiraAuth,
  shouldAppendJiraRef,
  shouldMoveRhdhplanDeliveryIssue,
  shouldSkipTeamAndSprint,
  stripMergedPrefix,
  stripOutcomePrefix,
  withClosedPrefix,
  withMergedPrefix,
};
