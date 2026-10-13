#!/usr/bin/env node
/*
  Jira PR/MR Web link helper for skill jira-pr-mr-link.

  Commands:
    link         Create/update a Web link, apply missing configured defaults, In Progress.
                 Auto-moves RHDHPLAN Epic/Story/Task → RHIDP first.
    mark-merged  Prefix remotelink titles: "[x] merged: " or "[!] closed: "

  Auth (either):
    - $JIRA_API_TOKEN + login/server from ~/.config/.jira/.config.yml
    - .jira-token (email:token) next to acli — same as rhdh-jira REST/GraphQL
*/

'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const {
  DEFAULT_JIRA_SERVER,
  RHIDP_PROJECT,
  buildBulkMovePayload,
  collectAdjustedFieldLines,
  detectHost,
  displayTitleFromLinkTitle,
  mergeDefaultsLayers,
  missingDefaultKeys,
  parsePrMrUrl,
  pickDefined,
  resolveJiraAuth,
  shouldMoveRhdhplanDeliveryIssue,
  shouldSkipTeamAndSprint,
  classifyPrMrState,
  prefixForPrMrState,
  withClosedPrefix,
  withMergedPrefix,
  parseArgs: parseArgv,
} = require('./lib.js');

const USER_CONFIG_DIR = path.join(os.homedir(), '.config', 'jira-pr-mr-link');
const USER_CONFIG_PATH = path.join(USER_CONFIG_DIR, 'config.json');
const EXAMPLE_CONFIG_PATH = path.join(__dirname, '..', 'config.example.json');
const SKILL_CONFIG_PATHS = [
  process.env.JIRA_PR_MR_CONFIG,
  USER_CONFIG_PATH,
  path.join(__dirname, '..', 'config.local.json'),
].filter(Boolean);

const ICONS = {
  gitlab: {
    application: { type: 'com.gitlab', name: 'GitLab' },
    icon: { title: 'GitLab', url16x16: 'https://gitlab.com/favicon.ico' },
  },
  github: {
    application: { type: 'com.github', name: 'GitHub' },
    icon: {
      title: 'GitHub',
      url16x16: 'https://github.githubassets.com/favicons/favicon.png',
    },
  },
};

const LEAVE_STATUS = new Set(['In Progress', 'Review', 'Closed', 'Done']);

function configurationError(missingKeys, configPath) {
  const missing = missingKeys.join(', ');
  const lines = [
    `Missing Jira PR/MR defaults: ${missing}`,
    '',
    'This skill has no built-in team/assignee values. Configure once:',
    '',
    `  mkdir -p ${USER_CONFIG_DIR}`,
    `  cp ${EXAMPLE_CONFIG_PATH} ${USER_CONFIG_PATH}`,
    `  # edit ${USER_CONFIG_PATH}  (assigneeEmail, teamId, teamName, boardId, …)`,
    '',
    'Or set env vars (JIRA_PR_MR_ASSIGNEE, JIRA_PR_MR_TEAM_ID, JIRA_PR_MR_BOARD_ID, …)',
    'or pass --assignee / --team-id / --board-id / … on the CLI.',
    '',
    'To link without filling defaults: add --no-defaults (or JIRA_PR_MR_APPLY_DEFAULTS=0).',
  ];
  if (configPath) {
    lines.splice(1, 0, `Config loaded from: ${configPath}`);
  }
  return new Error(lines.join('\n'));
}

