// Shared test fixture (GE6, GE4): a throwaway git repo that holds copies of the real runner, ledger, core and hooks, an approved run, and a
// fake "pytest" (a Node script that writes a chosen junit file). The real repo, ledger and gates.json are never touched.
// Not a test file: node --test ignores it (it matches no *.test.* pattern).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as core from '../../ledger-core.mjs';
import { securePrivateDir } from '../../run-gate.mjs';

export const REAL_ORCH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const REAL_HOOKS = path.resolve(REAL_ORCH, '..', 'hooks');
export const h = (s) => crypto.createHash('sha256').update(s).digest('hex');
export const NODE_HASH = h(fs.readFileSync(process.execPath));
export const DEFAULT_RUN_ID = 'gov-test';

const made = [];
export const tmp = (prefix = 'gfx-') => { const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); made.push(d); return d; };
// A private base directory for the runner (the runner rejects a shared or world-writable TEMP; on Windows a fresh mkdtemp inherits the parent's ACL).
export const privateTmp = (prefix = 'gfx-tmp-') => { const d = tmp(prefix); securePrivateDir(d); return d; };
export const cleanup = () => { for (const d of made.splice(0)) { try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best effort */ } } };
export function put(root, rel, content = 'x') {
  const p = path.join(root, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  return p;
}
export function git(root, ...args) {
  return execFileSync('git', ['-C', root, '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

export const FAKE_PYTEST = `
import fs from 'node:fs';
import path from 'node:path';
const args = process.argv.slice(2);
const jx = (args.find((a) => a.startsWith('--junitxml=')) || '').slice('--junitxml='.length);
const mode = (args.find((a) => a.startsWith('mode=')) || 'mode=pass').slice(5);
const tc = (n) => '<testcase classname="tests.test_x" name="' + n + '" time="0.001"/>';
const doc = (t, cases) => '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="' + t + '" time="0.01">' + cases + '</testsuite></testsuites>';
if (mode === 'pass') fs.writeFileSync(jx, doc(3, tc('a') + tc('b') + tc('c')));
`;

const PY = (over = {}) => ({
  name: 'pytest', kind: 'pytest', cwd: 'backend', launcher: [process.execPath], resolve_args: ['-e', 'console.log(process.execPath)'],
  python_args: ['fake-pytest.mjs'], argv_tail: ['mode=pass'], timeout_s: 60, ...over,
});
const SCRIPT = (name, file, over = {}) => ({ name, kind: 'script', cwd: '.', argv: ['node', file], timeout_s: 60, ...over });

export function defaultGates() {
  const auto = { autonomy: 'autonomous', status: 'CONFIGURED' };
  return {
    gates: [
      { id: 'G-PYT', ...auto, match: { kind: 'pytest' }, pytest_targets: ['tests'], runner: { steps: [PY()] } },
      { id: 'G-SCR', ...auto, runner: { steps: [SCRIPT('scan', 'scripts/ok.mjs')] } },
      { id: 'G-TWO', ...auto, runner: { steps: [SCRIPT('scope-check', 'scripts/ok.mjs'), { name: 'manifest-scope', kind: 'builtin', builtin: 'manifest-scope' }] } },
    ],
    risk_requirements: {
      LOW: { gates: ['G-SCR'], reviews: [] }, MEDIUM: { gates: ['G-SCR', 'G-PYT'], reviews: [] }, HIGH: { gates: ['G-SCR', 'G-PYT'], reviews: [] },
    },
  };
}

// opts: runId, gates (object), changeSet (object), withBaseline (bool), approved (bool), extraCopies (list of [srcAbs, destRelUnderRoot])
export function makeFixture({ runId = DEFAULT_RUN_ID, gates = null, changeSet = null, withBaseline = false, approved = true, extraCopies = [] } = {}) {
  const root = tmp('gfx-root-');
  const tmpd = privateTmp('gfx-tmp-');
  git(root, 'init', '-q');
  put(root, '.gitignore', '.claude/\n');
  put(root, 'backend/fake-pytest.mjs', FAKE_PYTEST);
  put(root, 'scripts/ok.mjs', 'process.exit(0);\n');
  put(root, 'src/app.txt', 'v1\n');
  git(root, 'add', '-A');
  git(root, 'commit', '-q', '-m', 'init');
  const orch = path.join(root, '.claude', 'orchestration');
  const hooks = path.join(root, '.claude', 'hooks');
  fs.mkdirSync(orch, { recursive: true });
  fs.mkdirSync(hooks, { recursive: true });
  for (const f of ['run-gate.mjs', 'ledger-core.mjs', 'ledger.mjs', 'patterns.mjs', 'boundaries.json']) fs.copyFileSync(path.join(REAL_ORCH, f), path.join(orch, f));
  for (const f of ['record-gate.mjs', 'subagent-log.mjs', 'lib.mjs']) fs.copyFileSync(path.join(REAL_HOOKS, f), path.join(hooks, f));
  for (const [src, dest] of extraCopies) { fs.mkdirSync(path.dirname(path.join(root, dest)), { recursive: true }); fs.copyFileSync(src, path.join(root, dest)); }
  put(root, '.claude/orchestration/gates.json', JSON.stringify(gates || defaultGates()));
  put(root, '.claude/orchestration/trusted-interpreters.json', JSON.stringify({ schema: 1, interpreters: [{ path: process.execPath, sha256: NODE_HASH }] }));
  put(root, '.claude/settings.json', '{"hooks":{}}\n');
  put(root, '.claude/agents/a.md', '# agent\n');
  put(root, '.claude/hooks/guard.mjs', '// guard\n');
  const cs = changeSet || { run_id: runId, allowed_paths: ['backend/**', 'scripts/**', 'src/**'], forbidden_paths: [] };
  if (withBaseline) {
    const m0 = core.hSetManifest(root);
    const baseline = put(tmp('gfx-base-'), 'm0.txt', m0.text);
    cs.baseline_manifest = { path: baseline, sha256: h(m0.text) };
    cs.allowed_paths = [...cs.allowed_paths, '.claude/orchestration/tests/**'];
  }
  const runDir = path.join(orch, 'runs', runId);
  fs.mkdirSync(runDir, { recursive: true });
  const csRaw = JSON.stringify(cs, null, 2) + '\n';
  fs.writeFileSync(path.join(runDir, 'change-set.json'), csRaw);
  const ledger = path.join(runDir, 'ledger.json');
  fs.writeFileSync(ledger, JSON.stringify({ run_id: runId, objective: 't', status: 'RUNNING', tasks: [], evidence: [], events: [] }));
  fs.writeFileSync(path.join(orch, 'ACTIVE_RUN'), runId + '\n');
  fs.mkdirSync(path.join(orch, 'approvals'), { recursive: true });
  const approval = path.join(orch, 'approvals', `${runId}.json`);
  if (approved) fs.writeFileSync(approval, JSON.stringify({ run_id: runId, change_set_sha256: h(csRaw), approved_at: new Date().toISOString(), approved_by: 'test' }));
  return { root, tmpd, orch, hooks, cs, csRaw, ledger, approval, runId };
}

export const baseEnv = (fx, extra = {}) => ({ ...process.env, TMP: fx.tmpd, TEMP: fx.tmpd, TMPDIR: fx.tmpd, ...extra });
export const runGate = (fx, args, extraEnv = {}) => spawnSync(process.execPath, [path.join(fx.orch, 'run-gate.mjs'), ...(Array.isArray(args) ? args : [args])], { cwd: fx.root, env: baseEnv(fx, extraEnv), encoding: 'utf8', timeout: 180000 });
export const runLedger = (fx, args, extraEnv = {}) => spawnSync(process.execPath, [path.join(fx.orch, 'ledger.mjs'), ...args], { cwd: fx.root, env: baseEnv(fx, extraEnv), encoding: 'utf8', timeout: 60000 });
export const fireHook = (fx, script, payload) => spawnSync(process.execPath, [path.join(fx.hooks, script)], { input: JSON.stringify({ cwd: fx.root, ...payload }), encoding: 'utf8', timeout: 30000 });
export const readLedger = (fx) => JSON.parse(fs.readFileSync(fx.ledger, 'utf8'));
export const evidence = (fx) => readLedger(fx).evidence;
export const last = (fx) => { const e = evidence(fx); return e[e.length - 1]; };
export function acceptCtx(fx, gate, over = {}) {
  const def = JSON.parse(fs.readFileSync(path.join(fx.orch, 'gates.json'), 'utf8')).gates.find((g) => g.id === gate);
  return { gate, ledgerRun: fx.runId, changeSetSha256: h(fx.csRaw), changeSet: fx.cs, stepNames: core.runnerStepNames(def), taskStartedAtMs: Date.now() - 600_000, nowMs: Date.now(), current: core.computeBindings(fx.cs, fx.root), ...over };
}
