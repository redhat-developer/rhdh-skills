import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { describe, it } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { buildLinkCommentAdf } = require('../scripts/link-pr-mr.js');

import {
  buildBulkMovePayload,
  collectAdjustedFieldLines,
  detectHost,
  displayTitleFromLinkTitle,
  mergeDefaultsLayers,
  missingDefaultKeys,
  parseArgs,
  parseEmailToken,
  parsePrMrUrl,
  resolveJiraAuth,
  shouldAppendJiraRef,
  shouldMoveRhdhplanDeliveryIssue,
  shouldSkipTeamAndSprint,
  stripMergedPrefix,
  withMergedPrefix,
  classifyPrMrState,
  prefixForPrMrState,
  withClosedPrefix,
} from '../scripts/lib.js';

describe('detectHost', () => {
  it('honors explicit host', () => {
    assert.equal(detectHost('https://example.com', 'github'), 'github');
    assert.equal(detectHost('https://github.com/a/b/pull/1', 'gitlab'), 'gitlab');
  });
  it('infers github vs gitlab from URL', () => {
    assert.equal(detectHost('https://github.com/org/repo/pull/1'), 'github');
    assert.equal(
      detectHost('https://gitlab.cee.redhat.com/rhidp/rhdh/-/merge_requests/9'),
      'gitlab',
    );
  });
});

describe('title helpers', () => {
  it('strips and adds merged prefix', () => {
    assert.equal(stripMergedPrefix('[x] merged: repo #1: fix'), 'repo #1: fix');
    assert.equal(withMergedPrefix('repo #1: fix'), '[x] merged: repo #1: fix');
    assert.equal(
      withMergedPrefix('[x] merged: repo #1: fix'),
      '[x] merged: repo #1: fix',
    );
  });
  it('strips and adds closed prefix', () => {
    assert.equal(stripMergedPrefix('[!] closed: repo #1: fix'), 'repo #1: fix');
    assert.equal(withClosedPrefix('repo #1: fix'), '[!] closed: repo #1: fix');
    assert.equal(
      withClosedPrefix('[!] closed: repo #1: fix'),
      '[!] closed: repo #1: fix',
    );
  });
  it('swaps closed and merged prefixes', () => {
    assert.equal(
      withMergedPrefix('[!] closed: repo #1: fix'),
      '[x] merged: repo #1: fix',
    );
    assert.equal(
      withClosedPrefix('[x] merged: repo #1: fix'),
      '[!] closed: repo #1: fix',
    );
  });
  it('displayTitleFromLinkTitle drops repo#N prefix', () => {
    assert.equal(
      displayTitleFromLinkTitle('rhdh #12: fix: widget'),
      'fix: widget',
    );
    assert.equal(
      displayTitleFromLinkTitle('[!] closed: rhdh #12: fix: widget'),
      'fix: widget',
    );
  });
});

describe('classifyPrMrState', () => {
  it('treats GitHub merged+closed as merged', () => {
    assert.equal(classifyPrMrState({ merged: true, state: 'closed' }), 'merged');
    assert.equal(classifyPrMrState({ merged: 'true', state: 'closed' }), 'merged');
  });
  it('treats closed unmerged as closed', () => {
    assert.equal(classifyPrMrState({ merged: false, state: 'closed' }), 'closed');
    assert.equal(classifyPrMrState({ state: 'closed' }), 'closed');
  });
  it('treats GitLab merged_at / state=merged as merged', () => {
    assert.equal(classifyPrMrState({ mergedAt: '2026-01-01T00:00:00Z' }), 'merged');
    assert.equal(classifyPrMrState({ state: 'merged' }), 'merged');
  });
  it('treats opened as open', () => {
    assert.equal(classifyPrMrState({ merged: false, state: 'open' }), 'open');
    assert.equal(classifyPrMrState({ state: 'opened' }), 'open');
    assert.equal(classifyPrMrState({}), 'open');
  });
  it('prefixForPrMrState maps merged and closed', () => {
    assert.equal(prefixForPrMrState('merged', 'repo #1: fix'), '[x] merged: repo #1: fix');
    assert.equal(prefixForPrMrState('closed', 'repo #1: fix'), '[!] closed: repo #1: fix');
    assert.equal(prefixForPrMrState('open', 'repo #1: fix'), 'repo #1: fix');
  });
});

