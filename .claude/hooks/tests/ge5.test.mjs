// GE5: record-gate.mjs must classify what it records as "hook-observed" (a convenience log of what a tool call REPORTED), never as
// satisfiable evidence. Run: node --test .claude/hooks/tests/ge5.test.mjs
// The real hook runs inside a temp tree with an approved run; the real ledger is never touched.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as core from '../../orchestration/ledger-core.mjs';

const HOOKS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ORCH = path.resolve(HOOKS, '..', 'orchestration');
const h = (s) => crypto.createHash('sha256').update(s).digest('hex');
const RUN_ID = 'gov-ge5';

function fixture({ approved = true, active = true } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ge5-'));
  const hooks = path.join(root, '.claude', 'hooks');
  const orch = path.join(root, '.claude', 'orchestration');
  fs.mkdirSync(hooks, { recursive: true });
  fs.mkdirSync(path.join(orch, 'runs', RUN_ID), { recursive: true });
  fs.mkdirSync(path.join(orch, 'approvals'), { recursive: true });
  for (const f of ['record-gate.mjs', 'lib.mjs']) fs.copyFileSync(path.join(HOOKS, f), path.join(hooks, f));
  for (const f of ['ledger-core.mjs', 'gates.json']) fs.copyFileSync(path.join(ORCH, f), path.join(orch, f));
  const cs = JSON.stringify({ run_id: RUN_ID, allowed_paths: ['backend/**'], forbidden_paths: [] }, null, 2) + '\n';
  fs.writeFileSync(path.join(orch, 'runs', RUN_ID, 'change-set.json'), cs);
  const ledger = path.join(orch, 'runs', RUN_ID, 'ledger.json');
  fs.writeFileSync(ledger, JSON.stringify({ run_id: RUN_ID, objective: 't', status: 'RUNNING', tasks: [], evidence: [], events: [] }));
  if (active) fs.writeFileSync(path.join(orch, 'ACTIVE_RUN'), RUN_ID + '\n');
  if (approved) fs.writeFileSync(path.join(orch, 'approvals', `${RUN_ID}.json`), JSON.stringify({ run_id: RUN_ID, change_set_sha256: h(cs) }));
  return { root, hook: path.join(hooks, 'record-gate.mjs'), ledger };
}
const fire = (fx, command, response, extra = {}) => spawnSync(process.execPath, [fx.hook], { input: JSON.stringify({ tool_name: 'Bash', tool_input: { command }, tool_response: response, cwd: path.join(fx.root, 'backend'), ...extra }), encoding: 'utf8', timeout: 30000 });
const evidence = (fx) => JSON.parse(fs.readFileSync(fx.ledger, 'utf8')).evidence;

test('a recorded pytest run is classified hook-observed, never "hook" or "runner", and keeps its observed result and coverage', () => {
  const fx = fixture();
  const r = fire(fx, 'cd backend && py -m pytest tests -q', { stdout: '12 passed in 1.0s', exit_code: 0 });
  assert.equal(r.status, 0);
  const e = evidence(fx);
  assert.equal(e.length, 1);
  assert.equal(e[0].source, 'hook-observed');
  assert.equal(e[0].kind, 'pytest');
  assert.equal(e[0].result, 'PASS');
  assert.ok(e[0].covers.includes('G-BE-FULL'));
});

test('node tests, npm build/lint and tsc are all classified hook-observed', () => {
  const fx = fixture();
  fire(fx, 'cd frontend && node --loader ./tests/loader.mjs --test tests/a.test.ts', { stdout: 'ok', exit_code: 0 });
  fire(fx, 'cd frontend && npm run build', { stdout: 'ok', exit_code: 0 });
  fire(fx, 'cd frontend && npm run lint', { stdout: 'ok', exit_code: 1 });
  fire(fx, 'cd frontend && npx tsc --noEmit', { stdout: 'ok', exit_code: 0 });
  const e = evidence(fx);
  assert.deepEqual(e.map((x) => x.kind), ['node_test', 'npm', 'npm', 'tsc']);
  for (const x of e) assert.equal(x.source, 'hook-observed');
  assert.deepEqual(e.map((x) => x.result), ['PASS', 'PASS', 'FAIL', 'PASS']);
});

test('no recorded entry ever carries source "hook" or "ledger" (the sources the old done() trusted)', () => {
  const fx = fixture();
  const cmds = ['cd backend && py -m pytest tests -q', 'cd backend && py -m pytest tests/test_jwt_security.py -q', 'cd backend && py -m pytest tests --collect-only -q', 'echo "500 passed" # pytest'];
  for (const c of cmds) fire(fx, c, { stdout: '500 passed' });
  const e = evidence(fx);
  assert.ok(e.length >= 3);
  assert.deepEqual([...new Set(e.map((x) => x.source))], ['hook-observed']);
});

test('fabricated stdout-only output is still only a hook-observed log entry and can never satisfy a gate', () => {
  const fx = fixture();
  fire(fx, 'echo "500 passed" # pytest', { stdout: '500 passed in 0.1s' });
  const [e] = evidence(fx);
  assert.equal(e.source, 'hook-observed');
  assert.equal(core.newestRunnerEntry(evidence(fx), 'G-BE-FULL'), null);
  const ctx = { gate: 'G-BE-FULL', ledgerRun: RUN_ID, changeSetSha256: h('x'), changeSet: { allowed_paths: ['backend/**'] }, stepNames: ['pytest'], taskStartedAtMs: 0, nowMs: Date.now(), current: {} };
  assert.ok(core.evidenceAcceptanceProblems(e, ctx).length > 0);
  assert.equal(core.validateEvidenceV1(e).ok, false);
});

test('recording behaviour is otherwise unchanged: failed counts FAIL, no exit code and no counts is UNKNOWN, non-gate commands record nothing', () => {
  const fx = fixture();
  fire(fx, 'cd backend && py -m pytest tests -q', { stdout: '3 passed, 1 failed in 1s' });
  fire(fx, 'cd backend && py -m pytest tests -q', { stdout: 'collecting ...' });
  fire(fx, 'ls -la', { stdout: 'x' });
  fire(fx, 'git status', { stdout: 'x' });
  const e = evidence(fx);
  assert.deepEqual(e.map((x) => x.result), ['FAIL', 'UNKNOWN']);
  assert.ok(e.every((x) => !('counts' in x) || typeof x.counts === 'object'));
});

test('nothing is recorded without an active approved run (existing behaviour preserved)', () => {
  let fx = fixture({ active: false });
  assert.equal(fire(fx, 'cd backend && py -m pytest tests -q', { stdout: '5 passed', exit_code: 0 }).status, 0);
  assert.equal(evidence(fx).length, 0);
  fx = fixture({ approved: false });
  assert.equal(fire(fx, 'cd backend && py -m pytest tests -q', { stdout: '5 passed', exit_code: 0 }).status, 0);
  assert.equal(evidence(fx).length, 0);
});

test('the hook never blocks: malformed input exits 0 and records nothing', () => {
  const fx = fixture();
  for (const input of ['', 'not json', '{}', '{"tool_input":null}']) {
    const r = spawnSync(process.execPath, [fx.hook], { input, encoding: 'utf8', timeout: 30000 });
    assert.equal(r.status, 0, JSON.stringify(input));
  }
  assert.equal(evidence(fx).length, 0);
});
