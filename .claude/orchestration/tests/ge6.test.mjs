// GE6: regression and adversarial tests. Run: node --test .claude/orchestration/tests/ge6.test.mjs
//  1. all 50 reference predicate vectors against the SHIPPED helper (AC-10, AC-13..AC-16, AC-8, AC-9)
//  2. cross-check: the Node manifest equals the human PowerShell manifest on a fixture tree
//  3. adversarial attempts in isolated temp trees: none may produce satisfiable evidence
//  4. regression: existing ledger behaviour is preserved and the preventive guards are byte-identical to the human baseline M0
// Node >= 18. PowerShell is used only for the cross-check (Windows); elsewhere the committed golden hash is compared instead.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as core from '../ledger-core.mjs';
import { makeFixture, runGate, runLedger, fireHook, evidence, last, readLedger, acceptCtx, put, tmp, cleanup, h, git, REAL_ORCH } from './fixtures/gate-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(HERE, 'fixtures');
after(cleanup);
const problems = (e, ctx) => core.evidenceAcceptanceProblems(e, ctx);

// ================================================================ 1. the 50 predicate vectors

const real = (f) => JSON.parse(fs.readFileSync(path.join(FIX, f), 'utf8'));
const ap = (...paths) => ({ allowed_paths: paths });
const BM = { path: 'p', sha256: 's' };
const SYNTH = [
  ['allowed **', ap('**'), 'FAIL'], ['allowed .claude/**', ap('.claude/**'), 'FAIL'], ['allowed **/*.mjs', ap('**/*.mjs'), 'FAIL'],
  ['allowed */foo.json', ap('*/foo.json'), 'FAIL'], ['allowed ./.claude/x', ap('./.claude/x'), 'FAIL'], ['allowed .CLAUDE/x', ap('.CLAUDE/x'), 'FAIL'],
  ['allowed .cl*/x', ap('.cl*/x'), 'FAIL'], ['allowed backslash .claude\\x', ap('.claude\\x'), 'FAIL'],
  ['allowed backend/**', ap('backend/**'), 'NOT_APPLICABLE'], ['allowed docs/*.md', ap('docs/*.md'), 'NOT_APPLICABLE'], ['allowed empty list', ap(), 'NOT_APPLICABLE'],
  ['ordinary scope + declared baseline', { allowed_paths: ['backend/**'], baseline_manifest: BM }, 'RUN'],
  ['baseline is an array, .claude scope', { allowed_paths: ['.claude/x'], baseline_manifest: [] }, 'FAIL'],
  ['traversal ../x', ap('../x'), 'FAIL'], ['traversal ..\\x', ap('..\\x'), 'FAIL'],
  ['traversal backend\\..\\.claude\\x', ap('backend\\..\\.claude\\x'), 'FAIL'], ['traversal a/../.claude/x', ap('a/../.claude/x'), 'FAIL'],
  ['traversal ".. /x" (trailing space)', ap('.. /x'), 'FAIL'], ['traversal "...\\x"', ap('...\\x'), 'FAIL'],
  ['UNC \\\\server\\share\\x', ap('\\\\server\\share\\x'), 'FAIL'], ['UNC //server/share/x', ap('//server/share/x'), 'FAIL'],
  ['rooted /abs/x', ap('/abs/x'), 'FAIL'], ['rooted \\abs\\x', ap('\\abs\\x'), 'FAIL'],
  ['drive C:\\x', ap('C:\\x'), 'FAIL'], ['drive-relative C:x', ap('C:x'), 'FAIL'], ['stream .claude::$DATA', ap('.claude::$DATA'), 'FAIL'],
  ['trailing space ".claude "', ap('.claude /x'), 'FAIL'], ['trailing dot ".claude./x"', ap('.claude./x'), 'FAIL'], ['short name CLAUDE~1/x', ap('CLAUDE~1/x'), 'FAIL'],
  ['empty string', ap(''), 'FAIL'], ['whitespace only', ap('   '), 'FAIL'], ['control character', ap('a\u0000b'), 'FAIL'],
  ['non-string element (number)', { allowed_paths: [5] }, 'FAIL'], ['non-string element (nested array)', { allowed_paths: [['backend/x']] }, 'FAIL'],
  ['non-string element (null)', { allowed_paths: [null] }, 'FAIL'],
  ['ordinary backslashes backend\\sub\\x', ap('backend\\sub\\x'), 'NOT_APPLICABLE'], ['ordinary dotted a.b./x', ap('docs/a.b./x'), 'NOT_APPLICABLE'],
  ['ordinary ./backend/x', ap('./backend/x'), 'NOT_APPLICABLE'],
  ['container: allowed_paths string', { allowed_paths: 'backend/**' }, 'FAIL'], ['container: allowed_paths object', { allowed_paths: { a: 'backend/**' } }, 'FAIL'],
  ['container: allowed_paths null', { allowed_paths: null }, 'FAIL'], ['container: allowed_paths missing', {}, 'FAIL'],
  ['container: allowed_paths number', { allowed_paths: 7 }, 'FAIL'],
  ['container: change set null', null, 'FAIL'], ['container: change set array', [], 'FAIL'], ['container: change set string', 'x', 'FAIL'],
  ['container malformed even with baseline', { allowed_paths: 'x', baseline_manifest: BM }, 'FAIL'],
];
const REAL_VECTORS = [
  ['governance v2 draft', 'governance-cs-draft-v2.json', '6c4c83a2', 'RUN'],
  ['PR-SEC-01 r4', 'pr-sec-01-change-set-r4.json', '9fded2fa', 'NOT_APPLICABLE'],
  ['PR-SEC-01 r3', 'pr-sec-01-change-set-r3.json', '09f4895a', 'NOT_APPLICABLE'],
];