describe('collectAdjustedFieldLines', () => {
  it('only includes newly set fields and transitions', () => {
    const lines = collectAdjustedFieldLines(
      {
        storyPoints: 'set 1',
        team: 'kept Cope',
        priority: 'set Normal',
      },
      'transitioned To Do → In Progress',
    );
    assert.deepEqual(lines, [
      'Story points: 1',
      'Priority: Normal',
      'Status: In Progress',
    ]);
  });
});

describe('mergeDefaultsLayers / missingDefaultKeys', () => {
  it('lets config beat jira-cli hints; CLI wins overall', () => {
    const merged = mergeDefaultsLayers({
      fromJiraCli: { boardId: 1, assigneeEmail: 'cli@example.com' },
      fromFile: { boardId: 2, teamId: 't', teamName: 'T', storyPoints: 1 },
      fromEnv: { priorityName: 'Normal' },
      fromCli: { boardId: 3 },
    });
    assert.equal(merged.boardId, 3);
    assert.equal(merged.assigneeEmail, 'cli@example.com');
    assert.equal(merged.teamId, 't');
    assert.equal(merged.priorityName, 'Normal');
  });
  it('reports incomplete defaults', () => {
    const missing = missingDefaultKeys({ boardId: 1, storyPoints: 1 });
    assert.ok(missing.includes('assigneeEmail'));
    assert.ok(missing.includes('teamId'));
  });
  it('NONE team skips team/sprint required keys', () => {
    assert.equal(shouldSkipTeamAndSprint({ teamName: 'NONE' }), true);
    assert.equal(shouldSkipTeamAndSprint({ teamId: 'none' }), true);
    assert.equal(shouldSkipTeamAndSprint({ teamName: 'RHDH Cope' }), false);
    const missing = missingDefaultKeys({
      assigneeEmail: 'a@b.com',
      teamName: 'NONE',
      storyPoints: 1,
      priorityName: 'Normal',
      storyPointsField: 'customfield_10028',
    });
    assert.deepEqual(missing, []);
  });
});

describe('shouldMoveRhdhplanDeliveryIssue', () => {
  it('moves only RHDHPLAN Epic/Story/Task', () => {
    assert.equal(shouldMoveRhdhplanDeliveryIssue('RHDHPLAN', 'Epic'), true);
    assert.equal(shouldMoveRhdhplanDeliveryIssue('RHDHPLAN', 'Story'), true);
    assert.equal(shouldMoveRhdhplanDeliveryIssue('RHDHPLAN', 'Task'), true);
    assert.equal(shouldMoveRhdhplanDeliveryIssue('RHDHPLAN', 'Feature'), false);
    assert.equal(shouldMoveRhdhplanDeliveryIssue('RHIDP', 'Story'), false);
  });
});

describe('buildBulkMovePayload', () => {
  it('targets RHIDP with issue type id', () => {
    assert.deepEqual(buildBulkMovePayload('RHDHPLAN-9', 'RHIDP', '10009'), {
      sendBulkNotification: false,
      targetToSourcesMapping: {
        'RHIDP,10009': {
          inferClassificationDefaults: true,
          inferFieldDefaults: true,
          inferStatusDefaults: true,
          inferSubtaskTypeDefault: true,
          issueIdsOrKeys: ['RHDHPLAN-9'],
        },
      },
    });
  });
});

describe('shouldAppendJiraRef', () => {
  it('skips community-plugins and --no-jira-ref', () => {
    assert.equal(shouldAppendJiraRef({}), true);
    assert.equal(shouldAppendJiraRef({ noJiraRef: true }), false);
    assert.equal(
      shouldAppendJiraRef({
        remoteUrl: 'git@github.com:backstage/community-plugins.git',
      }),
      false,
    );
  });
});