function usage(exitCode = 0) {
  console.log(`Usage:
  link-pr-mr.js link --issue KEY --url URL --title TITLE [--host gitlab|github]
    [--no-defaults] [--no-comment]
    [--assignee EMAIL] [--team-id ID] [--team-name NAME] [--board-id N]
    [--story-points N] [--priority NAME]

  link-pr-mr.js mark-merged --issue KEY
    Prefix merged PRs/MRs with "[x] merged: " and closed (unmerged) ones
    with "[!] closed: ". Open PRs/MRs are left unchanged.

Environment:
  JIRA_API_TOKEN              API token (or email:token); optional if .jira-token exists
  JIRA_EMAIL                  login email when token is bare
  JIRA_SERVER                 override (default ${DEFAULT_JIRA_SERVER})
  JIRA_PR_MR_CONFIG           optional path to JSON config
  JIRA_PR_MR_ASSIGNEE         assignee email
  JIRA_PR_MR_TEAM_ID          Atlassian team UUID
  JIRA_PR_MR_TEAM_NAME        team display name
  JIRA_PR_MR_BOARD_ID         sprint board id
  JIRA_PR_MR_STORY_POINTS     story points (number)
  JIRA_PR_MR_PRIORITY         priority name (e.g. Normal)
  JIRA_PR_MR_APPLY_DEFAULTS   0/false to skip defaults (like --no-defaults)

Config (required for defaults; first found wins):
  $JIRA_PR_MR_CONFIG
  ${USER_CONFIG_PATH}
  <skill>/config.local.json

  Setup:
    mkdir -p ${USER_CONFIG_DIR}
    cp ${EXAMPLE_CONFIG_PATH} ${USER_CONFIG_PATH}

Auth: JIRA_API_TOKEN + ~/.config/.jira/.config.yml, or .jira-token next to acli
  (run /setup-rhdh-skills jira, or ask /rhdh-jira-api for the auth setup).

RHDHPLAN Epic/Story/Task issues are moved to RHIDP before defaults.

After link (unless --no-comment), posts/updates a Jira comment:
  PR: <a href="{url}">{url}</a>   (GitHub)
  MR: <a href="{url}">{url}</a>   (GitLab)
  Adjusted fields:   (only newly set fields; omitted if none)
`);
  process.exit(exitCode);
}

function parseArgs(argv) {
  return parseArgv(argv, {
    booleanFlags: ['no-defaults', 'no-comment'],
    onHelp: () => usage(0),
  });
}

function readJsonFile(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (err) {
    throw new Error(`Invalid JSON config ${filePath}: ${err.message}`);
  }
}

function envNumber(name) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') {
    return undefined;
  }
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function envBoolFalse(name) {
  const raw = (process.env[name] || '').trim().toLowerCase();
  return raw === '0' || raw === 'false' || raw === 'no';
}

function readOptionalSkillConfig() {
  for (const p of SKILL_CONFIG_PATHS) {
    const data = readJsonFile(p);
    if (data) {
      return { path: p, data };
    }
  }
  return { path: null, data: {} };
}

/**
 * Merge defaults: jira CLI board/login hints < config file < env < CLI.
 * No silent team/assignee builtins — missing keys error when applying defaults.
 */
function resolveDefaults(fileCfg, args = {}, { requireComplete = true } = {}) {
  const { path: configPath, data: fileData } = readOptionalSkillConfig();
  const fromFile = pickDefined({
    storyPoints: fileData.storyPoints,
    teamName: fileData.teamName,
    teamId: fileData.teamId,
    boardId: fileData.boardId,
    assigneeEmail: fileData.assigneeEmail,
    priorityName: fileData.priorityName,
    storyPointsField: fileData.storyPointsField,
    teamField: fileData.teamField,
    sprintField: fileData.sprintField,
  });
  const fromJiraCli = pickDefined({
    boardId: fileCfg.boardId,
    assigneeEmail:
      fileCfg.login && String(fileCfg.login).includes('@') ? fileCfg.login : undefined,
  });
  const fromEnv = pickDefined({
    storyPoints: envNumber('JIRA_PR_MR_STORY_POINTS'),
    teamName: process.env.JIRA_PR_MR_TEAM_NAME,
    teamId: process.env.JIRA_PR_MR_TEAM_ID,
    boardId: envNumber('JIRA_PR_MR_BOARD_ID'),
    assigneeEmail: process.env.JIRA_PR_MR_ASSIGNEE,
    priorityName: process.env.JIRA_PR_MR_PRIORITY,
    storyPointsField: process.env.JIRA_PR_MR_STORY_POINTS_FIELD,
    teamField: process.env.JIRA_PR_MR_TEAM_FIELD,
    sprintField: process.env.JIRA_PR_MR_SPRINT_FIELD,
  });
  const fromCli = pickDefined({
    storyPoints:
      args['story-points'] !== undefined ? Number(args['story-points']) : undefined,
    teamName: args['team-name'],
    teamId: args['team-id'],
    boardId: args['board-id'] !== undefined ? Number(args['board-id']) : undefined,
    assigneeEmail: args.assignee,
    priorityName: args.priority,
  });

  const merged = mergeDefaultsLayers({ fromJiraCli, fromFile, fromEnv, fromCli });
  merged._configPath = configPath;

  if (requireComplete) {
    const missing = missingDefaultKeys(merged);
    if (missing.length) {
      throw configurationError(missing, configPath);
    }
  }

  return merged;
}