test('the vector set is exactly the 50 reference expectations (3 real Change Sets + 47 synthetic)', () => {
  assert.equal(REAL_VECTORS.length + SYNTH.length, 50);
  assert.equal(new Set(SYNTH.map((v) => v[0])).size, SYNTH.length, 'synthetic vector names are unique');
});

for (const [name, file, prefix, want] of REAL_VECTORS) {
  test(`vector (real file, byte-identical): ${name} -> ${want}`, () => {
    const bytes = fs.readFileSync(path.join(FIX, file));
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex').slice(0, 8), prefix, `${file} must be the unchanged original`);
    assert.equal(core.manifestScopeApplicability(real(file)), want);
  });
}
for (const [name, cs, want] of SYNTH) test(`vector: ${name} -> ${want}`, () => assert.equal(core.manifestScopeApplicability(cs), want));

test('AC-8: for PR-SEC-01 r3 and r4 the G-SCOPE outcome rests on step 1 alone (not-applicable record, null baseline hashes)', () => {
  for (const f of ['pr-sec-01-change-set-r3.json', 'pr-sec-01-change-set-r4.json']) {
    const cs = real(f);
    assert.equal(core.manifestScopeApplicability(cs), 'NOT_APPLICABLE', f);
    const fx = makeFixture({ changeSet: { ...cs, run_id: 'gov-test' } });
    const gates = { gates: [{ id: 'G-TWO', autonomy: 'autonomous', status: 'CONFIGURED', runner: { steps: [{ name: 'scope-check', kind: 'script', cwd: '.', argv: ['node', 'scripts/ok.mjs'], timeout_s: 60 }, { name: 'manifest-scope', kind: 'builtin', builtin: 'manifest-scope' }] } }] };
    fs.writeFileSync(path.join(fx.orch, 'gates.json'), JSON.stringify(gates));
    assert.equal(runGate(fx, 'G-TWO').status, 0, f);
    const e = last(fx);
    assert.equal(e.steps[1].applicable, false);
    assert.equal(e.baseline_manifest_sha256, null);
  }
});

// ================================================================ 2. cross-check: Node manifest vs the human PowerShell manifest

