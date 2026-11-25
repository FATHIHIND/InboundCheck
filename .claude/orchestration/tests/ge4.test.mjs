// GE4: ledger.mjs done() verifies runner evidence; computeRisk raises .claude/ files to HIGH; status shows trust state.
// Run: node --test .claude/orchestration/tests/ge4.test.mjs
// End-to-end: the real ledger.mjs and run-gate.mjs run inside isolated temp git trees (see fixtures/gate-fixture.mjs). The real ledger is never touched.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { makeFixture, defaultGates, runGate, runLedger, fireHook, evidence, last, readLedger, put, cleanup } from './fixtures/gate-fixture.mjs';

after(cleanup);

function gates4() {
  const g = defaultGates();
  g.risk_requirements = {
    LOW: { gates: ['G-SCR'], reviews: [] },
    MEDIUM: { gates: ['G-SCR', 'G-PYT'], reviews: ['code-reviewer'] },
    HIGH: { gates: ['G-SCR', 'G-PYT'], reviews: ['code-reviewer', 'security-auditor', 'test-engineer'] },
  };
  g.gates.push({ id: 'G-BLK', autonomy: 'approval', status: 'BLOCKED' });
  g.gates.push({ id: 'G-NORUN', autonomy: 'autonomous', status: 'CONFIGURED' });
  return g;
}
const CS = (extra = {}) => ({ run_id: 'gov-test', allowed_paths: ['backend/**', 'scripts/**', 'src/**', '.claude/orchestration/tests/**'], forbidden_paths: [], ...extra });
const fixture = (over = {}) => makeFixture({ gates: gates4(), changeSet: CS(), ...over });
function addStart(fx, id, files, risk = 'LOW', extra = []) {
  const r = runLedger(fx, ['add-task', '--id', id, '--title', 't', '--owner', 'main', '--files', files, '--risk', risk, ...extra]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(runLedger(fx, ['start', id]).status, 0);
  return r;
}
const done = (fx, id = 'T1') => runLedger(fx, ['done', id]);
const taskOf = (fx, id = 'T1') => readLedger(fx).tasks.find((t) => t.id === id);
const editLedger = (fx, fn) => { const l = readLedger(fx); fn(l); fs.writeFileSync(fx.ledger, JSON.stringify(l, null, 2)); };
const REVIEWERS = ['code-reviewer', 'security-auditor', 'test-engineer'];
const logAndReview = (fx, id = 'T1', agents = REVIEWERS) => {
  for (const a of agents) {
    fireHook(fx, 'subagent-log.mjs', { hook_event_name: 'SubagentStop', agent_type: a, agent_id: `a-${a}` });
    const r = runLedger(fx, ['review', id, '--agent', a, '--verdict', 'PASS', '--ref', 'x']);
    assert.equal(r.status, 0, r.stderr);
  }
};
const forgedFail = (e) => ({ ...e, result: 'FAIL', exit_status: 1, steps: e.steps.map((s) => (s.applicable === false ? s : { ...s, exit_status: 1 })), at: new Date(Date.parse(e.at) + 5000).toISOString() });

// ---------------------------------------------------------------- done() requires genuine runner evidence

test('done is refused without runner evidence and tells the operator which gate to run', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  const r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /gate G-SCR: no runner evidence/);
  assert.match(r.stderr, /run-gate\.mjs G-SCR/);
  assert.equal(taskOf(fx).status, 'IN_PROGRESS');
});

test('done is accepted from genuine, fresh, bound runner evidence', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  const r = done(fx);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /DONE \(verified from runner evidence\)/);
  assert.equal(taskOf(fx).status, 'DONE');
  assert.equal(taskOf(fx).final_risk, 'LOW');
});

