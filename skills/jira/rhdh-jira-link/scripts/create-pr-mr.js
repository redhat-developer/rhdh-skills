#!/usr/bin/env node
/*
  Create a GitHub PR or GitLab MR, then link it to Jira (web link + defaults + comment).

  Prefer this over raw `gh pr create` / `glab mr create` in agent sessions so one
  shell call covers push, create, Jira link, and opening diffs.

  Opens diffs once unless --no-open (agents: report browserOpened from stdout).

  Jira comment markup is owned by link-pr-mr.js:
    PR: <a href="{url}">{url}</a>   (GitHub)
    MR: <a href="{url}">{url}</a>   (GitLab)
    Adjusted fields: (only newly set; omitted if none)

  Usage:
    create-pr-mr.js --issue KEY --title TITLE [--body BODY] [--target BRANCH]
      [--draft] [--no-push] [--no-link] [--no-open] [--no-defaults] [--no-comment]
      [--no-jira-ref]
      [--assignee EMAIL] [--team-id ID] [--board-id N] … (forwarded to link-pr-mr.js)

  Auth: git remotes + gh/glab; Jira via JIRA_API_TOKEN or .jira-token (unless --no-link).
  Defaults: config required (see config.example.json); CLI > env > config > jira CLI hints.
*/

'use strict';

const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { shouldAppendJiraRef, resolveJiraAuth, parseArgs: parseArgv } = require('./lib.js');

const LINK_SCRIPT = path.join(__dirname, 'link-pr-mr.js');
const JIRA_BROWSE = 'https://redhat.atlassian.net/browse';

function usage(exitCode = 0) {
  console.log(`Usage:
  create-pr-mr.js --issue KEY --title TITLE [--body BODY] [--target BRANCH]
    [--draft] [--no-push] [--no-link] [--no-open] [--no-defaults] [--no-comment]
    [--no-jira-ref]
    [--assignee EMAIL] [--team-id ID] [--team-name NAME] [--board-id N]
    [--story-points N] [--priority NAME] [--host github|gitlab]

Creates a PR (GitHub) or MR (GitLab) from the current branch, links Jira, opens diffs.
Jira defaults need ~/.config/jira-pr-mr-link/config.json (or env/CLI); see config.example.json.
Skips appending Ref: browse URL for community-plugins remotes (or with --no-jira-ref).

Examples:
  create-pr-mr.js --issue RHIDP-12345 --title 'fix: widget' --target main \\
    --body "$(cat <<'EOF'
## Summary
- ...

Generated-by: cursor
EOF
)"
`);
  process.exit(exitCode);
}

function parseArgs(argv) {
  return parseArgv(argv, {
    booleanFlags: [
      'draft',
      'no-push',
      'no-link',
      'no-open',
      'no-defaults',
      'no-comment',
      'no-jira-ref',
    ],
    onHelp: () => usage(0),
  });
}

function run(cmd, cmdArgs, opts = {}) {
  const out = spawnSync(cmd, cmdArgs, {
    encoding: 'utf8',
    env: { ...process.env, ...(opts.env || {}) },
    cwd: opts.cwd || process.cwd(),
  });
  return {
    status: out.status ?? 1,
    stdout: out.stdout || '',
    stderr: out.stderr || '',
    combined: `${out.stdout || ''}${out.stderr || ''}`.trim(),
  };
}

function git(args) {
  const r = run('git', args);
  if (r.status !== 0) {
    throw new Error(`git ${args.join(' ')} failed: ${r.combined}`);
  }
  return r.stdout.trim();
}

function detectHost(explicit) {
  if (explicit === 'github' || explicit === 'gitlab') {
    return explicit;
  }
  const url = git(['remote', 'get-url', 'origin']);
  if (/github\.com/i.test(url)) {
    return 'github';
  }
  return 'gitlab';
}

function repoShortName() {
  const url = git(['remote', 'get-url', 'origin']);
  const cleaned = url.replace(/\.git$/, '');
  const parts = cleaned.split(/[/:]/);
  return parts[parts.length - 1] || 'repo';
}

function originRemoteUrl() {
  try {
    return git(['remote', 'get-url', 'origin']);
  } catch {
    return '';
  }
}

function ensureBody(body, issue, { appendJiraRef }) {
  let text = (body || '').trim();
  const refLine = `Ref: ${JIRA_BROWSE}/${issue}`;
  if (appendJiraRef && !text.includes(issue) && !text.includes(refLine)) {
    text = text ? `${text}\n\n${refLine}` : refLine;
  }
  if (!/Generated-by:\s*cursor/i.test(text) && !/Assisted-by:\s*cursor/i.test(text)) {
    text = `${text}\n\nGenerated-by: cursor`;
  }
  return `${text.trim()}\n`;
}

function parseCreatedUrl(text, host) {
  if (host === 'github') {
    const m = text.match(/https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/\d+/i);
    return m ? m[0] : '';
  }
  const m = text.match(/https:\/\/[^\s]*gitlab[^\s]*\/.+?\/-\/merge_requests\/\d+/i);
  return m ? m[0] : '';
}

function diffsUrl(url, host) {
  if (host === 'github') {
    return url.replace(/\/?$/, '') + '/files';
  }
  return url.replace(/\/?$/, '') + '/diffs';
}