const TREE = {
  'settings.json': '{"hooks":{}}\n', 'settings.local.json': '{}\n', 'agents/a.md': '# a\n', 'skills/s/SKILL.md': 'skill\n', 'references/r.md': 'r\n',
  'hooks/guard.mjs': 'g\n', 'hooks/tests/t.mjs': 't\n', 'orchestration/ledger.mjs': 'l\n', 'orchestration/gates.json': '{}\n', 'orchestration/tests/ge.test.mjs': 'x',
  'orchestration/Zeta.txt': 'z', 'orchestration/_under.txt': 'u', 'orchestration/with space.txt': 'sp', '\u00fcn\u00ef/\u00e7\u00f6d\u00e9.txt': 'unicode', '.hidden': 'h',
  'orchestration/runs.txt': 'prefix lookalike, kept', 'orchestration/reports-notes.md': 'kept', 'a/b/c/deep.txt': 'deep', 'empty.txt': '',
  'orchestration/runs/r1/ledger.json': 'EXCLUDED', 'orchestration/approvals/a.json': 'EXCLUDED', 'orchestration/ACTIVE_RUN': 'EXCLUDED', 'orchestration/hook-debug.log': 'EXCLUDED',
  'reports/x.md': 'EXCLUDED', 'worktrees/w/y.txt': 'EXCLUDED',
};
const GOLDEN_SHA256 = '70c4d9c89fb30e05577335d43f1b975ac9e52b918f9e2e61f0f94bc30146cbe3'; // first produced by this test and verified equal to the PowerShell output

// The human procedure from design v2 section 8 step 5, verbatim apart from the output path. It does not use the code under test.
const PS_SNIPPET = (outFile) => `
$root=(Get-Location).Path; $claude=Join-Path $root '.claude'
$ex=@('orchestration/runs/','orchestration/approvals/','orchestration/ACTIVE_RUN','orchestration/hook-debug.log','reports/','worktrees/')
$k=New-Object System.Collections.Generic.List[string]; $v=New-Object System.Collections.Generic.List[string]
foreach($f in Get-ChildItem -LiteralPath $claude -Recurse -File -Force){
  $rel=$f.FullName.Substring($claude.Length+1).Replace('\\','/'); $skip=$false
  foreach($e in $ex){ if($rel -eq $e.TrimEnd('/') -or $rel.StartsWith($e)){ $skip=$true } }
  if(-not $skip){ $k.Add($rel); $v.Add(((Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower())+'  '+$rel) } }
$ka=$k.ToArray(); $va=$v.ToArray(); [Array]::Sort($ka,$va,[StringComparer]::Ordinal)
[IO.File]::WriteAllText('${outFile.replace(/'/g, "''")}', (($va -join "\`n")+"\`n"), (New-Object Text.UTF8Encoding($false)))
`;
function buildTree() {
  const root = tmp('ge6-tree-');
  for (const [rel, body] of Object.entries(TREE)) put(root, `.claude/${rel}`, body);
  return root;
}