test('legacy sources never satisfy a gate: orchestrator, hook-observed, and old "hook"/"ledger" entries are ignored', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runLedger(fx, ['evidence', '--gate', 'G-SCR', '--result', 'PASS', '--ref', 'trust me']).status, 0);
  fireHook(fx, 'record-gate.mjs', { tool_name: 'Bash', tool_input: { command: 'echo "500 passed" # pytest' }, tool_response: { stdout: '500 passed in 1s' } });
  const soon = new Date(Date.now() + 1000).toISOString();
  editLedger(fx, (l) => {
    l.evidence.push({ at: soon, source: 'hook', kind: 'script', covers: ['G-SCR'], result: 'PASS', exit_code: 0 });
    l.evidence.push({ at: soon, source: 'ledger', gate: 'G-SCR', covers: ['G-SCR'], result: 'PASS' });
  });
  const r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /no runner evidence/);
});

test('evidence goes stale after any edit to the tree and is accepted again after a re-run', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  put(fx.root, 'src/app.txt', 'edited after the gate ran\n');
  let r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /stale: tree_hash/);
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  r = done(fx);
  assert.equal(r.status, 0, r.stderr);
});

test('a newer FAIL entry revokes an older genuine PASS', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  editLedger(fx, (l) => l.evidence.push(forgedFail(l.evidence[0])));
  const r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /result is FAIL/);
});

test('evidence produced before the task started cannot complete it', () => {
  const fx = fixture();
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  addStart(fx, 'T1', 'src/app.txt');
  const r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /finished before the task started/);
});

test('an entry copied from another run is rejected (ledger_run binding)', () => {
  const a = fixture({ runId: 'run-a', changeSet: CS({ run_id: 'run-a' }) });
  assert.equal(runGate(a, 'G-SCR').status, 0);
  const stolen = last(a);
  const b = fixture({ runId: 'run-b', changeSet: CS({ run_id: 'run-b' }) });
  addStart(b, 'T1', 'src/app.txt');
  editLedger(b, (l) => l.evidence.push(stolen));
  const r = done(b);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /different run/);
});

test('an amended Change Set voids approval, so done is refused even with otherwise fresh evidence', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  fs.appendFileSync(path.join(fx.orch, 'runs', fx.runId, 'change-set.json'), ' ');
  const r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /not approved/);
});

test('a hand-forged duplicate key is not laundered by later ledger rewrites: the record stays tainted and done keeps refusing', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  const raw = fs.readFileSync(fx.ledger, 'utf8');
  const forged = raw.replace('"result": "PASS"', '"result": "FAIL", "result": "PASS"');
  assert.notEqual(forged, raw);
  fs.writeFileSync(fx.ledger, forged);
  fireHook(fx, 'subagent-log.mjs', { hook_event_name: 'SubagentStop', agent_type: 'Explore', agent_id: 'noise' }); // an ordinary hook rewrite
  for (let i = 0; i < 2; i++) {
    const r = done(fx);
    assert.equal(r.status, 1, `attempt ${i}`);
    assert.match(r.stderr, /malformed runner evidence/);
  }
  assert.equal(taskOf(fx).status, 'IN_PROGRESS');
});

test('a truncated ledger fails closed', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  const raw = fs.readFileSync(fx.ledger, 'utf8');
  fs.writeFileSync(fx.ledger, raw.slice(0, raw.length - 25));
  const r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /^ledger: /m);
  assert.equal(fs.readFileSync(fx.ledger, 'utf8'), raw.slice(0, raw.length - 25), 'the damaged ledger is left exactly as found');
});

// ---------------------------------------------------------------- risk: .claude/ files are HIGH

test('computeRisk: a task listing a .claude/ file is raised to HIGH, an ordinary file stays LOW, a security-boundary file is still HIGH', () => {
  const fx = fixture({ changeSet: CS({ allowed_paths: ['backend/**', 'scripts/**', 'src/**', '.claude/orchestration/tests/**'], boundary_ack: ['backend/app/core/security.py'] }) });
  const low = runLedger(fx, ['add-task', '--id', 'T1', '--title', 't', '--owner', 'main', '--files', 'src/app.txt', '--risk', 'LOW']);
  assert.match(low.stdout, /risk LOW\)/);
  const hi = runLedger(fx, ['add-task', '--id', 'T2', '--title', 't', '--owner', 'main', '--files', '.claude/orchestration/tests/x.mjs', '--risk', 'LOW']);
  assert.match(hi.stdout, /risk HIGH, raised from LOW/);
  const bnd = runLedger(fx, ['add-task', '--id', 'T3', '--title', 't', '--owner', 'main', '--files', 'backend/app/core/security.py', '--risk', 'LOW']);
  assert.match(bnd.stdout, /risk HIGH, raised from LOW/);
  assert.deepEqual(readLedger(fx).tasks.map((t) => t.risk), ['LOW', 'HIGH', 'HIGH']);
});

