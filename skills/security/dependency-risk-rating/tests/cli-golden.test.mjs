// Golden-file tests for the two scripts whose stdout is a contract: the
// lockfile comparison that feeds everything downstream, and the scorer's
// rendered report. Offline — no fixture here reaches the network.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { execFileSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const testsDir = path.dirname(fileURLToPath(import.meta.url));
const skillDir = path.join(testsDir, '..');
const fixture = (name) => path.join(testsDir, 'fixtures', name);
const expected = (name) => fs.readFileSync(path.join(testsDir, 'expected', name), 'utf8');

const run = (script, args) =>
  execFileSync(process.execPath, [path.join(skillDir, 'scripts', script), ...args], {
    encoding: 'utf8',
    // A fixture run must never reach out; fail loudly instead of hanging.
    timeout: 60_000,
  });

describe('compare-manifests', () => {
  it('diffs a yarn v1 lock alongside its package.json', () => {
    const out = run('compare-manifests.ts', [
      '--old-lock', fixture('yarn-v1-old.lock'),
      '--new-lock', fixture('yarn-v1-new.lock'),
      '--old-pkg', fixture('package-old.json'),
      '--new-pkg', fixture('package-new.json'),
    ]);
    assert.equal(out, expected('yarn-v1.json'));
  });

  it('diffs a yarn berry lock', () => {
    const out = run('compare-manifests.ts', [
      '--old-lock', fixture('yarn-berry-old.lock'),
      '--new-lock', fixture('yarn-berry-new.lock'),
    ]);
    assert.equal(out, expected('yarn-berry.json'));
  });

  it('diffs a package-lock v3', () => {
    const out = run('compare-manifests.ts', [
      '--old-lock', fixture('package-lock-old.json'),
      '--new-lock', fixture('package-lock-new.json'),
    ]);
    assert.equal(out, expected('package-lock.json'));
  });

  it('diffs package.json alone when no lockfile changed', () => {
    const out = run('compare-manifests.ts', [
      '--old-pkg', fixture('package-old.json'),
      '--new-pkg', fixture('package-new.json'),
    ]);
    assert.equal(out, expected('package-json-only.json'));
  });
});

describe('score', () => {
  const args = ['--metrics', fixture('metrics-basic.json'), '--judgments', fixture('judgments-basic.json')];

  it('renders the JSON result', () => {
    assert.equal(run('score.ts', args), expected('score-basic.json'));
  });

  it('renders the markdown report used verbatim in the report', () => {
    assert.equal(run('score.ts', [...args, '--format', 'md']), expected('score-basic.md'));
  });
});