test('the Node manifest of a fixture tree equals the human PowerShell manifest byte for byte (Windows) and the committed golden hash (everywhere)', () => {
  const root = buildTree();
  const m = core.hSetManifest(root);
  assert.ok(m.rels.every((r) => !/(^|\/)(runs|approvals|reports|worktrees)\//.test(r) || r.startsWith('orchestration/runs.txt')), 'excluded paths are absent');
  assert.ok(!m.rels.includes('orchestration/ACTIVE_RUN') && !m.rels.includes('orchestration/hook-debug.log'));
  assert.ok(m.rels.includes('settings.local.json') && m.rels.includes('orchestration/runs.txt') && m.rels.includes('.hidden') && m.rels.includes('empty.txt'));
  if (process.platform === 'win32') { // the independent human procedure is checked FIRST, so a golden is only ever a copy of something PowerShell agreed with
    const out = path.join(tmp('ge6-ps-'), 'M0.txt');
    const r = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', PS_SNIPPET(out)], { cwd: root, encoding: 'utf8', timeout: 120000 });
    assert.equal(r.status, 0, `PowerShell failed: ${r.stderr}`);
    const ps = fs.readFileSync(out);
    assert.equal(ps.toString('utf8'), m.text, 'Node and PowerShell manifests differ');
    assert.equal(crypto.createHash('sha256').update(ps).digest('hex'), m.sha256);
    assert.equal(ps.includes(13), false, 'no CR in the human manifest');
  }
  assert.equal(m.sha256, GOLDEN_SHA256, `golden mismatch; actual manifest sha256 = ${m.sha256}`);
});

test('the E-set of the same fixture tree is the documented subset (and only that)', () => {
  const root = buildTree();
  assert.deepEqual(core.eSetManifest(root).rels, ['agents/a.md', 'hooks/guard.mjs', 'orchestration/gates.json', 'orchestration/ledger.mjs', 'settings.json']);
});

// ================================================================ 3. adversarial attempts (isolated temp trees)

function goodEntry(fx, gate = 'G-PYT') {
  assert.equal(runGate(fx, gate).status, 0);
  const e = last(fx);
  assert.deepEqual(problems(e, acceptCtx(fx, gate)), [], 'baseline: the genuine entry is acceptable before any attack');
  return e;
}
const mutate = (fx, rel, extra = ' ') => { const p = path.join(fx.root, rel); const orig = fs.readFileSync(p); fs.writeFileSync(p, Buffer.concat([orig, Buffer.from(extra)])); return () => fs.writeFileSync(p, orig); };

test('ATTACK: replaying a genuine PASS after any tracked or untracked edit is stale; restoring identical bytes (even with a newer mtime) is content-equal, an mtime-only touch changes nothing', () => {
  const fx = makeFixture();
  const e = goodEntry(fx);
  const app = path.join(fx.root, 'src/app.txt');
  fs.writeFileSync(app, 'v2\n');
  assert.ok(problems(e, acceptCtx(fx, 'G-PYT')).some((m) => m.includes('tree_hash')));
  fs.writeFileSync(app, 'v1\n');
  const later = new Date(Date.now() + 3600_000);
  fs.utimesSync(app, later, later);
  assert.deepEqual(problems(e, acceptCtx(fx, 'G-PYT')), []);
  put(fx.root, 'src/new-untracked.txt', 'n');
  assert.ok(problems(e, acceptCtx(fx, 'G-PYT')).some((m) => m.includes('tree_hash')));
});

test('ATTACK: editing the runner, ledger, ledger-core, gates.json, interpreter allowlist, settings.json, an agent file or a hook after the run stales the evidence; reverting restores it', () => {
  const fx = makeFixture();
  const e = goodEntry(fx);
  const targets = { 'run-gate.mjs': ['runner_sha256', 'claude_e_sha256'], 'ledger.mjs': ['ledger_sha256', 'claude_e_sha256'], 'ledger-core.mjs': ['ledger_core_sha256', 'claude_e_sha256'],
    'gates.json': ['gates_json_sha256', 'claude_e_sha256'], 'trusted-interpreters.json': ['interpreters_sha256', 'claude_e_sha256'] };
  for (const [f, keys] of Object.entries(targets)) {
    const restore = mutate(fx, `.claude/orchestration/${f}`, f.endsWith('.json') ? ' ' : '\n// tampered\n');
    const p = problems(e, acceptCtx(fx, 'G-PYT')).join(' | ');
    for (const k of keys) assert.ok(p.includes(k), `${f} -> ${k}: ${p}`);
    restore();
    assert.deepEqual(problems(e, acceptCtx(fx, 'G-PYT')), [], `${f} reverted`);
  }
  for (const rel of ['.claude/settings.json', '.claude/agents/a.md', '.claude/hooks/guard.mjs']) {
    const restore = mutate(fx, rel);
    assert.ok(problems(e, acceptCtx(fx, 'G-PYT')).join(' | ').includes('claude_e_sha256'), rel);
    restore();
    assert.deepEqual(problems(e, acceptCtx(fx, 'G-PYT')), [], `${rel} reverted`);
  }
});

test('ATTACK: loosening gates.json after the run (dropping a step) is rejected twice over: the file hash is stale and the step list no longer matches', () => {
  const fx = makeFixture();
  assert.equal(runGate(fx, 'G-TWO').status, 0);
  const e = last(fx);
  const gp = path.join(fx.orch, 'gates.json');
  const g = JSON.parse(fs.readFileSync(gp, 'utf8'));
  g.gates.find((x) => x.id === 'G-TWO').runner.steps.pop();
  fs.writeFileSync(gp, JSON.stringify(g));
  const p = problems(e, acceptCtx(fx, 'G-TWO')).join(' | ');
  assert.ok(p.includes('gates_json_sha256'));
  assert.ok(p.includes('do not match the gate definition'));
});

test('ATTACK: copying an entry into another run or under another Change Set is rejected', () => {
  const a = makeFixture({ runId: 'run-a' });
  const e = goodEntry(a);
  const b = makeFixture({ runId: 'run-b' });
  assert.ok(problems(e, acceptCtx(b, 'G-PYT')).some((m) => m.includes('different run')));
  const c = makeFixture({ runId: 'run-a', changeSet: { run_id: 'run-a', allowed_paths: ['backend/**'], forbidden_paths: [] } });
  assert.ok(problems(e, acceptCtx(c, 'G-PYT')).some((m) => m.includes('different Change Set')));
  const sameBytesOtherGate = { ...e, gate: 'G-SCR', covers: ['G-SCR'] };
  assert.ok(problems(sameBytesOtherGate, acceptCtx(a, 'G-SCR')).length > 0, 'relabelling a pytest entry as another gate fails its step/kind checks');
});

test('ATTACK: an entry for one gate cannot satisfy another gate', () => {
  const fx = makeFixture();
  const e = goodEntry(fx, 'G-SCR');
  assert.ok(problems(e, acceptCtx(fx, 'G-PYT')).length > 0);
});

test('ATTACK: a hand-written `ledger.mjs evidence` PASS is recorded as source "orchestrator" and never satisfies a gate', () => {
  const fx = makeFixture();
  const r = runLedger(fx, ['evidence', '--gate', 'G-PYT', '--result', 'PASS', '--ref', 'trust me']);
  assert.equal(r.status, 0, r.stderr);
  const e = last(fx);
  assert.equal(e.source, 'orchestrator');
  assert.equal(core.newestRunnerEntry(evidence(fx), 'G-PYT'), null);
  assert.ok(problems(e, acceptCtx(fx, 'G-PYT')).length > 0);
});

test('ATTACK: `echo "500 passed" # pytest` leaves only a hook-observed log entry (no runner evidence exists)', () => {
  const fx = makeFixture();
  const r = fireHook(fx, 'record-gate.mjs', { tool_name: 'Bash', tool_input: { command: 'echo "500 passed" # pytest' }, tool_response: { stdout: '500 passed in 1.0s' } });
  assert.equal(r.status, 0);
  const all = evidence(fx);
  assert.equal(all.length, 1);
  assert.equal(all[0].source, 'hook-observed');
  assert.equal(core.newestRunnerEntry(all, 'G-PYT'), null);
  assert.ok(problems(all[0], acceptCtx(fx, 'G-PYT')).length > 0);
});

test('ATTACK: a newer FAIL revokes an older genuine PASS (newest-entry rule), including a runner FAIL caused by a Change Set that may include .claude/', () => {
  const fx = makeFixture();
  const pass = goodEntry(fx, 'G-TWO');
  const failEntry = { ...pass, result: 'FAIL', exit_status: 1, steps: [pass.steps[0], { name: 'manifest-scope', argv_sha256: h('x'), exit_status: 1 }], at: new Date(Date.parse(pass.at) + 5000).toISOString() };
  const newest = core.newestRunnerEntry([pass, failEntry], 'G-TWO');
  assert.equal(newest.result, 'FAIL');
  assert.ok(problems(newest, acceptCtx(fx, 'G-TWO')).length > 0);
});

test('ATTACK: schema fuzzing - replacing any field of a genuine entry with a wrong-typed value never yields a valid record (except nullable fields set to null)', () => {
  const fx = makeFixture();
  const e = goodEntry(fx);
  // Oracle: the only structurally valid mutations are null for nullable fields, a well-formed hex string for hash fields, and a well-formed run id for
  // ledger_run. Whether such a value is the RIGHT value is decided by evidenceAcceptanceProblems (stale/mismatch), tested elsewhere in this file.
  const NULLABLE = new Set(['baseline_manifest_sha256', 'h_manifest_sha256', 'required_cells']);
  const HEX = new Set(['change_set_sha256', 'tree_hash', 'claude_e_sha256', 'runner_sha256', 'ledger_sha256', 'ledger_core_sha256', 'gates_json_sha256', 'interpreters_sha256', 'junit_sha256', 'baseline_manifest_sha256', 'h_manifest_sha256']);
  const values = [null, 0, 1, -1, '', 'x', true, false, [], {}, ['x'], { a: 1 }, 1.5, 'G-OTHER', '0'.repeat(64), 'A'.repeat(64)];
  let checked = 0;
  for (const key of Object.keys(e)) {
    for (const v of values) {
      const mutated = { ...e, [key]: v };
      if (JSON.stringify(mutated[key]) === JSON.stringify(e[key])) continue;
      const ok = core.validateEvidenceV1(mutated).ok;
      const legit = (NULLABLE.has(key) && v === null) || (HEX.has(key) && v === '0'.repeat(64)) || (key === 'ledger_run' && typeof v === 'string' && core.RUN_ID_RE.test(v));
      assert.equal(ok, legit, `${key} <- ${JSON.stringify(v)}`);
      checked++;
    }
  }
  assert.ok(checked > 300, `fuzzed ${checked} mutations`);
});

test('ATTACK: a malformed or truncated ledger cannot be read as clean (duplicate-key scan throws, so done() must fail closed)', () => {
  const fx = makeFixture();
  goodEntry(fx);
  const raw = fs.readFileSync(fx.ledger, 'utf8');
  assert.deepEqual([...core.taintedEvidenceIndexes(raw)], []);
  assert.throws(() => core.taintedEvidenceIndexes(raw.slice(0, raw.length - 40)));
  const forged = raw.replace('"result": "PASS"', '"result": "FAIL", "result": "PASS"');
  assert.notEqual(forged, raw);
  assert.deepEqual([...core.taintedEvidenceIndexes(forged)], [0]);
  assert.equal(JSON.parse(forged).evidence[0].result, 'PASS', 'JSON.parse alone would have hidden it');
});

// ---- G-SCAN coverage of ignored governance files (correction cycle 1) ----
const FAKE_KEY = ['sk_live_', 'abcdefghijklmnop1234'].join(''); // assembled at run time: this file never contains the literal
const SCAN_STEPS = [
  { name: 'scan', kind: 'script', cwd: '.', argv: ['node', '.claude/orchestration/scan.mjs', '--changed'], timeout_s: 60 },
  { name: 'manifest-scan', kind: 'builtin', builtin: 'manifest-scan' },
];
const scanGates = (steps = SCAN_STEPS) => ({ gates: [{ id: 'G-SCAN', autonomy: 'autonomous', status: 'EXECUTABLE', runner: { steps } }], risk_requirements: { LOW: { gates: ['G-SCAN'], reviews: [] }, MEDIUM: { gates: ['G-SCAN'], reviews: [] }, HIGH: { gates: ['G-SCAN'], reviews: [] } } });
const scanFixture = (steps) => makeFixture({ gates: scanGates(steps), withBaseline: true, extraCopies: [[path.join(REAL_ORCH, 'scan.mjs'), '.claude/orchestration/scan.mjs']] });

test('ATTACK: a secret planted in an ignored governance file is invisible to scan.mjs --changed (0 files) but fails G-SCAN through manifest-scan', () => {
  const fx = scanFixture();
  put(fx.root, '.claude/orchestration/tests/leak.mjs', `export const k = "${FAKE_KEY}";\n`);
  assert.equal(git(fx.root, 'status', '--porcelain=v1').trim(), '', 'git sees nothing');
  const r = runGate(fx, 'G-SCAN');
  assert.match(r.stdout, /scan: clean \(0 file\(s\) checked\)/, 'the legacy scan step alone would have PASSED with nothing checked');
  assert.equal(r.status, 1);
  assert.match(r.stdout, /BLOCKING orchestration\/tests\/leak\.mjs:1 secret:/);
  assert.ok(!(r.stdout + r.stderr).includes(FAKE_KEY));
  const e = last(fx);
  assert.equal(e.result, 'FAIL');
  assert.deepEqual(e.steps.map((s) => [s.name, s.exit_status]), [['scan', 0], ['manifest-scan', 1]]);
  assert.ok(problems(e, acceptCtx(fx, 'G-SCAN')).length > 0);
});

test('G-SCAN with manifest-scan: a clean governance diff PASSes, and the evidence binds exactly the scanned files', () => {
  const fx = scanFixture();
  put(fx.root, '.claude/orchestration/tests/ok.mjs', 'export const a = 1;\n');
  assert.equal(runGate(fx, 'G-SCAN').status, 0);
  const e = last(fx);
  assert.deepEqual(problems(e, acceptCtx(fx, 'G-SCAN')), []);
  const expected = h(`builtin:manifest-scan:v1\n${h('export const a = 1;\n')}  orchestration/tests/ok.mjs\n`);
  assert.equal(e.steps[1].argv_sha256, expected);
  // editing the scanned file afterwards stales the evidence (tree/H-set binding) even though it is invisible to git
  put(fx.root, '.claude/orchestration/tests/ok.mjs', `export const a = "${FAKE_KEY}";\n`);
  assert.ok(problems(e, acceptCtx(fx, 'G-SCAN')).some((m) => m.includes('h_manifest_sha256')));
});

test('ATTACK: a pre-manifest-scan G-SCAN entry (single step) is rejected once gates.json requires manifest-scan', () => {
  const fx = scanFixture([SCAN_STEPS[0]]);
  put(fx.root, '.claude/orchestration/tests/ok.mjs', 'export const a = 1;\n');
  assert.equal(runGate(fx, 'G-SCAN').status, 0);
  const old = last(fx);
  fs.writeFileSync(path.join(fx.orch, 'gates.json'), JSON.stringify(scanGates()));
  const p = problems(old, acceptCtx(fx, 'G-SCAN')).join(' | ');
  assert.ok(p.includes('do not match the gate definition'), p);
  assert.ok(p.includes('gates_json_sha256'), p);
});

test('ATTACK: a run directory in a shared TEMP is refused by the runner (no evidence), so a planted junit in a world-writable folder is never read', () => {
  const fx = makeFixture();
  const shared = tmp('ge6-shared-');
  if (process.platform === 'win32') assert.equal(spawnSync(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'icacls.exe'), [shared, '/grant', '*S-1-1-0:(OI)(CI)F']).status, 0);
  else fs.chmodSync(shared, 0o777);
  const r = spawnSync(process.execPath, [path.join(fx.orch, 'run-gate.mjs'), 'G-PYT'], { cwd: fx.root, env: { ...process.env, TMP: shared, TEMP: shared, TMPDIR: shared }, encoding: 'utf8' });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /unsafe temp directory/);
  assert.equal(evidence(fx).length, 0);
  assert.deepEqual(fs.readdirSync(shared), [], 'no run directory was left in the shared folder');
});

