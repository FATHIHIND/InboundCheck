// GE3: gates.json runner blocks. Run: node --test .claude/orchestration/tests/ge3.test.mjs
// Reads the real .claude/orchestration/gates.json and checks it against the approved design: a runner block for every CONFIGURED and
// EXECUTABLE autonomous gate, a two-step G-SCOPE, a conditional G-BE-FULL harness block, BLOCKED / NOT-CONFIGURED gates untouched.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as core from '../ledger-core.mjs';
import * as rg from '../run-gate.mjs';

const ORCH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const cfg = JSON.parse(fs.readFileSync(path.join(ORCH, 'gates.json'), 'utf8'));
const by = Object.fromEntries(cfg.gates.map((g) => [g.id, g]));

const RUNNABLE = ['G-BE-COLLECT', 'G-BE-FULL', 'G-AUTH-JWT', 'G-WEBHOOKS', 'G-BILLING', 'G-ABUSE', 'G-WORKER', 'G-MIGRATION-STATIC', 'G-SCAN', 'G-SCOPE', 'G-FE-UNIT'];
// gate id -> [autonomy, status] that must stay exactly as before (no runner block)
const UNTOUCHED = {
  'G-FE-TYPES': ['approval', 'BLOCKED'], 'G-FE-LINT': ['approval', 'BLOCKED'], 'G-FE-BUILD': ['approval', 'BLOCKED'], 'G-DOCKER': ['approval', 'BLOCKED'],
  'G-BE-LINT': ['n/a', 'NOT-CONFIGURED'], 'G-REVIEW-CODE': ['autonomous', 'CONFIGURED'], 'G-REVIEW-SEC': ['autonomous', 'CONFIGURED'], 'G-REVIEW-TEST': ['autonomous', 'CONFIGURED'],
};

test('every runnable gate has a valid runner block and is autonomous and CONFIGURED or EXECUTABLE', () => {
  for (const id of RUNNABLE) {
    const g = by[id];
    assert.ok(g, `${id} exists`);
    assert.equal(g.autonomy, 'autonomous', id);
    assert.ok(['CONFIGURED', 'EXECUTABLE'].includes(g.status), `${id} status ${g.status}`);
    assert.deepEqual(rg.validateRunnerBlock(g), [], id);
    assert.ok(core.runnerStepNames(g), id);
  }
});

test('completeness: no autonomous CONFIGURED/EXECUTABLE non-review gate is missing a runner block, and no other gate has one', () => {
  const expectBlock = cfg.gates.filter((g) => g.autonomy === 'autonomous' && ['CONFIGURED', 'EXECUTABLE'].includes(g.status) && !(g.match && g.match.kind === 'agent')).map((g) => g.id).sort();
  assert.deepEqual(expectBlock, [...RUNNABLE].sort());
  for (const g of cfg.gates) assert.equal(Boolean(g.runner), RUNNABLE.includes(g.id), g.id);
});

test('BLOCKED, NOT-CONFIGURED and review gates are unchanged: same autonomy and status, no runner block', () => {
  for (const [id, [autonomy, status]] of Object.entries(UNTOUCHED)) {
    assert.ok(by[id], id);
    assert.equal(by[id].autonomy, autonomy, id);
    assert.equal(by[id].status, status, id);
    assert.equal(by[id].runner, undefined, id);
  }
  assert.equal(cfg.gates.length, RUNNABLE.length + Object.keys(UNTOUCHED).length, 'no gate was added or removed');
});

test('risk requirements are unchanged and every gate they require can be satisfied by the runner', () => {
  assert.deepEqual(cfg.risk_requirements, {
    LOW: { gates: ['G-SCOPE', 'G-SCAN', 'G-BE-COLLECT'], reviews: [] },
    MEDIUM: { gates: ['G-SCOPE', 'G-SCAN', 'G-BE-FULL'], reviews: ['code-reviewer'] },
    HIGH: { gates: ['G-SCOPE', 'G-SCAN', 'G-BE-FULL'], reviews: ['code-reviewer', 'security-auditor', 'test-engineer'] },
  });
  for (const r of Object.values(cfg.risk_requirements)) for (const gid of r.gates) assert.ok(RUNNABLE.includes(gid), gid);
});

test('pytest gates: the runner block matches the documented command (cwd backend, same arguments) and pins the approved Python 3.12 launcher', () => {
  const PYTEST_GATES = ['G-BE-COLLECT', 'G-BE-FULL', 'G-AUTH-JWT', 'G-WEBHOOKS', 'G-BILLING', 'G-ABUSE', 'G-WORKER'];
  for (const id of PYTEST_GATES) {
    const g = by[id];
    const m = /^cd backend && py -m pytest (.+)$/.exec(g.command);
    assert.ok(m, `${id} command shape`);
    assert.equal(g.runner.steps.length, 1, id);
    const s = g.runner.steps[0];
    assert.equal(s.kind, 'pytest', id); assert.equal(s.name, 'pytest', id); assert.equal(s.cwd, 'backend', id);
    assert.deepEqual(s.argv_tail, m[1].split(/\s+/), id);
    assert.deepEqual(s.launcher, ['py', '-3.12'], id); // selects the approved 3.12 without touching any global Windows setting
    assert.equal(s.python_args, undefined, id);
    assert.equal(s.collect_only === true, id === 'G-BE-COLLECT', id);
  }
});