test('HIGH task: needs every HIGH gate and all three reviews after the last edit; reviews go stale after any later governance-file edit', () => {
  const fx = fixture();
  addStart(fx, 'T1', '.claude/orchestration/tests/x.mjs');
  assert.equal(taskOf(fx).risk, 'HIGH');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  let r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /gate G-PYT: no runner evidence/);
  assert.match(r.stderr, /review by code-reviewer/);
  assert.equal(runGate(fx, 'G-PYT').status, 0);
  r = done(fx);
  assert.equal(r.status, 1);
  for (const a of REVIEWERS) assert.match(r.stderr, new RegExp(`review by ${a}`));
  logAndReview(fx);
  // an edit (even identical bytes) to any governance file after the reviews makes them stale
  const agent = path.join(fx.root, '.claude', 'agents', 'a.md');
  fs.writeFileSync(agent, fs.readFileSync(agent));
  r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /review by code-reviewer: no PASS recorded after the last edit/);
  logAndReview(fx);
  r = done(fx);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(taskOf(fx).final_risk, 'HIGH');
});

test('a review PASS without a hook-logged agent run after the last edit does not count', () => {
  const fx = fixture();
  addStart(fx, 'T1', '.claude/orchestration/tests/x.mjs');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  assert.equal(runGate(fx, 'G-PYT').status, 0);
  logAndReview(fx, 'T1', ['code-reviewer', 'security-auditor']);
  const r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /review by test-engineer/);
});

// ---------------------------------------------------------------- unchanged behaviour

test('gates that are not autonomous, unknown, or lack a runner block still cannot satisfy a task', () => {
  let fx = fixture();
  addStart(fx, 'T1', 'src/app.txt', 'LOW', ['--gates', 'G-BLK']);
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  let r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /gate G-BLK is approval\/BLOCKED; it cannot be satisfied autonomously/);
  fx = fixture();
  addStart(fx, 'T1', 'src/app.txt', 'LOW', ['--gates', 'G-NORUN,G-MISSING']);
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /gate G-NORUN: no runner block/);
  assert.match(r.stderr, /unknown gate G-MISSING/);
});

test('done still refuses an out-of-scope working-tree change and a status that is not IN_PROGRESS/IN_REVIEW', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  put(fx.root, 'stray.txt', 'x');
  let r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /out-of-scope changes: stray\.txt/);
  fs.rmSync(path.join(fx.root, 'stray.txt'));
  assert.equal(done(fx).status, 0);
  r = done(fx);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /status is DONE/);
});

test('a failed done does not change the task and records no accepted evidence', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  const before = evidence(fx).length;
  assert.equal(done(fx).status, 1);
  assert.equal(taskOf(fx).status, 'IN_PROGRESS');
  assert.equal(taskOf(fx).done_at, undefined);
  assert.equal(evidence(fx).length, before);
});

// ---------------------------------------------------------------- status shows trust state

test('status shows the trust state: strict mode and, per required gate, the newest runner entry and whether it is acceptable now', () => {
  const fx = fixture();
  addStart(fx, 'T1', 'src/app.txt');
  let out = runLedger(fx, ['status']).stdout;
  assert.match(out, /evidence trust: STRICT/);
  assert.match(out, /G-SCR: no runner evidence/);
  assert.equal(runGate(fx, 'G-SCR').status, 0);
  out = runLedger(fx, ['status']).stdout;
  assert.match(out, /G-SCR: newest runner entry PASS/);
  assert.match(out, /acceptable now/);
  put(fx.root, 'src/app.txt', 'moved on\n');
  out = runLedger(fx, ['status']).stdout;
  assert.match(out, /G-SCR: newest runner entry PASS/);
  assert.match(out, /NOT acceptable/);
  assert.match(out, /tree_hash/);
});