test('DOCUMENTED SAME-USER LIMIT (unchanged, not prevented here): a record forged with the correct current bindings validates; only the write guards on ledger.json and the human/independent review stand against it', () => {
  const fx = makeFixture();
  const e = goodEntry(fx);
  const forged = { ...e, run_id: crypto.randomUUID(), counts: { tests: 999, failures: 0, errors: 0, skipped: 0 } };
  assert.deepEqual(problems(forged, acceptCtx(fx, 'G-PYT')), []);
});

// ================================================================ 4. regression: existing behaviour preserved

test('REGRESSION: done is refused without an approved Change Set', () => {
  const fx = makeFixture({ approved: false });
  const r = runLedger(fx, ['done', 'T1']);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /not approved/);
});

test('REGRESSION: add-task still refuses files outside the Change Set and unacknowledged security-boundary files, and accepts in-scope files', () => {
  const fx = makeFixture();
  assert.equal(runLedger(fx, ['add-task', '--id', 'T1', '--title', 'a', '--owner', 'main', '--files', 'src/app.txt', '--risk', 'LOW']).status, 0);
  assert.equal(runLedger(fx, ['add-task', '--id', 'T2', '--title', 'b', '--owner', 'main', '--files', 'other/z.py']).status, 1);
  const r = runLedger(fx, ['add-task', '--id', 'T3', '--title', 'c', '--owner', 'main', '--files', 'backend/app/core/security.py']);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /boundary_ack/);
});