function basicAuth(login, token) {
  return `Basic ${Buffer.from(`${login}:${token}`).toString('base64')}`;
}

async function jiraFetch(cfg, method, apiPath, body) {
  const url = `${cfg.server}${apiPath}`;
  const headers = {
    Authorization: basicAuth(cfg.login, cfg.token),
    Accept: 'application/json',
  };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  if (!res.ok) {
    const err = new Error(`Jira ${method} ${apiPath} → HTTP ${res.status}: ${text.slice(0, 500)}`);
    err.status = res.status;
    err.body = json;
    throw err;
  }
  return { status: res.status, json };
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitBulkTask(cfg, taskId, { timeoutMs = 90000, intervalMs = 1000 } = {}) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const { json } = await jiraFetch(cfg, 'GET', `/rest/api/3/bulk/queue/${encodeURIComponent(taskId)}`);
    const status = String(json?.status || '').toUpperCase();
    if (status === 'COMPLETE' || status === 'COMPLETED') {
      return json;
    }
    if (status === 'FAILED' || status === 'CANCELLED' || status === 'CANCELED') {
      throw new Error(`Bulk move ${status}: ${JSON.stringify(json).slice(0, 400)}`);
    }
    await sleep(intervalMs);
  }
  throw new Error(`Bulk move timed out after ${timeoutMs}ms (taskId=${taskId})`);
}

async function resolveIssueKeyById(cfg, issueId) {
  const { json } = await jiraFetch(cfg, 'GET', `/rest/api/3/issue/${issueId}?fields=summary`);
  return json?.key || null;
}

/**
 * If issue is RHDHPLAN Epic/Story/Task, move it to RHIDP (same issue type) via bulk move.
 * Returns { issue, moved, from?, detail }.
 */
async function maybeMoveRhdhplanDeliveryIssue(cfg, issueKey) {
  const { json } = await jiraFetch(
    cfg,
    'GET',
    `/rest/api/3/issue/${encodeURIComponent(issueKey)}?fields=project,issuetype`,
  );
  const projectKey = json?.fields?.project?.key;
  const typeName = json?.fields?.issuetype?.name;
  const typeId = json?.fields?.issuetype?.id;
  if (!shouldMoveRhdhplanDeliveryIssue(projectKey, typeName)) {
    return {
      issue: issueKey,
      moved: false,
      detail: `kept ${projectKey || '?'} ${typeName || '?'}`,
    };
  }
  if (!typeId) {
    throw new Error(`Cannot move ${issueKey}: missing issuetype id`);
  }

  const payload = buildBulkMovePayload(issueKey, RHIDP_PROJECT, typeId);
  const { json: submitted } = await jiraFetch(cfg, 'POST', '/rest/api/3/bulk/issues/move', payload);
  const taskId = submitted?.taskId;
  if (!taskId) {
    throw new Error(`Bulk move submitted but no taskId: ${JSON.stringify(submitted).slice(0, 300)}`);
  }
  const progress = await waitBulkTask(cfg, taskId);
  const ids = progress?.processedAccessibleIssues || [];
  let newKey = null;
  if (ids.length > 0) {
    newKey = await resolveIssueKeyById(cfg, ids[0]);
  }
  // Fallback: old key often redirects after move
  if (!newKey) {
    const { json: after } = await jiraFetch(
      cfg,
      'GET',
      `/rest/api/3/issue/${encodeURIComponent(issueKey)}?fields=project,issuetype`,
    );
    newKey = after?.key || issueKey;
  }
  return {
    issue: newKey,
    moved: true,
    from: issueKey,
    detail: `moved ${issueKey} → ${newKey} (${typeName} ${projectKey}→${RHIDP_PROJECT})`,
  };
}