describe('parsePrMrUrl', () => {
  it('parses github and gitlab URLs', () => {
    assert.deepEqual(
      parsePrMrUrl('https://github.com/redhat-developer/rhdh/pull/42'),
      { kind: 'github', owner: 'redhat-developer', repo: 'rhdh', id: '42' },
    );
    assert.deepEqual(
      parsePrMrUrl(
        'https://gitlab.cee.redhat.com/rhidp/rhdh-plugin-catalog/-/merge_requests/817',
      ),
      {
        kind: 'gitlab',
        host: 'gitlab.cee.redhat.com',
        project: 'rhidp/rhdh-plugin-catalog',
        id: '817',
      },
    );
  });
});

describe('parseArgs', () => {
  it('maps boolean flags to camelCase and keeps valued flags', () => {
    const args = parseArgs(
      ['link', '--no-defaults', '--issue', 'RHIDP-1', '--title', 't'],
      { booleanFlags: ['no-defaults', 'no-comment'] },
    );
    assert.equal(args.noDefaults, true);
    assert.equal(args.issue, 'RHIDP-1');
    assert.equal(args.title, 't');
    assert.deepEqual(args._, ['link']);
  });
});

describe('parseEmailToken / resolveJiraAuth', () => {
  it('parses email:token', () => {
    assert.deepEqual(parseEmailToken('a@b.com:secret'), {
      login: 'a@b.com',
      token: 'secret',
    });
  });

  it('reads .jira-token when env token missing', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jira-pr-mr-'));
    const tokenPath = path.join(dir, '.jira-token');
    const cfgPath = path.join(dir, 'missing.yml');
    fs.writeFileSync(tokenPath, 'user@example.com:tok-123\n');
    const auth = resolveJiraAuth({
      env: {},
      jiraConfigPath: cfgPath,
      tokenFilePath: tokenPath,
    });
    assert.equal(auth.login, 'user@example.com');
    assert.equal(auth.token, 'tok-123');
    assert.equal(auth.server, 'https://redhat.atlassian.net');
  });

  it('prefers go-jira login + JIRA_API_TOKEN', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jira-pr-mr-'));
    const cfgPath = path.join(dir, '.config.yml');
    fs.writeFileSync(
      cfgPath,
      ['login: from-file@example.com', 'server: https://example.atlassian.net', ''].join(
        '\n',
      ),
    );
    const auth = resolveJiraAuth({
      env: { JIRA_API_TOKEN: 'bare-token' },
      jiraConfigPath: cfgPath,
      tokenFilePath: path.join(dir, 'nope'),
    });
    assert.equal(auth.login, 'from-file@example.com');
    assert.equal(auth.token, 'bare-token');
    assert.equal(auth.server, 'https://example.atlassian.net');
  });
});

describe('buildLinkCommentAdf', () => {
  const githubUrl = 'https://github.com/org/repo/pull/123';
  const gitlabUrl = 'https://gitlab.cee.redhat.com/group/repo/-/merge_requests/817';

  function firstParagraphText(doc) {
    const nodes = doc.content[0].content;
    return nodes.map((n) => n.text).join('');
  }

  it('uses PR: <url> for GitHub', () => {
    const doc = buildLinkCommentAdf({ url: githubUrl, host: 'github' });
    assert.equal(firstParagraphText(doc), `PR: ${githubUrl}`);
    assert.equal(doc.content[0].content[1].marks[0].attrs.href, githubUrl);
    assert.equal(doc.content.length, 1);
  });

  it('uses MR: <url> for GitLab', () => {
    const doc = buildLinkCommentAdf({ url: gitlabUrl });
    assert.equal(firstParagraphText(doc), `MR: ${gitlabUrl}`);
  });

  it('appends Adjusted fields when defaults were newly set', () => {
    const doc = buildLinkCommentAdf({
      url: githubUrl,
      host: 'github',
      status: 'transitioned To Do → In Progress',
      defaults: { priority: 'set Normal' },
    });
    assert.equal(doc.content[1].content[0].text, 'Adjusted fields:');
  });
});