test('REGRESSION: a review still needs a hook-logged agent_stop for that agent', () => {
  const fx = makeFixture();
  runLedger(fx, ['add-task', '--id', 'T1', '--title', 'a', '--owner', 'main', '--files', 'src/app.txt', '--risk', 'MEDIUM']);
  runLedger(fx, ['start', 'T1']);
  assert.equal(runLedger(fx, ['review', 'T1', '--agent', 'code-reviewer', '--verdict', 'PASS']).status, 1);
  fireHook(fx, 'subagent-log.mjs', { hook_event_name: 'SubagentStop', agent_type: 'code-reviewer', agent_id: 'r1', last_assistant_message: 'x' });
  assert.equal(runLedger(fx, ['review', 'T1', '--agent', 'code-reviewer', '--verdict', 'PASS']).status, 0);
  const ev = readLedger(fx).events.filter((e) => e.type === 'agent_stop');
  assert.equal(ev.length, 1);
  assert.equal(ev[0].agent_type, 'code-reviewer');
});

test('REGRESSION: scope-check still passes in scope and fails for a stray file', () => {
  const fx = makeFixture();
  assert.equal(runLedger(fx, ['scope-check']).status, 0);
  put(fx.root, 'stray.txt', 'x');
  assert.equal(runLedger(fx, ['scope-check']).status, 1);
});