async function getIssueFields(cfg, issue) {
  const d = cfg.defaults;
  const fields = [
    'summary',
    'status',
    'assignee',
    'priority',
    d.storyPointsField,
    d.teamField,
    d.sprintField,
  ]
    .filter(Boolean)
    .join(',');
  const { json } = await jiraFetch(cfg, 'GET', `/rest/api/3/issue/${issue}?fields=${fields}`);
  return json.fields;
}

async function resolveAssigneeAccountId(cfg, email) {
  const q = encodeURIComponent(email);
  const { json } = await jiraFetch(cfg, 'GET', `/rest/api/3/user/search?query=${q}`);
  if (!Array.isArray(json) || !json[0]?.accountId) {
    throw new Error(`Could not resolve accountId for ${email}`);
  }
  return json[0].accountId;
}

async function resolveActiveSprint(cfg, boardId) {
  const { json } = await jiraFetch(
    cfg,
    'GET',
    `/rest/agile/1.0/board/${boardId}/sprint?state=active`,
  );
  const sprint = json?.values?.[0];
  if (!sprint?.id) {
    throw new Error(`No active sprint on board ${boardId}`);
  }
  return { id: sprint.id, name: sprint.name };
}

function isEmpty(value) {
  if (value === null || value === undefined || value === '') {
    return true;
  }
  if (Array.isArray(value) && value.length === 0) {
    return true;
  }
  return false;
}

async function applyMissingDefaults(cfg, issue, fields) {
  const d = cfg.defaults;
  const summary = {
    storyPoints: 'unchanged',
    team: 'unchanged',
    sprint: 'unchanged',
    assignee: 'unchanged',
    priority: 'unchanged',
  };
  const update = {};

  if (d.storyPoints !== undefined && d.storyPoints !== null && d.storyPoints !== false) {
    if (isEmpty(fields[d.storyPointsField])) {
      update[d.storyPointsField] = d.storyPoints;
      summary.storyPoints = `set ${d.storyPoints}`;
    } else {
      summary.storyPoints = `kept ${fields[d.storyPointsField]}`;
    }
  } else {
    summary.storyPoints = 'skipped (not configured)';
  }

  if (shouldSkipTeamAndSprint(d)) {
    summary.team = 'skipped (NONE)';
    summary.sprint = 'skipped (NONE)';
  } else {
    if (d.teamId) {
      if (isEmpty(fields[d.teamField])) {
        update[d.teamField] = { id: d.teamId };
        summary.team = `set ${d.teamName || d.teamId}`;
      } else {
        summary.team = `kept ${fields[d.teamField].name || fields[d.teamField].id}`;
      }
    } else {
      summary.team = 'skipped (no teamId)';
    }

    if (d.boardId) {
      if (isEmpty(fields[d.sprintField])) {
        try {
          const sprint = await resolveActiveSprint(cfg, d.boardId);
          update[d.sprintField] = sprint.id;
          summary.sprint = `set ${sprint.name}`;
        } catch (err) {
          summary.sprint = `skipped (${err.message})`;
        }
      } else {
        const names = (fields[d.sprintField] || []).map((s) => s.name).join(', ');
        summary.sprint = `kept ${names || 'existing'}`;
      }
    } else {
      summary.sprint = 'skipped (no boardId)';
    }
  }

  if (d.assigneeEmail) {
    if (isEmpty(fields.assignee)) {
      const accountId = await resolveAssigneeAccountId(cfg, d.assigneeEmail);
      update.assignee = { accountId };
      summary.assignee = `set ${d.assigneeEmail}`;
    } else {
      summary.assignee = `kept ${fields.assignee.emailAddress || fields.assignee.displayName}`;
    }
  } else {
    summary.assignee = 'skipped (no assigneeEmail)';
  }

  if (d.priorityName) {
    if (isEmpty(fields.priority)) {
      update.priority = { name: d.priorityName };
      summary.priority = `set ${d.priorityName}`;
    } else {
      summary.priority = `kept ${fields.priority.name}`;
    }
  } else {
    summary.priority = 'skipped (no priorityName)';
  }

  if (Object.keys(update).length > 0) {
    await jiraFetch(cfg, 'PUT', `/rest/api/3/issue/${issue}`, { fields: update });
  }
  return summary;
}