test('G-BE-FULL: conditional harness block per design (diff globs, runner-set variables, required cell manifest, longer timeout)', () => {
  const c = by['G-BE-FULL'].runner.conditional;
  assert.deepEqual(c.when_diff_matches, ['supabase/migrations/**', 'supabase/tests/pr_sec_01/**', 'backend/tests/test_pr_sec_01_db_harness.py']);
  assert.deepEqual(c.env, { PR_SEC_01_DB_HARNESS: '1', PR_SEC_01_REQUIRE_HARNESS: '1' });
  assert.equal(c.required_testcase_manifest, 'supabase/tests/pr_sec_01/cells.json');
  assert.equal(c.timeout_s, 3600);
  assert.equal(by['G-BE-FULL'].runner.steps[0].timeout_s, 1800);
  for (const id of RUNNABLE) if (id !== 'G-BE-FULL') assert.equal(by[id].runner.conditional, undefined, id);
});

test('G-SCOPE is a two-step gate: scope-check, then the conditional manifest-scope builtin', () => {
  const s = by['G-SCOPE'].runner.steps;
  assert.deepEqual(s.map((x) => x.name), ['scope-check', 'manifest-scope']);
  assert.deepEqual(s[0], { name: 'scope-check', kind: 'script', cwd: '.', argv: ['node', '.claude/orchestration/ledger.mjs', 'scope-check'], timeout_s: 60 });
  assert.deepEqual(s[1], { name: 'manifest-scope', kind: 'builtin', builtin: 'manifest-scope' });
});

test('G-SCAN and G-MIGRATION-STATIC run the scanner as a node script; G-MIGRATION-STATIC runs it before the ledger-reconciliation test', () => {
  // G-SCAN is two-step: the git-visible diff scan, then manifest-scan, which scans the governance files that differ from the human baseline
  // (scan.mjs --changed is blind to the gitignored .claude/ and reported "0 file(s) checked" for a governance run).
  assert.deepEqual(by['G-SCAN'].runner.steps, [
    { name: 'scan', kind: 'script', cwd: '.', argv: ['node', '.claude/orchestration/scan.mjs', '--changed'], timeout_s: 300 },
    { name: 'manifest-scan', kind: 'builtin', builtin: 'manifest-scan' },
  ]);
  assert.deepEqual(core.runnerStepNames(by['G-SCAN']), ['scan', 'manifest-scan']);
  const m = by['G-MIGRATION-STATIC'].runner.steps;
  assert.deepEqual(m.map((x) => [x.name, x.kind]), [['scan', 'script'], ['pytest', 'pytest']]);
  assert.deepEqual(m[0].argv, ['node', '.claude/orchestration/scan.mjs', '--changed']);
  assert.deepEqual(m[1].argv_tail, ['tests/test_migration_ledger_reconciliation.py', '-q']);
  assert.deepEqual(m[1].launcher, ['py', '-3.12']);
});

test('G-FE-UNIT runs the documented node:test command from frontend/', () => {
  const s = by['G-FE-UNIT'].runner.steps;
  assert.equal(s.length, 1);
  assert.equal(s[0].kind, 'script'); assert.equal(s[0].cwd, 'frontend');
  assert.equal(`cd frontend && ${s[0].argv.join(' ')}`, by['G-FE-UNIT'].command);
});

test('the runner step names and kinds that done() will require are stable and unique per gate', () => {
  for (const id of RUNNABLE) {
    const names = core.runnerStepNames(by[id]);
    assert.equal(new Set(names).size, names.length, id);
  }
  assert.deepEqual(core.runnerStepNames(by['G-SCOPE']), ['scope-check', 'manifest-scope']);
  assert.deepEqual(core.runnerStepNames(by['G-BE-FULL']), ['pytest']);
});

test('existing consumers keep working: record-gate fields (match, pytest_targets, command) are untouched for every gate', () => {
  for (const id of RUNNABLE) {
    assert.equal(typeof by[id].command, 'string', id);
    assert.ok(by[id].match && by[id].match.kind, id);
  }
  assert.deepEqual(by['G-BE-FULL'].pytest_targets, ['tests']);
  assert.deepEqual(by['G-BE-COLLECT'].match, { kind: 'pytest', flags_any: ['--collect-only'] });
});