test('REGRESSION: G-SCOPE as a real two-step runner gate (scope-check then manifest-scope) passes in scope and FAILs on a stray file', () => {
  const gates = { gates: [{ id: 'G-SCOPE', autonomy: 'autonomous', status: 'EXECUTABLE', runner: { steps: [
    { name: 'scope-check', kind: 'script', cwd: '.', argv: ['node', '.claude/orchestration/ledger.mjs', 'scope-check'], timeout_s: 60 },
    { name: 'manifest-scope', kind: 'builtin', builtin: 'manifest-scope' }] } }] };
  const fx = makeFixture({ gates });
  assert.equal(runGate(fx, 'G-SCOPE').status, 0);
  assert.deepEqual(problems(last(fx), acceptCtx(fx, 'G-SCOPE')), []);
  put(fx.root, 'stray.txt', 'x');
  assert.equal(runGate(fx, 'G-SCOPE').status, 1);
  assert.equal(last(fx).result, 'FAIL');
  assert.deepEqual(last(fx).steps.map((s) => s.name), ['scope-check']);
});

test('REGRESSION: git history operations are untouched by the runner (it only reads git)', () => {
  const fx = makeFixture();
  const before = git(fx.root, 'rev-parse', 'HEAD').trim();
  goodEntry(fx);
  assert.equal(git(fx.root, 'rev-parse', 'HEAD').trim(), before);
  assert.equal(git(fx.root, 'status', '--porcelain=v1').trim(), '');
});

test('REGRESSION: every preventive guard and the interpreter allowlist are byte-identical to the human baseline M0 in the real governance worktree', () => {
  const csPath = path.resolve(HERE, '..', 'runs', 'gov-trusted-gate-evidence', 'change-set.json');
  const cs = JSON.parse(fs.readFileSync(csPath, 'utf8'));
  const r = core.manifestScopeCheck(cs, core.ROOT);
  assert.equal(r.ok, true, r.problems.join('; '));
  const guarded = ['hooks/guard-bash.mjs', 'hooks/guard-write.mjs', 'hooks/guard-agent.mjs', 'hooks/scope.mjs', 'hooks/subagent-log.mjs', 'hooks/session-context.mjs', 'hooks/lib.mjs',
    'orchestration/scan.mjs', 'orchestration/patterns.mjs', 'orchestration/boundaries.json', 'orchestration/trusted-interpreters.json', 'settings.json'];
  for (const g of guarded) assert.ok(![...r.added, ...r.modified, ...r.deleted].includes(g), `${g} must be unchanged`);
  assert.ok(![...r.added, ...r.modified, ...r.deleted].some((p) => p.startsWith('agents/') || p.startsWith('skills/') || p.startsWith('references/')), 'agents, skills and references are unchanged');
});