async function transitionInProgress(cfg, issue, currentStatus) {
  if (LEAVE_STATUS.has(currentStatus)) {
    return { status: `kept ${currentStatus}` };
  }
  const { json } = await jiraFetch(cfg, 'GET', `/rest/api/3/issue/${issue}/transitions`);
  const transition = (json.transitions || []).find(
    (t) => t.to?.name === 'In Progress' || t.name === 'In Progress',
  );
  if (!transition) {
    return { status: `no In Progress transition from ${currentStatus}` };
  }
  await jiraFetch(cfg, 'POST', `/rest/api/3/issue/${issue}/transitions`, {
    transition: { id: transition.id },
  });
  return { status: `transitioned ${currentStatus} → In Progress` };
}

async function upsertRemoteLink(cfg, issue, { url, title, host }) {
  const iconCfg = ICONS[host];
  const { json: existing } = await jiraFetch(cfg, 'GET', `/rest/api/3/issue/${issue}/remotelink`);
  const match = (existing || []).find((l) => l.object?.url === url);
  const payload = {
    application: iconCfg.application,
    object: {
      url,
      title,
      icon: iconCfg.icon,
    },
  };
  if (match?.id) {
    await jiraFetch(cfg, 'PUT', `/rest/api/3/issue/${issue}/remotelink/${match.id}`, payload);
    return { action: 'updated', id: match.id, title };
  }
  const { json } = await jiraFetch(cfg, 'POST', `/rest/api/3/issue/${issue}/remotelink`, payload);
  return { action: 'created', id: json?.id, title };
}

function printLinkSummary(result) {
  console.log(`issue: ${result.issue}`);
  if (result.move) {
    console.log(`move: ${result.move}`);
  }
  console.log(`webLink: ${result.webLink.action} — ${result.webLink.title}`);
  console.log(`url: ${result.url}`);
  console.log(`status: ${result.status}`);
  if (result.defaults) {
    console.log('defaults:');
    for (const [k, v] of Object.entries(result.defaults)) {
      console.log(`  ${k}: ${v}`);
    }
  }
  if (result.comment) {
    console.log(`comment: ${result.comment}`);
  }
}

function adfParagraph(text) {
  return {
    type: 'paragraph',
    content: text ? [{ type: 'text', text }] : [],
  };
}

function adfBulletList(items) {
  return {
    type: 'bulletList',
    content: items.map((text) => ({
      type: 'listItem',
      content: [adfParagraph(text)],
    })),
  };
}

function adfPrOrMrLine(url, host) {
  const label = detectHost(url, host) === 'github' ? 'PR: ' : 'MR: ';
  return {
    type: 'paragraph',
    content: [
      { type: 'text', text: label },
      {
        type: 'text',
        text: url,
        marks: [{ type: 'link', attrs: { href: url } }],
      },
    ],
  };
}

function buildLinkCommentAdf({ url, status, defaults, host }) {
  const content = [adfPrOrMrLine(url, host)];
  const adjusted = collectAdjustedFieldLines(defaults, status);
  if (adjusted.length > 0) {
    content.push(adfParagraph('Adjusted fields:'));
    content.push(adfBulletList(adjusted));
  }
  return { type: 'doc', version: 1, content };
}

