import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const git = args => execFileSync('git', ['-C', root, ...args], { encoding: 'utf8' });
const ignore = fs.readFileSync(path.join(root, '.gitignore'), 'utf8');
const block = ignore.split('# BEGIN reviewed Engineering OS package')[1]?.split('# END reviewed Engineering OS package')[0];
const files = block?.split(/\r?\n/).filter(l => l.startsWith('!/') && !l.endsWith('/')).map(l => l.slice(2)) || [];
test('package is an explicit file allowlist and every file exists in Git index', () => {
  assert.equal(files.length, 24);
  const indexed = new Set(git(['ls-files', '-z']).split('\0'));
  for (const f of files) {
    assert.ok(fs.statSync(path.join(root, f)).isFile(), f);
    assert.ok(indexed.has(f), 'not staged/tracked: ' + f);
  }
});
test('machine config, activation settings and generated state stay ignored', () => {
  const privatePaths = ['.claude/settings.json', '.claude/settings.local.json', '.claude/.credentials.json', '.claude/session.log', '.claude/cache/x', '.claude/agents/unrelated.md', '.claude/skills/unrelated/SKILL.md', '.claude/orchestration/ACTIVE_RUN', '.claude/orchestration/approvals/x.json', '.claude/orchestration/runs/x/ledger.json', '.claude/orchestration/hook-debug.log'];
  for (const p of privatePaths) {
    assert.equal(spawnSync('git', ['-C', root, 'check-ignore', '--no-index', '-q', p]).status, 0, p);
  }
  assert.ok(!files.some(p => /settings|credentials|ACTIVE_RUN|\/runs\/|\/approvals\//.test(p)));
});
test('runtime static imports resolve within packaged files', () => {
  for (const f of files.filter(f => f.endsWith('.mjs'))) {
    const text = fs.readFileSync(path.join(root, f), 'utf8');
    for (const m of text.matchAll(/from\s+['"](\.[^'"]+)['"]/g)) {
      assert.ok(fs.existsSync(path.resolve(root, path.dirname(f), m[1])), f + ': ' + m[1]);
    }
  }
});
test('governance skill references resolve without local Claude skill copies', () => {
  for (const f of files.filter(f => f.endsWith('SKILL.md'))) {
    const text = fs.readFileSync(path.join(root, f), 'utf8');
    assert.match(text, /^name:\s*\S+/m);
    assert.match(text, /^description:\s*\S+/m);
    for (const m of text.matchAll(/(?:\.agent|\.claude)\/(?:skills\/[a-z0-9-]+\/SKILL\.md|references\/[a-z0-9-]+\.md)/g)) {
      assert.ok(fs.existsSync(path.join(root, m[0])), f + ': ' + m[0]);
    }
  }
  assert.ok(fs.existsSync(path.join(root, '.claude/references/definition-of-done.md')));
  for (const p of ['.agent/references/definition-of-done.md', '.agent/references/security-checklist.md']) {
    assert.ok(fs.existsSync(path.join(root, p)), p);
  }
  for (const name of ['planning-and-task-breakdown', 'security-and-hardening']) {
    const p = path.join(root, '.agent/skills', name, 'SKILL.md');
    for (const m of fs.readFileSync(p, 'utf8').matchAll(/\.\.\/\.\.\/references\/[a-z0-9-]+\.md/g)) {
      assert.ok(fs.existsSync(path.resolve(path.dirname(p), m[0])), name + ': ' + m[0]);
    }
  }
});