function openBrowser(url) {
  const opener =
    process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'cmd' : 'xdg-open';
  const args = process.platform === 'win32' ? ['/c', 'start', '', url] : [url];
  spawnSync(opener, args, { stdio: 'ignore', detached: true });
}

function createGithub({ title, body, target, draft }) {
  const args = ['pr', 'create', '--title', title, '--body', body];
  if (target) args.push('--base', target);
  if (draft) args.push('--draft');
  const r = run('gh', args, { env: { CURSOR_JIRA_CREATE_PR_MR: '1' } });
  if (r.status !== 0) {
    throw new Error(`gh pr create failed: ${r.combined}`);
  }
  const url = parseCreatedUrl(r.combined, 'github');
  if (!url) {
    throw new Error(`gh pr create succeeded but no PR URL in output:\n${r.combined}`);
  }
  return { url, output: r.combined };
}

function createGitlab({ title, body, target, draft }) {
  const args = ['mr', 'create', '--yes', '--title', title, '--description', body];
  if (target) args.push('--target-branch', target);
  if (draft) args.push('--draft');
  const r = run('glab', args, { env: { CURSOR_JIRA_CREATE_PR_MR: '1' } });
  if (r.status !== 0) {
    throw new Error(`glab mr create failed: ${r.combined}`);
  }
  const url = parseCreatedUrl(r.combined, 'gitlab');
  if (!url) {
    throw new Error(`glab mr create succeeded but no MR URL in output:\n${r.combined}`);
  }
  return { url, output: r.combined };
}

function assertJiraAuthAvailable() {
  try {
    resolveJiraAuth();
  } catch (err) {
    throw new Error(
      `${err.message}\n\nPass --no-link to create the PR/MR without Jira linking.`,
    );
  }
}

function linkJira({ issue, url, title, host, linkArgs = {} }) {
  assertJiraAuthAvailable();
  const idMatch = url.match(/\/(?:pull|merge_requests)\/(\d+)/i);
  const id = idMatch ? idMatch[1] : '?';
  const linkTitle = `${repoShortName()} #${id}: ${title}`;
  const argv = [
    LINK_SCRIPT,
    'link',
    '--issue',
    issue,
    '--url',
    url,
    '--title',
    linkTitle,
    '--host',
    host,
  ];
  const passthrough = [
    ['assignee', '--assignee'],
    ['team-id', '--team-id'],
    ['team-name', '--team-name'],
    ['board-id', '--board-id'],
    ['story-points', '--story-points'],
    ['priority', '--priority'],
  ];
  for (const [key, flag] of passthrough) {
    if (linkArgs[key]) {
      argv.push(flag, String(linkArgs[key]));
    }
  }
  if (linkArgs.noDefaults) {
    argv.push('--no-defaults');
  }
  if (linkArgs.noComment) {
    argv.push('--no-comment');
  }
  const r = run(process.execPath, argv);
  process.stdout.write(r.stdout);
  if (r.stderr) {
    process.stderr.write(r.stderr);
  }
  if (r.status !== 0) {
    throw new Error(`link-pr-mr.js failed: ${r.combined}`);
  }
  return r.stdout.trim() || 'linked';
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const issue = args.issue;
  const title = args.title;
  if (!issue || !title) {
    console.error('[ERROR] --issue and --title are required');
    usage(1);
  }

  const host = detectHost(args.host);
  const target = args.target || args.base || '';
  const remoteUrl = originRemoteUrl();
  const appendJiraRef = shouldAppendJiraRef({
    noJiraRef: Boolean(args.noJiraRef),
    remoteUrl,
  });
  const body = ensureBody(args.body || args.description || '', issue, { appendJiraRef });

  if (!args.noPush) {
    console.log(`[INFO] git push -u origin HEAD`);
    const push = run('git', ['push', '-u', 'origin', 'HEAD']);
    if (push.status !== 0) {
      throw new Error(`git push failed: ${push.combined}`);
    }
    if (push.combined) {
      console.log(push.combined);
    }
  }

  console.log(`[INFO] creating ${host === 'github' ? 'PR' : 'MR'} on ${host}`);
  const created =
    host === 'github'
      ? createGithub({ title, body, target, draft: args.draft })
      : createGitlab({ title, body, target, draft: args.draft });

  console.log(`[INFO] created: ${created.url}`);

  let jiraLink = 'skipped';
  if (!args.noLink) {
    linkJira({
      issue,
      url: created.url,
      title,
      host,
      linkArgs: args,
    });
    jiraLink = 'done';
  }

  const diffs = diffsUrl(created.url, host);
  if (!args.noOpen) {
    try {
      openBrowser(diffs);
      console.log(`[INFO] opened diffs: ${diffs}`);
    } catch (err) {
      console.warn(`[WARN] could not open browser: ${err.message}`);
      console.log(`[INFO] diffs: ${diffs}`);
    }
  } else {
    console.log(`[INFO] diffs: ${diffs}`);
  }

  console.log('---');
  console.log(`url: ${created.url}`);
  console.log(`diffs: ${diffs}`);
  console.log(`browserOpened: ${args.noOpen ? 'false' : 'true'}`);
  console.log(`issue: ${issue}`);
  console.log(`host: ${host}`);
  console.log(`jiraLink: ${jiraLink}`);
  console.log(`jiraRef: ${appendJiraRef ? 'appended' : 'skipped'}`);
}

try {
  main();
} catch (err) {
  console.error(`[ERROR] ${err.message}`);
  process.exit(1);
}