/** Paginate comments (oldest-first); keep the newest match that mentions url. */
async function findCommentMentioningUrl(cfg, issue, url) {
  let startAt = 0;
  const pageSize = 100;
  let match = null;
  for (;;) {
    const { json } = await jiraFetch(
      cfg,
      'GET',
      `/rest/api/3/issue/${encodeURIComponent(issue)}/comment?startAt=${startAt}&maxResults=${pageSize}`,
    );
    const comments = json?.comments || [];
    const total = typeof json?.total === 'number' ? json.total : startAt + comments.length;
    for (const c of comments) {
      if (JSON.stringify(c.body || '').includes(url)) {
        match = c;
      }
    }
    startAt += comments.length;
    if (comments.length === 0 || startAt >= total) {
      break;
    }
  }
  return match;
}

async function postLinkComment(cfg, issue, { url, webLink, status, defaults, host }) {
  const body = buildLinkCommentAdf({ url, webLink, status, defaults, host });
  const existing = await findCommentMentioningUrl(cfg, issue, url);
  if (existing?.id) {
    await jiraFetch(cfg, 'PUT', `/rest/api/3/issue/${issue}/comment/${existing.id}`, {
      body,
    });
    return `updated id=${existing.id}`;
  }
  const { json } = await jiraFetch(cfg, 'POST', `/rest/api/3/issue/${issue}/comment`, {
    body,
  });
  return json?.id ? `posted id=${json.id}` : 'posted';
}

async function cmdLink(args, cfg) {
  let issue = args.issue;
  const url = args.url;
  const title = args.title;
  if (!issue || !url || !title) {
    throw new Error('link requires --issue, --url, and --title');
  }
  const host = detectHost(url, args.host);
  const moveResult = await maybeMoveRhdhplanDeliveryIssue(cfg, issue);
  issue = moveResult.issue;

  const webLink = await upsertRemoteLink(cfg, issue, { url, title, host });

  const skipDefaults = args.noDefaults || envBoolFalse('JIRA_PR_MR_APPLY_DEFAULTS');
  let defaults;
  let statusLine;
  if (!skipDefaults) {
    const missing = missingDefaultKeys(cfg.defaults);
    if (missing.length) {
      throw configurationError(missing, cfg.defaults._configPath);
    }
    const fields = await getIssueFields(cfg, issue);
    defaults = await applyMissingDefaults(cfg, issue, fields);
    const statusResult = await transitionInProgress(cfg, issue, fields.status?.name || '');
    statusLine = statusResult.status;
  } else {
    statusLine = 'skipped (--no-defaults)';
  }

  let commentLine;
  if (!args.noComment) {
    try {
      commentLine = await postLinkComment(cfg, issue, {
        url,
        webLink,
        status: statusLine,
        defaults,
        host,
      });
    } catch (err) {
      commentLine = `failed — ${err.message}`;
    }
  } else {
    commentLine = 'skipped (--no-comment)';
  }

  printLinkSummary({
    issue,
    url,
    move: moveResult.detail,
    webLink,
    status: statusLine,
    defaults,
    comment: commentLine,
  });
}

function lookupPrMrState(ref) {
  if (ref.kind === 'github') {
    const label = `${ref.owner}/${ref.repo}#${ref.id}`;
    const out = spawnSync(
      'gh',
      [
        'api',
        `repos/${ref.owner}/${ref.repo}/pulls/${ref.id}`,
        '--jq',
        '{merged:.merged,state:.state}',
      ],
      { encoding: 'utf8' },
    );
    if (out.status !== 0) {
      const err = (out.stderr || out.stdout || '').trim().slice(0, 240);
      console.error(`warn: merge-check failed for github ${label}: ${err || `exit ${out.status}`}`);
      return 'unknown';
    }
    try {
      return classifyPrMrState(JSON.parse(out.stdout));
    } catch (err) {
      console.error(`warn: merge-check parse failed for github ${label}: ${err.message}`);
      return 'unknown';
    }
  }
  const label = `${ref.project}!${ref.id}`;
  const project = encodeURIComponent(ref.project);
  const glabArgs = ['api'];
  if (ref.host) {
    glabArgs.push('--hostname', ref.host);
  }
  glabArgs.push(`projects/${project}/merge_requests/${ref.id}`);
  const out = spawnSync('glab', glabArgs, { encoding: 'utf8' });
  if (out.status !== 0) {
    const err = (out.stderr || out.stdout || '').trim().slice(0, 240);
    console.error(`warn: merge-check failed for gitlab ${label}: ${err || `exit ${out.status}`}`);
    return 'unknown';
  }
  try {
    const mr = JSON.parse(out.stdout);
    return classifyPrMrState({
      merged: Boolean(mr.merged_at) || mr.state === 'merged',
      state: mr.state,
      mergedAt: mr.merged_at,
    });
  } catch (err) {
    console.error(`warn: merge-check parse failed for gitlab ${label}: ${err.message}`);
    return 'unknown';
  }
}

async function cmdMarkMerged(args, cfg) {
  const issue = args.issue;
  if (!issue) {
    throw new Error('mark-merged requires --issue');
  }
  const { json: links } = await jiraFetch(cfg, 'GET', `/rest/api/3/issue/${issue}/remotelink`);
  const updated = [];
  const leftOpen = [];
  const skipped = [];

  for (const link of links || []) {
    const url = link.object?.url;
    const title = link.object?.title || '';
    if (!url) {
      continue;
    }
    const ref = parsePrMrUrl(url);
    if (!ref) {
      skipped.push(title || url);
      continue;
    }
    const prMrState = lookupPrMrState(ref);
    if (prMrState === 'open' || prMrState === 'unknown') {
      leftOpen.push({ title: title || url, url });
      continue;
    }
    const newTitle = prefixForPrMrState(prMrState, title);
    if (newTitle === title) {
      updated.push({ label: `already: ${title}`, url });
      continue;
    }
    const host = ref.kind === 'github' ? 'github' : 'gitlab';
    const iconCfg = ICONS[host];
    await jiraFetch(cfg, 'PUT', `/rest/api/3/issue/${issue}/remotelink/${link.id}`, {
      application: iconCfg.application,
      object: {
        url,
        title: newTitle,
        icon: iconCfg.icon,
        status: { resolved: true },
      },
    });
    updated.push({ label: newTitle, url });
  }

  console.log(`issue: ${issue}`);
  console.log(`updated: ${updated.length}`);
  for (const item of updated) {
    console.log(`  ${item.label}`);
    console.log(`    ${item.url}`);
  }
  console.log(`leftOpen: ${leftOpen.length}`);
  for (const item of leftOpen) {
    console.log(`  ${item.title}`);
    console.log(`    ${item.url}`);
  }
  if (skipped.length) {
    console.log(`skippedNonPrMr: ${skipped.length}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  if (!cmd) {
    usage(1);
  }

  const auth = resolveJiraAuth();
  // Never hard-fail on incomplete defaults before Web link/comment; validate only when applying.
  const defaults = resolveDefaults(
    { login: auth.login, boardId: auth.boardId },
    args,
    { requireComplete: false },
  );
  const cfg = {
    login: auth.login,
    server: auth.server,
    boardId: defaults.boardId || auth.boardId,
    token: auth.token,
    defaults,
  };

  if (cmd === 'link') {
    await cmdLink(args, cfg);
    return;
  }
  if (cmd === 'mark-merged') {
    await cmdMarkMerged(args, cfg);
    return;
  }
  throw new Error(`Unknown command: ${cmd}`);
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`[ERROR] ${err.message}`);
    process.exit(1);
  });
}

module.exports = {
  applyMissingDefaults,
  buildLinkCommentAdf,
  cmdLink,
  collectAdjustedFieldLines,
  configurationError,
  detectHost,
  displayTitleFromLinkTitle,
  findCommentMentioningUrl,
  maybeMoveRhdhplanDeliveryIssue,
  parseArgs,
  parsePrMrUrl,
  resolveDefaults,
  withMergedPrefix,
  withClosedPrefix,
  prefixForPrMrState,
};
