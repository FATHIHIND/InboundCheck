// GE2: trusted gate runner (run-gate.mjs). Run: node --test .claude/orchestration/tests/ge2.test.mjs
// Every integration test copies the real runner into a fresh temp git repo ("fixture") and runs it there: the real ledger, repo and
// gates.json are never touched. The "pytest" under test is a small Node script that writes a chosen junit file and exits with a chosen
// status, so no Python is needed. Node >= 18.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as core from '../ledger-core.mjs';
import * as rg from '../run-gate.mjs';

const REAL_ORCH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const h = (s) => crypto.createHash('sha256').update(s).digest('hex');
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'ge2-'));
const NODE_HASH = h(fs.readFileSync(process.execPath));
const RUN_ID = 'gov-test';

function put(root, rel, content = 'x') {
  const p = path.join(root, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  return p;
}
function git(root, ...args) {
  return execFileSync('git', ['-C', root, '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

// ---- the fake pytest (a Node script; modes are selected through argv because the runner scrubs the environment) ----
const FAKE_PYTEST = `
import fs from 'node:fs';
import path from 'node:path';
const args = process.argv.slice(2);
const jx = (args.find((a) => a.startsWith('--junitxml=')) || '').slice('--junitxml='.length);
const mode = (args.find((a) => a.startsWith('mode=')) || 'mode=pass').slice(5);
const dir = path.dirname(jx);
const e = process.env;
fs.writeFileSync(path.join(dir, 'env.json'), JSON.stringify({ addopts: e.PYTEST_ADDOPTS ?? null, pythonpath: e.PYTHONPATH ?? null, startup: e.PYTHONSTARTUP ?? null,
  secret: e.SECRET_TOKEN ?? null, enc: e.PYTHONIOENCODING ?? null, harness: e.PR_SEC_01_DB_HARNESS ?? null, require: e.PR_SEC_01_REQUIRE_HARNESS ?? null, argv: args, cwd: process.cwd() }));
const tc = (n, extra, c = 'tests.test_x') => (extra ? '<testcase classname="' + c + '" name="' + n + '" time="0.001">' + extra + '</testcase>' : '<testcase classname="' + c + '" name="' + n + '" time="0.001"/>');
const doc = (a, cases) => '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="' + a.e + '" failures="' + a.f + '" skipped="' + a.s + '" tests="' + a.t + '" time="0.01">' + cases + '</testsuite></testsuites>';
const pass3 = doc({ e: 0, f: 0, s: 0, t: 3 }, tc('a') + tc('b') + tc('c'));
const write = (x) => fs.writeFileSync(jx, x);
switch (mode) {
  case 'pass': write(pass3); break;
  case 'skip': write(doc({ e: 0, f: 0, s: 1, t: 3 }, tc('a') + tc('b') + tc('s', '<skipped type="pytest.skip" message="why"/>'))); break;
  case 'fail-junit': write(doc({ e: 0, f: 1, s: 0, t: 3 }, tc('a') + tc('b') + tc('c', '<failure message="boom">x</failure>'))); break;
  case 'error-junit': write(doc({ e: 1, f: 0, s: 0, t: 3 }, tc('a') + tc('b') + tc('c', '<error message="boom">x</error>'))); break;
  case 'fail-exit': write(pass3); process.exit(1); break;
  case 'missing': break;
  case 'truncated': write(pass3.slice(0, -25)); break;
  case 'mismatch': write(doc({ e: 0, f: 0, s: 0, t: 5 }, tc('a') + tc('b') + tc('c'))); break;
  case 'zero': write(doc({ e: 0, f: 0, s: 0, t: 0 }, '')); break;
  case 'cdata': write(doc({ e: 0, f: 0, s: 0, t: 1 }, '<testcase classname="tests.test_x" name="a"><system-out><![CDATA[<testcase name="fake"/><failure>nope</failure>]]></system-out></testcase>')); break;
  case 'hang': setInterval(() => {}, 1000); break;
  case 'touch': fs.writeFileSync('touched.txt', 'x'); write(pass3); break;
  case 'collect': console.log('3 tests collected in 0.01s'); write(doc({ e: 0, f: 0, s: 0, t: 0 }, '')); break;
  case 'cells-ok': write(doc({ e: 0, f: 0, s: 0, t: 3 }, tc('t_cell_a', '', 'tests.test_h') + tc('t_cell_b', '', 'tests.test_h') + tc('other'))); break;
  case 'cells-skip': write(doc({ e: 0, f: 0, s: 1, t: 3 }, tc('t_cell_a', '', 'tests.test_h') + tc('t_cell_b', '<skipped type="pytest.skip"/>', 'tests.test_h') + tc('other'))); break;
  case 'cells-fail': write(doc({ e: 0, f: 1, s: 0, t: 3 }, tc('t_cell_a', '', 'tests.test_h') + tc('t_cell_b', '<failure message="boom">x</failure>', 'tests.test_h') + tc('other'))); break;
  case 'cells-error': write(doc({ e: 1, f: 0, s: 0, t: 3 }, tc('t_cell_a', '', 'tests.test_h') + tc('t_cell_b', '<error message="boom">x</error>', 'tests.test_h') + tc('other'))); break;
  case 'cells-absent': write(doc({ e: 0, f: 0, s: 0, t: 2 }, tc('t_cell_a', '', 'tests.test_h') + tc('other'))); break;
  default: process.exit(9);
}
`;

const PY = (over = {}) => ({
  name: 'pytest', kind: 'pytest', cwd: 'backend', launcher: [process.execPath], resolve_args: ['-e', 'console.log(process.execPath)'],
  python_args: ['fake-pytest.mjs'], argv_tail: ['mode=pass'], timeout_s: 60, ...over,
});
const SCRIPT = (name, file, over = {}) => ({ name, kind: 'script', cwd: '.', argv: ['node', file], timeout_s: 60, ...over });
const HARNESS = { when_diff_matches: ['supabase/migrations/**'], env: { PR_SEC_01_DB_HARNESS: '1', PR_SEC_01_REQUIRE_HARNESS: '1' }, required_testcase_manifest: 'supabase/tests/cells.json', timeout_s: 120 };

function defaultGates(mode = 'pass', pyOver = {}) {
  const auto = { autonomy: 'autonomous', status: 'CONFIGURED' };
  return {
    gates: [
      { id: 'G-PYT', ...auto, runner: { steps: [PY({ argv_tail: [`mode=${mode}`], ...pyOver })] } },
      { id: 'G-SCR', ...auto, runner: { steps: [SCRIPT('scan', 'scripts/ok.mjs')] } },
      { id: 'G-SCRF', ...auto, runner: { steps: [SCRIPT('scan', 'scripts/fail.mjs')] } },
      { id: 'G-TWO', ...auto, runner: { steps: [SCRIPT('scope-check', 'scripts/ok.mjs'), { name: 'manifest-scope', kind: 'builtin', builtin: 'manifest-scope' }] } },
      { id: 'G-HARN', ...auto, runner: { steps: [PY({ argv_tail: [`mode=${mode}`] })], conditional: HARNESS } },
      { id: 'G-BLOCKED', autonomy: 'approval', status: 'BLOCKED', runner: { steps: [SCRIPT('scan', 'scripts/ok.mjs')] } },
      { id: 'G-NORUN', ...auto },
    ],
  };
}

function makeFixture({ mode = 'pass', pyOver = {}, changeSet = null, withBaseline = false, allow = 'node', gates = null } = {}) {
  const root = tmp();
  const tmpd = tmp();
  rg.securePrivateDir(tmpd); // the runner rejects a shared TEMP; a fresh mkdtemp inherits its parent's ACL on Windows
  git(root, 'init', '-q');
  put(root, '.gitignore', '.claude/\n');
  put(root, 'backend/fake-pytest.mjs', FAKE_PYTEST);
  put(root, 'scripts/ok.mjs', 'process.exit(0);\n');
  put(root, 'scripts/fail.mjs', 'process.exit(3);\n');
  put(root, 'supabase/tests/cells.json', JSON.stringify({ cells: ['t_cell_a', 't_cell_b'] }));
  git(root, 'add', '-A');
  git(root, 'commit', '-q', '-m', 'init');
  const orch = path.join(root, '.claude', 'orchestration');
  fs.mkdirSync(orch, { recursive: true });
  for (const f of ['run-gate.mjs', 'ledger-core.mjs', 'ledger.mjs', 'patterns.mjs']) fs.copyFileSync(path.join(REAL_ORCH, f), path.join(orch, f));
  put(root, '.claude/orchestration/gates.json', JSON.stringify(gates || defaultGates(mode, pyOver)));
  const entry = allow === 'node' ? { path: process.execPath, sha256: NODE_HASH } : allow;
  put(root, '.claude/orchestration/trusted-interpreters.json', typeof allow === 'string' && allow !== 'node' ? allow : JSON.stringify({ schema: 1, interpreters: [entry] }));
  const cs = changeSet || { run_id: RUN_ID, allowed_paths: ['backend/**', 'scripts/**', 'supabase/**'], forbidden_paths: [] };
  const fx = { root, tmpd, orch, cs };
  if (withBaseline) {
    const m0 = core.hSetManifest(root);
    const out = tmp();
    const baseline = put(out, 'm0.txt', m0.text);
    cs.baseline_manifest = { path: baseline, sha256: h(m0.text) };
    cs.allowed_paths = [...cs.allowed_paths, '.claude/orchestration/tests/**'];
  }
  const runDir = path.join(orch, 'runs', RUN_ID);
  fs.mkdirSync(runDir, { recursive: true });
  fx.csRaw = JSON.stringify(cs, null, 2) + '\n';
  fs.writeFileSync(path.join(runDir, 'change-set.json'), fx.csRaw);
  fx.ledger = path.join(runDir, 'ledger.json');
  fs.writeFileSync(fx.ledger, JSON.stringify({ run_id: RUN_ID, objective: 't', status: 'RUNNING', tasks: [], evidence: [], events: [] }));
  fs.writeFileSync(path.join(orch, 'ACTIVE_RUN'), RUN_ID + '\n');
  fs.mkdirSync(path.join(orch, 'approvals'), { recursive: true });
  fx.approval = path.join(orch, 'approvals', `${RUN_ID}.json`);
  fs.writeFileSync(fx.approval, JSON.stringify({ run_id: RUN_ID, change_set_sha256: h(fx.csRaw), approved_at: new Date().toISOString(), approved_by: 'test' }));
  return fx;
}
const run = (fx, args, extraEnv = {}) => spawnSync(process.execPath, [path.join(fx.orch, 'run-gate.mjs'), ...(Array.isArray(args) ? args : [args])], {
  cwd: fx.root, env: { ...process.env, TMP: fx.tmpd, TEMP: fx.tmpd, TMPDIR: fx.tmpd, ...extraEnv }, encoding: 'utf8', timeout: 180000,
});
const evidence = (fx) => JSON.parse(fs.readFileSync(fx.ledger, 'utf8')).evidence;
const last = (fx) => { const e = evidence(fx); return e[e.length - 1]; };
const gateDir = (fx) => { const d = fs.readdirSync(fx.tmpd).filter((n) => n.startsWith('gate-')); assert.equal(d.length, 1, 'exactly one run directory'); return path.join(fx.tmpd, d[0]); };
const seenEnv = (fx) => JSON.parse(fs.readFileSync(path.join(gateDir(fx), 'env.json'), 'utf8'));
function acceptCtx(fx, gate, over = {}) {
  const def = JSON.parse(fs.readFileSync(path.join(fx.orch, 'gates.json'), 'utf8')).gates.find((g) => g.id === gate);
  return { gate, ledgerRun: RUN_ID, changeSetSha256: h(fx.csRaw), changeSet: fx.cs, stepNames: core.runnerStepNames(def), taskStartedAtMs: Date.now() - 600_000, nowMs: Date.now(), current: core.computeBindings(fx.cs, fx.root), ...over };
}

// ---------------------------------------------------------------- unit: junit extraction

const J = (suiteAttrs, body) => `<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" ${suiteAttrs} time="0.1">${body}</testsuite></testsuites>`;
test('parseJunit counts elements independently and agrees with consistent attributes', () => {
  const p = rg.parseJunit(J('errors="0" failures="1" skipped="1" tests="3"', '<testcase classname="a.b" name="x"/><testcase classname="a.b" name="y"><failure message="m">t</failure></testcase><testcase classname="a.b" name="z"><skipped type="s"/></testcase>'));
  assert.equal(p.ok, true, p.error);
  assert.deepEqual(p.totals, { tests: 3, failures: 1, errors: 0, skipped: 1 });
  assert.deepEqual(p.cases.map((c) => [c.name, c.failed, c.errored, c.skipped]), [['x', false, false, false], ['y', true, false, false], ['z', false, false, true]]);
});

test('parseJunit rejects empty, non-xml, truncated, unbalanced, missing-attribute and disagreeing totals', () => {
  const good = J('errors="0" failures="0" skipped="0" tests="1"', '<testcase classname="a" name="x"/>');
  assert.equal(rg.parseJunit(good).ok, true);
  const bad = {
    empty: '', blank: '  \n', 'not xml': 'hello', 'wrong root': '<html></html>', truncated: good.slice(0, -20), 'no close': good.replace('</testsuites>', ''),
    'attr missing': good.replace(' skipped="0"', ''), 'attr not int': good.replace('tests="1"', 'tests="x"'), 'tests mismatch': good.replace('tests="1"', 'tests="2"'),
    'failures mismatch': good.replace('failures="0"', 'failures="1"'), 'errors mismatch': good.replace('errors="0"', 'errors="1"'), 'skipped mismatch': good.replace('skipped="0"', 'skipped="1"'),
    'element outside testcase': J('errors="0" failures="1" skipped="0" tests="1"', '<testcase classname="a" name="x"/><failure message="m"/>'),
    'unbalanced suite': good.replace('</testsuite>', ''),
  };
  for (const [name, text] of Object.entries(bad)) assert.equal(rg.parseJunit(text).ok, false, name);
  assert.equal(rg.parseJunit(null).ok, false);
});

test('parseJunit ignores markup that only appears inside CDATA or comments, and unescapes attribute entities', () => {
  const p = rg.parseJunit(J('errors="0" failures="0" skipped="0" tests="1"', '<!-- <testcase name="c"/><failure/> --><testcase classname="a&amp;b" name="x&lt;1&gt;"><system-out><![CDATA[<testcase name="f"/><failure>no</failure>]]></system-out></testcase>'));
  assert.equal(p.ok, true, p.error);
  assert.equal(p.cases.length, 1);
  assert.equal(p.cases[0].name, 'x<1>');
  assert.equal(p.cases[0].classname, 'a&b');
});

// ---------------------------------------------------------------- unit: environment and runner block validation

test('scrubEnv keeps only the allowlist, fixes the Python encoding, and never forwards pytest/python injection variables', () => {
  const parent = { PATH: 'p', Path: 'p2', SYSTEMROOT: 's', TEMP: 't', PYTEST_ADDOPTS: '-k x', PYTEST_PLUGINS: 'evil', PYTHONPATH: 'x', PYTHONSTARTUP: 'x', PYTHONHOME: 'x', PYTHONINSPECT: '1', NODE_OPTIONS: '--require x', SECRET_TOKEN: 's', PYTHONIOENCODING: 'latin-1' };
  const e = rg.scrubEnv(parent, { PR_X: '1' });
  for (const k of ['PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME', 'PYTHONINSPECT', 'NODE_OPTIONS', 'SECRET_TOKEN']) assert.ok(!(k in e), k);
  assert.equal(e.PYTHONIOENCODING, 'utf-8');
  assert.equal(e.PR_X, '1');
  assert.equal(e.PATH, 'p');
  assert.equal(e.SYSTEMROOT, 's');
});

test('validateRunnerBlock accepts the supported shapes and rejects malformed ones', () => {
  const ok = (def) => assert.deepEqual(rg.validateRunnerBlock(def), [], JSON.stringify(def));
  const no = (def, why) => assert.ok(rg.validateRunnerBlock(def).length > 0, why);
  ok({ runner: { steps: [PY()] } });
  ok({ runner: { steps: [SCRIPT('scan', 'x.mjs'), { name: 'manifest-scope', kind: 'builtin', builtin: 'manifest-scope' }] } });
  ok({ runner: { steps: [PY()], conditional: HARNESS } });
  no({}, 'no runner'); no({ runner: {} }, 'no steps'); no({ runner: { steps: [] } }, 'empty steps'); no({ runner: { steps: 'x' } }, 'steps not array');
  no({ runner: { steps: [PY(), PY()] } }, 'two pytest steps');
  no({ runner: { steps: [SCRIPT('a', 'x.mjs'), SCRIPT('a', 'y.mjs')] } }, 'duplicate names');
  no({ runner: { steps: [SCRIPT('Bad Name', 'x.mjs')] } }, 'bad name');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), argv: ['python', 'x.py'] }] } }, 'script argv0 must be node');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), argv: 'node x' }] } }, 'argv must be an array');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), argv: ['node', 5] }] } }, 'argv entries strings');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), cwd: '..' }] } }, 'cwd escapes');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), cwd: '/abs' }] } }, 'cwd absolute');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), cwd: 'C:\\x' }] } }, 'cwd drive');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), timeout_s: 0 }] } }, 'timeout 0');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), timeout_s: 'x' }] } }, 'timeout str');
  no({ runner: { steps: [{ ...SCRIPT('a', 'x.mjs'), timeout_s: 999999 }] } }, 'timeout huge');
  no({ runner: { steps: [{ name: 'x', kind: 'shell', argv: ['node'] }] } }, 'unknown kind');
  no({ runner: { steps: [{ name: 'manifest-scope', kind: 'builtin', builtin: 'other' }] } }, 'unknown builtin');
  no({ runner: { steps: [PY({ argv_tail: 'tests' })] } }, 'argv_tail array');
  no({ runner: { steps: [PY({ launcher: [] })] } }, 'launcher non-empty');
  no({ runner: { steps: [PY()], conditional: { ...HARNESS, env: { A: 5 } } } }, 'conditional env strings');
  no({ runner: { steps: [PY()], conditional: { ...HARNESS, required_testcase_manifest: '../x' } } }, 'manifest path escapes');
  no({ runner: { steps: [SCRIPT('a', 'x.mjs')], conditional: HARNESS } }, 'conditional needs a pytest step');
});

test('freshRunDir creates an empty private directory and assertEmptyDir refuses a directory that already has files', () => {
  const base = tmp();
  rg.securePrivateDir(base);
  const d = rg.freshRunDir(base);
  assert.ok(fs.statSync(d).isDirectory());
  assert.equal(fs.readdirSync(d).length, 0);
  assert.ok(path.basename(d).startsWith('gate-'));
  assert.notEqual(rg.freshRunDir(base), d);
  fs.writeFileSync(path.join(d, 'planted.xml'), 'x');
  assert.throws(() => rg.assertEmptyDir(d));
});

// ---------------------------------------------------------------- run-directory hardening (Windows ACL and POSIX mode)

const SID = 'S-1-5-21-1111111111-2222222222-3333333333-1002';
const OTHER = 'S-1-5-21-1111111111-2222222222-3333333333-1999';
const sddl = (flags, ...aces) => `D:${flags}${aces.map((a) => `(${a})`).join('')}`;
// A fake Windows ops object: whoami returns SID; icacls /save writes the SDDL registered for that directory (UTF-16LE, no BOM, like the real tool);
// icacls /inheritance:r and /grant:r succeed and are recorded. `acls` maps a directory to the SDDL its /save returns.
function winOps({ acls = {}, failOn = null, sid = SID, saveText = null } = {}) {
  const calls = [];
  const exec = (file, args) => {
    calls.push([path.basename(file).toLowerCase(), ...args]);
    if (failOn && [file, ...args].join(' ').includes(failOn)) return { status: 5, stdout: '', stderr: 'denied' };
    if (/whoami/i.test(file)) return { status: 0, stdout: `"host\\user","${sid}"\n`, stderr: '' };
    const si = args.indexOf('/save');
    if (si !== -1) {
      const target = args[si + 1];
      const text = saveText !== null ? saveText : `${args[0]}\n${acls[args[0]] || acls['*'] || ''}\n\n`;
      fs.writeFileSync(target, Buffer.from(text, 'utf16le'));
    }
    return { status: 0, stdout: '', stderr: '' };
  };
  return { platform: 'win32', fs, exec, systemRoot: process.env.SystemRoot || process.env.SYSTEMROOT || 'C:\\Windows', calls, getuid: undefined, icaclsExists: () => true };
}
const PRIVATE_SDDL = sddl('PAI', `A;OICI;FA;;;${SID}`);
const OPEN_BASE_SDDL = sddl('AI', 'A;OICIID;FA;;;WD', `A;OICIID;FA;;;${SID}`);

test('Windows: a fresh run directory is protected, granted to the current user only, and the resulting ACL is verified from locale-independent SDDL', () => {
  const base = tmp();
  const ops = winOps({ acls: { '*': PRIVATE_SDDL } });
  const d = rg.freshRunDir(base, ops);
  const names = ops.calls.map((c) => c.join(' '));
  assert.ok(names.some((c) => c.includes('/inheritance:r')), 'inheritance removed');
  assert.ok(names.some((c) => c.includes(`/grant:r *${SID}:(OI)(CI)F`)), 'only the current user is granted');
  assert.ok(ops.calls.every((c) => c[0] === 'icacls.exe' || c[0] === 'whoami.exe'), 'only the two system tools are used');
  assert.equal(fs.readdirSync(d).length, 0, 'the temporary ACL snapshot is removed');
});

test('Windows: an unsafe BASE directory (anyone can write) is rejected, and the run directory just created is removed again', () => {
  const base = tmp();
  const ops = winOps({ acls: { '*': PRIVATE_SDDL, [base]: OPEN_BASE_SDDL } });
  assert.throws(() => rg.freshRunDir(base, ops), /unsafe|writable/i);
  assert.deepEqual(fs.readdirSync(base), [], 'no leftover gate directory');
});

test('Windows: base directories granting write only to SYSTEM, Administrators or the current user, and read-only to others, are accepted', () => {
  const base = tmp();
  const okBase = sddl('PAI', 'A;OICI;FA;;;SY', 'A;OICI;FA;;;BA', `A;OICI;FA;;;${SID}`, 'A;OICI;0x1200a9;;;AC', `A;OICI;FR;;;${OTHER}`);
  assert.doesNotThrow(() => rg.freshRunDir(base, winOps({ acls: { '*': PRIVATE_SDDL, [base]: okBase } })));
});

test('Windows: a base granting any write-capable right to a foreign principal is rejected, whatever the right is spelled as', () => {
  for (const ace of ['A;OICI;FA;;;WD', 'A;OICI;FA;;;BU', 'A;OICI;FA;;;AU', `A;OICI;FA;;;${OTHER}`, `A;OICI;FW;;;${OTHER}`, `A;OICI;0x1301bf;;;${OTHER}`, `A;OICI;GA;;;${OTHER}`,
    `A;OICI;GW;;;${OTHER}`, `A;OICI;0x40040;;;${OTHER}`, `A;OICI;0x10000;;;${OTHER}`, `A;OICI;0x80000;;;${OTHER}`, `A;OICI;0x40;;;${OTHER}`, `A;OICI;FRFW;;;${OTHER}`]) {
    const base = tmp();
    const ops = winOps({ acls: { '*': PRIVATE_SDDL, [base]: sddl('PAI', `A;OICI;FA;;;${SID}`, ace) } });
    assert.throws(() => rg.freshRunDir(base, ops), /unsafe|writable/i, ace);
  }
});

test('Windows: fails closed when security cannot be established (tool missing, command fails, unparsable or too-open result, no grant for the user)', () => {
  const mk = () => { const b = tmp(); return b; };
  let b = mk();
  assert.throws(() => rg.freshRunDir(b, { ...winOps({ acls: { '*': PRIVATE_SDDL } }), icaclsExists: () => false }), /was not found/i);
  b = mk();
  assert.throws(() => rg.freshRunDir(b, winOps({ acls: { '*': PRIVATE_SDDL }, failOn: '/inheritance:r' })));
  b = mk();
  assert.throws(() => rg.freshRunDir(b, winOps({ acls: { '*': PRIVATE_SDDL }, failOn: '/grant:r' })));
  b = mk();
  assert.throws(() => rg.freshRunDir(b, winOps({ acls: { '*': PRIVATE_SDDL }, failOn: 'whoami' })));
  b = mk();
  assert.throws(() => rg.freshRunDir(b, winOps({ sid: 'not-a-sid', acls: { '*': PRIVATE_SDDL } })));
  for (const bad of ['', 'garbage', 'D:PAI(A;OICI;FA;;;SY', 'D:PAI(A;OICI;ZZ;;;SY)', 'D:PAI(A;OICI)', 'D:PAI(A;OICI;FA;;;SY)junk']) {
    b = mk();
    assert.throws(() => rg.freshRunDir(b, winOps({ acls: { '*': bad } })), undefined, JSON.stringify(bad));
  }
  b = mk(); // the run directory still inherits (not protected)
  assert.throws(() => rg.freshRunDir(b, winOps({ acls: { '*': sddl('AI', `A;OICIID;FA;;;${SID}`) } })), /inherit|protected/i);
  b = mk(); // the run directory is protected but grants a foreign principal
  assert.throws(() => rg.freshRunDir(b, winOps({ acls: { '*': sddl('PAI', `A;OICI;FA;;;${SID}`, `A;OICI;FR;;;${OTHER}`) } })), /grants access/i);
  b = mk(); // protected, but the current user lost access
  assert.throws(() => rg.freshRunDir(b, winOps({ acls: { '*': sddl('PAI', 'A;OICI;FA;;;SY') } })), /current user/i);
  assert.deepEqual(fs.readdirSync(b), [], 'a failed hardening leaves no directory behind');
});

test('real OS: a fresh run directory is private (Windows: protected ACL without Everyone/Users; POSIX: mode 0700) and an open base is rejected', () => {
  const base = tmp();
  rg.securePrivateDir(base);
  const d = rg.freshRunDir(base);
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(d).mode & 0o777, 0o700);
    const open = tmp();
    fs.chmodSync(open, 0o777);
    assert.throws(() => rg.freshRunDir(open), /unsafe|writable/i);
    assert.deepEqual(fs.readdirSync(open), []);
    return;
  }
  const sys32 = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32');
  const out = path.join(d, 'acl.txt');
  assert.equal(spawnSync(path.join(sys32, 'icacls.exe'), [d, '/save', out]).status, 0);
  const text = fs.readFileSync(out).toString('utf16le');
  assert.match(text, /D:P/);
  assert.ok(!/;(WD|BU|AU|AN)\)/.test(text), text);
  fs.rmSync(out);
  const open = tmp();
  assert.equal(spawnSync(path.join(sys32, 'icacls.exe'), [open, '/grant', '*S-1-1-0:(OI)(CI)F']).status, 0); // Everyone: full control
  assert.throws(() => rg.freshRunDir(open), /unsafe|writable/i);
  assert.deepEqual(fs.readdirSync(open), [], 'no gate directory left in the rejected base');
});

const st = (mode, uid = 1000, over = {}) => ({ mode: 0o040000 | mode, uid, isDirectory: () => true, isSymbolicLink: () => false, ...over });
function posixOps({ base = 0o700, run = null, uid = 1000, runUid = null, symlink = false } = {}) {
  const calls = [];
  const state = { mode: run };
  const fake = {
    statSync: () => st(base, uid),
    lstatSync: () => st(state.mode ?? 0o700, runUid ?? uid, { isSymbolicLink: () => symlink }),
    chmodSync: (_p, m) => { calls.push(['chmod', m]); if (run === null) state.mode = m; },
    mkdtempSync: (p) => fs.mkdtempSync(p),
    rmdirSync: (p) => fs.rmdirSync(p),
    readdirSync: (p) => fs.readdirSync(p),
  };
  return { platform: 'linux', fs: fake, exec: () => { throw new Error('no system tool is needed on POSIX'); }, getuid: () => uid, calls };
}

test('POSIX: the run directory is forced to 0700 and verified (owner, mode, not a symlink); safe bases are accepted', () => {
  for (const base of [0o700, 0o755, 0o1777, 0o1770]) {
    const b = tmp();
    const ops = posixOps({ base });
    const d = rg.freshRunDir(b, ops);
    assert.deepEqual(ops.calls, [['chmod', 0o700]], `base ${base.toString(8)}`);
    assert.equal(fs.readdirSync(d).length, 0);
  }
});

test('POSIX: a group- or world-writable base without the sticky bit is rejected; so are a wrong owner, a loose mode that cannot be tightened, and a symlink', () => {
  for (const base of [0o777, 0o770, 0o722, 0o757, 0o775]) {
    const b = tmp();
    assert.throws(() => rg.freshRunDir(b, posixOps({ base })), /unsafe|writable/i, base.toString(8));
    assert.deepEqual(fs.readdirSync(b), [], 'rejected base left clean');
  }
  assert.throws(() => rg.freshRunDir(tmp(), posixOps({ runUid: 0 })), /not owned/i);
  assert.throws(() => rg.freshRunDir(tmp(), posixOps({ run: 0o755 })), /mode|private/i); // chmod did not take effect
  assert.throws(() => rg.freshRunDir(tmp(), posixOps({ symlink: true })), /symbolic|symlink/i);
});

test('the runner refuses (exit 2, no evidence) when TEMP is an unsafe, shared directory', () => {
  const fx = makeFixture();
  const unsafe = tmp();
  if (process.platform === 'win32') assert.equal(spawnSync(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'icacls.exe'), [unsafe, '/grant', '*S-1-1-0:(OI)(CI)F']).status, 0);
  else fs.chmodSync(unsafe, 0o777);
  const r = run(fx, 'G-SCR', { TMP: unsafe, TEMP: unsafe, TMPDIR: unsafe });
  assert.equal(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stderr, /unsafe|writable/i);
  assert.equal(evidence(fx).length, 0);
});

test('environment scrubbing is unchanged by the hardening: only the allowlist reaches the child', () => {
  const fx = makeFixture();
  assert.equal(run(fx, 'G-PYT', { PYTEST_ADDOPTS: '-k nothing', PYTHONPATH: 'C:\\evil', SECRET_TOKEN: 'zzz' }).status, 0);
  const env = seenEnv(fx);
  assert.equal(env.addopts, null); assert.equal(env.pythonpath, null); assert.equal(env.secret, null); assert.equal(env.enc, 'utf-8');
});

// ---------------------------------------------------------------- manifest-scan (G-SCAN coverage of ignored governance files)

const FAKE_KEY = ['sk_live_', 'abcdefghijklmnop1234'].join(''); // assembled at run time so this file never contains the literal
const SCAN_GATES = () => ({ gates: [{ id: 'G-SCANX', autonomy: 'autonomous', status: 'CONFIGURED', runner: { steps: [SCRIPT('scan', 'scripts/ok.mjs'), { name: 'manifest-scan', kind: 'builtin', builtin: 'manifest-scan' }] } }] });
const scanFx = (over = {}) => makeFixture({ gates: SCAN_GATES(), withBaseline: true, ...over });
const sha = (s) => h(s);

test('manifest-scan RUN: scans exactly the added and modified governance files, passes when clean, and records which files in the step hash', () => {
  const fx = scanFx();
  put(fx.root, '.claude/orchestration/tests/new.test.mjs', 'const a = 1;\n');
  const tracked = path.join(fx.orch, 'gates.json');
  fs.appendFileSync(tracked, ' ');
  const r = run(fx, 'G-SCANX');
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /manifest-scan: clean \(2 governance file\(s\) scanned\)/);
  const e = last(fx);
  assert.deepEqual(e.steps.map((s) => s.name), ['scan', 'manifest-scan']);
  const files = [['orchestration/tests/new.test.mjs', sha('const a = 1;\n')], ['orchestration/gates.json', sha(fs.readFileSync(tracked))]].sort((x, y) => (x[0] < y[0] ? -1 : 1));
  assert.equal(e.steps[1].argv_sha256, sha(`builtin:manifest-scan:v1\n${files.map(([rel, hash]) => `${hash}  ${rel}`).join('\n')}\n`));
  assert.deepEqual(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-SCANX')), []);
});

test('manifest-scan catches a secret in an IGNORED governance file that scan.mjs --changed cannot see, without printing the value', () => {
  const fx = scanFx();
  put(fx.root, '.claude/orchestration/tests/leak.mjs', `const k = "${FAKE_KEY}";\n`);
  assert.equal(git(fx.root, 'status', '--porcelain=v1').trim(), '', 'git sees nothing: the change is in an ignored directory');
  const r = run(fx, 'G-SCANX');
  assert.equal(r.status, 1);
  assert.match(r.stdout, /BLOCKING orchestration\/tests\/leak\.mjs:1 secret:/);
  assert.ok(!(r.stdout + r.stderr).includes(FAKE_KEY), 'the matched value is never printed');
  assert.ok(!fs.readFileSync(fx.ledger, 'utf8').includes(FAKE_KEY), 'nor stored');
  const e = last(fx);
  assert.equal(e.result, 'FAIL');
  assert.equal(e.steps[1].exit_status, 1);
});

test('manifest-scan also scans MODIFIED baseline files, and .sql files get the SQL rules', () => {
  let fx = scanFx();
  fs.appendFileSync(path.join(fx.orch, 'ledger.mjs'), `\n// ${FAKE_KEY}\n`); // an existing baseline file (not parsed by the runner), now modified
  assert.equal(run(fx, 'G-SCANX').status, 1);
  fx = scanFx();
  put(fx.root, '.claude/orchestration/tests/m.sql', 'DROP TABLE users;\n');
  assert.equal(run(fx, 'G-SCANX').status, 1);
});

test('manifest-scan refuses a vacuous PASS: a declared baseline with an empty diff is FAIL', () => {
  const fx = scanFx();
  const r = run(fx, 'G-SCANX');
  assert.equal(r.status, 1);
  assert.match(r.stdout, /nothing to scan|vacuous/i);
  assert.equal(last(fx).result, 'FAIL');
});

test('manifest-scan fails closed on an unusable baseline and on an unscannable (oversized) file', () => {
  let fx = scanFx();
  put(fx.root, '.claude/orchestration/tests/x.mjs', 'a');
  fs.rmSync(fx.cs.baseline_manifest.path);
  assert.equal(run(fx, 'G-SCANX').status, 1);
  assert.equal(last(fx).result, 'FAIL');
  fx = scanFx();
  put(fx.root, '.claude/orchestration/tests/big.txt', 'a'.repeat(2_000_001));
  const r = run(fx, 'G-SCANX');
  assert.equal(r.status, 1);
  assert.match(r.stdout, /too large|unscannable/i);
});

test('manifest-scan NOT_APPLICABLE (ordinary Change Set) passes with a distinct constant step hash; a .claude-capable scope without baseline FAILs', () => {
  const fx = makeFixture({ gates: SCAN_GATES() });
  assert.equal(run(fx, 'G-SCANX').status, 0);
  assert.equal(last(fx).steps[1].argv_sha256, sha('builtin:manifest-scan:not-applicable:v1'));
  const bad = makeFixture({ gates: SCAN_GATES(), changeSet: { run_id: RUN_ID, allowed_paths: ['backend/**', '.claude/orchestration/x.mjs'], forbidden_paths: [] } });
  assert.equal(run(bad, 'G-SCANX').status, 1);
  assert.equal(last(bad).result, 'FAIL');
});

test('scanGovernanceFiles: counts every file, fails closed on a read error, and never reports a file as scanned that was not read', () => {
  const root = tmp();
  put(root, '.claude/a.txt', 'clean\n');
  put(root, '.claude/b.txt', `x ${FAKE_KEY}\n`);
  let r = rg.scanGovernanceFiles(['a.txt', 'b.txt'], root);
  assert.equal(r.scanned, 2);
  assert.deepEqual(r.findings.map((f) => [f.rel, f.line]), [['b.txt', 1]]);
  assert.deepEqual(r.unreadable, []);
  r = rg.scanGovernanceFiles(['a.txt', 'missing.txt'], root);
  assert.equal(r.scanned, 1);
  assert.deepEqual(r.unreadable, ['missing.txt']);
  r = rg.scanGovernanceFiles(['a.txt'], root, () => { throw new Error('EACCES'); });
  assert.equal(r.scanned, 0);
  assert.deepEqual(r.unreadable, ['a.txt']);
});

test('validateRunnerBlock accepts the manifest-scan builtin only under its own name', () => {
  assert.deepEqual(rg.validateRunnerBlock({ runner: { steps: [SCRIPT('scan', 'x.mjs'), { name: 'manifest-scan', kind: 'builtin', builtin: 'manifest-scan' }] } }), []);
  assert.ok(rg.validateRunnerBlock({ runner: { steps: [{ name: 'other', kind: 'builtin', builtin: 'manifest-scan' }] } }).length > 0);
  assert.ok(rg.validateRunnerBlock({ runner: { steps: [{ name: 'manifest-scan', kind: 'builtin', builtin: 'manifest-scope' }] } }).length > 0);
});

// ---------------------------------------------------------------- integration: refusals (exit 2, no evidence)

test('refuses malformed gate ids and wrong argument counts without writing evidence', () => {
  const fx = makeFixture();
  for (const a of [[], ['G-PYT', 'G-SCR'], ['G-PYT; rm -rf x'], ['../x'], ['g-pyt'], [''], ['G-A G-B'], ['G-PYT\n'], ['--help'], ['G_PYT']]) {
    const r = run(fx, a);
    assert.equal(r.status, 2, JSON.stringify(a));
  }
  assert.equal(evidence(fx).length, 0);
});

test('refuses unknown gates, gates without a runner block, and non-autonomous gates', () => {
  const fx = makeFixture();
  for (const g of ['G-UNKNOWN', 'G-NORUN', 'G-BLOCKED']) assert.equal(run(fx, g).status, 2, g);
  assert.equal(evidence(fx).length, 0);
});

test('refuses a gate whose runner block is malformed', () => {
  const fx = makeFixture({ gates: { gates: [{ id: 'G-BAD', autonomy: 'autonomous', runner: { steps: [{ name: 'a', kind: 'script', cwd: '..', argv: ['node', 'x'], timeout_s: 5 }] } }] } });
  assert.equal(run(fx, 'G-BAD').status, 2);
  assert.equal(evidence(fx).length, 0);
});

test('refuses without an active run, without approval, and after the Change Set changed post-approval', () => {
  let fx = makeFixture();
  fs.writeFileSync(path.join(fx.orch, 'ACTIVE_RUN'), '');
  assert.equal(run(fx, 'G-SCR').status, 2);
  fx = makeFixture();
  fs.rmSync(fx.approval);
  assert.equal(run(fx, 'G-SCR').status, 2);
  fx = makeFixture();
  fs.appendFileSync(path.join(fx.orch, 'runs', RUN_ID, 'change-set.json'), ' ');
  assert.equal(run(fx, 'G-SCR').status, 2);
  assert.equal(evidence(fx).length, 0);
});

test('refuses when git state is unreadable or a bound file is missing', () => {
  let fx = makeFixture();
  fs.rmSync(path.join(fx.root, '.git'), { recursive: true, force: true });
  assert.equal(run(fx, 'G-SCR').status, 2);
  fx = makeFixture();
  fs.rmSync(path.join(fx.orch, 'trusted-interpreters.json'));
  assert.equal(run(fx, 'G-SCR').status, 2);
  assert.equal(evidence(fx).length, 0);
});

// ---------------------------------------------------------------- integration: genuine PASS and the evidence it writes

test('genuine pytest PASS writes one strict schema-1 entry bound to the run, Change Set, interpreter and junit file; done-side acceptance succeeds', () => {
  const fx = makeFixture({ mode: 'skip' });
  const r = run(fx, 'G-PYT');
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const all = evidence(fx);
  assert.equal(all.length, 1);
  const e = all[0];
  assert.deepEqual(core.validateEvidenceV1(e), { ok: true, errors: [] });
  assert.equal(e.source, 'runner'); assert.equal(e.schema, 1); assert.equal(e.gate, 'G-PYT'); assert.deepEqual(e.covers, ['G-PYT']);
  assert.equal(e.kind, 'pytest'); assert.equal(e.result, 'PASS'); assert.equal(e.exit_status, 0);
  assert.deepEqual(e.counts, { tests: 3, failures: 0, errors: 0, skipped: 1 });
  assert.equal(e.ledger_run, RUN_ID);
  assert.equal(e.change_set_sha256, h(fx.csRaw));
  assert.equal(e.interpreter.sha256, NODE_HASH);
  assert.equal(path.resolve(e.interpreter.path).toLowerCase(), path.resolve(process.execPath).toLowerCase());
  assert.equal(e.junit_sha256, h(fs.readFileSync(path.join(gateDir(fx), 'junit.xml'))));
  assert.equal(e.required_cells, null);
  assert.equal(e.baseline_manifest_sha256, null);
  assert.deepEqual(e.steps.map((s) => s.name), ['pytest']);
  assert.deepEqual(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-PYT')), []);
  assert.match(e.run_id, /^[0-9a-f-]{36}$/);
});

test('runner injects --junitxml (inside a fresh private run directory) and -p no:cacheprovider, and runs in the configured cwd', () => {
  const fx = makeFixture();
  assert.equal(run(fx, 'G-PYT').status, 0);
  const env = seenEnv(fx);
  const jx = env.argv.find((a) => a.startsWith('--junitxml='));
  assert.ok(jx.slice('--junitxml='.length).startsWith(gateDir(fx)));
  assert.ok(env.argv.join(' ').includes('-p no:cacheprovider'));
  assert.equal(path.basename(env.cwd), 'backend');
});

test('genuine script PASS writes a kind:script entry with null counts, interpreter and junit hash', () => {
  const fx = makeFixture();
  assert.equal(run(fx, 'G-SCR').status, 0);
  const e = last(fx);
  assert.deepEqual(core.validateEvidenceV1(e), { ok: true, errors: [] });
  assert.equal(e.kind, 'script'); assert.equal(e.counts, null); assert.equal(e.interpreter, null); assert.equal(e.junit_sha256, null);
  assert.deepEqual(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-SCR')), []);
});

test('a non-zero script exit is FAIL with the exit status recorded, and the runner exits 1', () => {
  const fx = makeFixture();
  const r = run(fx, 'G-SCRF');
  assert.equal(r.status, 1);
  const e = last(fx);
  assert.equal(e.result, 'FAIL'); assert.equal(e.exit_status, 3);
  assert.ok(core.validateEvidenceV1(e).ok);
  assert.ok(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-SCRF')).length > 0);
});

// ---------------------------------------------------------------- integration: FAIL / UNKNOWN matrix

const matrix = [
  ['fail-junit', 'FAIL', 'exit 0 with junit failures'],
  ['error-junit', 'FAIL', 'exit 0 with junit errors'],
  ['fail-exit', 'FAIL', 'exit 1 with an all-pass junit file (status wins)'],
  ['missing', 'UNKNOWN', 'junit missing'],
  ['truncated', 'UNKNOWN', 'junit truncated'],
  ['mismatch', 'UNKNOWN', 'junit totals disagree with elements'],
  ['zero', 'UNKNOWN', 'zero tests'],
];
for (const [mode, want, why] of matrix) {
  test(`pytest ${why} is ${want} and can never satisfy a gate`, () => {
    const fx = makeFixture({ mode });
    const r = run(fx, 'G-PYT');
    assert.equal(r.status, 1);
    const e = last(fx);
    assert.equal(e.result, want);
    assert.ok(core.validateEvidenceV1(e).ok, JSON.stringify(core.validateEvidenceV1(e)));
    assert.ok(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-PYT')).length > 0);
  });
}

test('markup inside CDATA cannot inflate or hide results: a CDATA-only fake failure still yields a genuine PASS', () => {
  const fx = makeFixture({ mode: 'cdata' });
  assert.equal(run(fx, 'G-PYT').status, 0);
  assert.deepEqual(last(fx).counts, { tests: 1, failures: 0, errors: 0, skipped: 0 });
});

test('a hung child is killed at the timeout and recorded UNKNOWN', () => {
  const fx = makeFixture({ mode: 'hang', pyOver: { timeout_s: 2 } });
  const r = run(fx, 'G-PYT');
  assert.equal(r.status, 1);
  const e = last(fx);
  assert.equal(e.result, 'UNKNOWN'); assert.equal(e.exit_status, null);
  assert.equal(e.steps[0].exit_status, null);
  assert.equal(e.counts, null);
});

test('a tree change during the run makes the result UNKNOWN', () => {
  const fx = makeFixture({ mode: 'touch' });
  assert.equal(run(fx, 'G-PYT').status, 1);
  const e = last(fx);
  assert.equal(e.result, 'UNKNOWN');
  assert.ok(core.validateEvidenceV1(e).ok);
});

test('a .claude evidence-bound file changing during the run makes the result UNKNOWN', () => {
  const fx = makeFixture({ mode: 'pass', gates: { gates: [{ id: 'G-MUT', autonomy: 'autonomous', runner: { steps: [SCRIPT('scan', 'scripts/mutate.mjs')] } }] } });
  put(fx.root, 'scripts/mutate.mjs', `import fs from 'node:fs'; fs.appendFileSync(${JSON.stringify(path.join(fx.orch, 'gates.json'))}, ' ');\n`);
  git(fx.root, 'add', '-A'); git(fx.root, 'commit', '-q', '-m', 'mutate');
  assert.equal(run(fx, 'G-MUT').status, 1);
  assert.equal(last(fx).result, 'UNKNOWN');
});

test('collect-only: PASS needs exit 0, a valid junit file and the child-reported collected count', () => {
  const fx = makeFixture({ mode: 'collect', pyOver: { collect_only: true } });
  assert.equal(run(fx, 'G-PYT').status, 0);
  const e = last(fx);
  assert.deepEqual(e.counts, { tests: 3, failures: 0, errors: 0, skipped: 0 });
  assert.deepEqual(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-PYT')), []);
  const bad = makeFixture({ mode: 'pass', pyOver: { collect_only: true } }); // child prints no "N tests collected"
  assert.equal(run(bad, 'G-PYT').status, 1);
  assert.equal(last(bad).result, 'UNKNOWN');
});

// ---------------------------------------------------------------- integration: interpreter allowlist

test('an interpreter whose hash differs from the allowlist is UNKNOWN and the test is never run', () => {
  const fx = makeFixture({ allow: { path: process.execPath, sha256: 'f'.repeat(64) } });
  assert.equal(run(fx, 'G-PYT').status, 1);
  const e = last(fx);
  assert.equal(e.result, 'UNKNOWN');
  assert.equal(e.interpreter.sha256, NODE_HASH);
  assert.equal(fs.readdirSync(gateDir(fx)).includes('env.json'), false, 'child must not have run');
});

test('an interpreter whose path is not in the allowlist is UNKNOWN and the test is never run', () => {
  const fx = makeFixture({ allow: { path: path.join(os.tmpdir(), 'not-python.exe'), sha256: NODE_HASH } });
  assert.equal(run(fx, 'G-PYT').status, 1);
  assert.equal(last(fx).result, 'UNKNOWN');
  assert.equal(fs.readdirSync(gateDir(fx)).includes('env.json'), false);
});

test('an unreadable or malformed allowlist is UNKNOWN', () => {
  for (const allow of ['{not json', JSON.stringify({ schema: 2, interpreters: [] }), JSON.stringify({ schema: 1, interpreters: [] }), JSON.stringify({ schema: 1, interpreters: [{ path: 'relative.exe', sha256: NODE_HASH }] }),
    JSON.stringify({ schema: 1, interpreters: [{ path: process.execPath, sha256: 'ABC' }] }), JSON.stringify({ schema: 1, interpreters: [{ path: process.execPath, sha256: NODE_HASH, extra: 1 }] })]) {
    const fx = makeFixture({ allow });
    assert.equal(run(fx, 'G-PYT').status, 1, allow);
    assert.equal(last(fx).result, 'UNKNOWN', allow);
  }
});

test('a launcher that does not print an absolute existing file is UNKNOWN (a PATH shim cannot stand in)', () => {
  for (const printed of ['python', '', path.join(os.tmpdir(), 'does-not-exist.exe'), os.tmpdir()]) {
    const fx = makeFixture({ pyOver: { resolve_args: ['-e', `console.log(${JSON.stringify(printed)})`] } });
    assert.equal(run(fx, 'G-PYT').status, 1, JSON.stringify(printed));
    assert.equal(last(fx).result, 'UNKNOWN', JSON.stringify(printed));
    assert.equal(fs.readdirSync(gateDir(fx)).includes('env.json'), false);
  }
});

test('the resolved interpreter, not the launcher, runs the tests', () => {
  const fx = makeFixture({ pyOver: { launcher: [process.execPath], python_args: ['fake-pytest.mjs'] } });
  assert.equal(run(fx, 'G-PYT').status, 0);
  const e = last(fx);
  assert.equal(e.steps[0].argv_sha256, h(JSON.stringify([path.resolve(process.execPath), 'fake-pytest.mjs', 'mode=pass', `--junitxml=${path.join(gateDir(fx), 'junit.xml')}`, '-p', 'no:cacheprovider'])));
});

// ---------------------------------------------------------------- integration: environment scrubbing and result-path control

test('PYTEST_ADDOPTS, PYTHONPATH, PYTHONSTARTUP and other caller variables never reach the child', () => {
  const fx = makeFixture();
  assert.equal(run(fx, 'G-PYT', { PYTEST_ADDOPTS: '-k nothing', PYTHONPATH: 'C:\\evil', PYTHONSTARTUP: 'C:\\evil.py', SECRET_TOKEN: 'zzz', PYTHONIOENCODING: 'latin-1' }).status, 0);
  const env = seenEnv(fx);
  assert.equal(env.addopts, null); assert.equal(env.pythonpath, null); assert.equal(env.startup, null); assert.equal(env.secret, null);
  assert.equal(env.enc, 'utf-8');
  assert.equal(env.harness, null);
});

test('a planted junit file at a guessed location is ignored; only the child-written file in the fresh directory counts', () => {
  const fx = makeFixture({ mode: 'missing' });
  const good = '<?xml version="1.0"?><testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="1"><testcase classname="a" name="x"/></testsuite></testsuites>';
  for (const p of [path.join(fx.tmpd, 'junit.xml'), path.join(fx.root, 'junit.xml'), path.join(fx.root, 'backend', 'junit.xml')]) fs.writeFileSync(p, good);
  assert.equal(run(fx, 'G-PYT').status, 1);
  assert.equal(last(fx).result, 'UNKNOWN');
});

// ---------------------------------------------------------------- integration: manifest-scope (conditional)

test('manifest-scope RUN: unchanged and allowed additions PASS with baseline hashes recorded; out-of-scope additions FAIL', () => {
  let fx = makeFixture({ withBaseline: true });
  assert.equal(run(fx, 'G-TWO').status, 0);
  let e = last(fx);
  assert.deepEqual(e.steps.map((s) => s.name), ['scope-check', 'manifest-scope']);
  assert.equal(e.steps[1].exit_status, 0);
  assert.match(e.baseline_manifest_sha256, /^[0-9a-f]{64}$/); assert.match(e.h_manifest_sha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-TWO')), []);

  fx = makeFixture({ withBaseline: true });
  put(fx.root, '.claude/orchestration/tests/new.test.mjs', 'x');
  assert.equal(run(fx, 'G-TWO').status, 0);

  fx = makeFixture({ withBaseline: true });
  put(fx.root, '.claude/orchestration/extra.mjs', 'x');
  assert.equal(run(fx, 'G-TWO').status, 1);
  e = last(fx);
  assert.equal(e.result, 'FAIL');
  assert.equal(e.steps[1].exit_status, 1);
});

test('manifest-scope RUN: a missing baseline file or a pin mismatch is FAIL', () => {
  let fx = makeFixture({ withBaseline: true });
  fs.rmSync(fx.cs.baseline_manifest.path);
  assert.equal(run(fx, 'G-TWO').status, 1);
  assert.equal(last(fx).result, 'FAIL');
  fx = makeFixture({ withBaseline: true });
  fx.cs.baseline_manifest.sha256 = 'e'.repeat(64);
  const csRaw = JSON.stringify(fx.cs, null, 2) + '\n';
  fs.writeFileSync(path.join(fx.orch, 'runs', RUN_ID, 'change-set.json'), csRaw);
  fs.writeFileSync(fx.approval, JSON.stringify({ run_id: RUN_ID, change_set_sha256: h(csRaw), approved_at: new Date().toISOString(), approved_by: 'test' }));
  assert.equal(run(fx, 'G-TWO').status, 1);
  assert.equal(last(fx).result, 'FAIL');
});

test('manifest-scope NOT_APPLICABLE: an ordinary Change Set records the exact not-applicable step and PASSes on step 1 alone', () => {
  const fx = makeFixture();
  assert.equal(run(fx, 'G-TWO').status, 0);
  const e = last(fx);
  assert.deepEqual(e.steps[1], { name: 'manifest-scope', applicable: false, reason: 'no_baseline_declared_scope_excludes_claude', exit_status: null });
  assert.equal(e.baseline_manifest_sha256, null);
  assert.deepEqual(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-TWO')), []);
});

test('AC-5: step 1 behaves identically in every outcome (a failing scope step FAILs and stops before manifest-scope)', () => {
  const fx = makeFixture({ gates: { gates: [{ id: 'G-TWO', autonomy: 'autonomous', runner: { steps: [SCRIPT('scope-check', 'scripts/fail.mjs'), { name: 'manifest-scope', kind: 'builtin', builtin: 'manifest-scope' }] } }] } });
  assert.equal(run(fx, 'G-TWO').status, 1);
  const e = last(fx);
  assert.equal(e.result, 'FAIL');
  assert.deepEqual(e.steps.map((s) => s.name), ['scope-check']);
});

test('AC-2: without a baseline, a Change Set that may include .claude/ FAILs and writes a FAIL entry that revokes an earlier PASS', () => {
  const fx = makeFixture({ changeSet: { run_id: RUN_ID, allowed_paths: ['backend/**', '.claude/orchestration/x.mjs'], forbidden_paths: [] } });
  const ok = makeFixture();
  assert.equal(run(ok, 'G-TWO').status, 0);
  const earlierPass = last(ok);
  assert.equal(run(fx, 'G-TWO').status, 1);
  const e = last(fx);
  assert.equal(e.result, 'FAIL');
  assert.equal(e.steps[1].name, 'manifest-scope');
  assert.equal(e.steps[1].exit_status, 1);
  assert.equal(core.newestRunnerEntry([earlierPass, { ...e, at: new Date(Date.parse(earlierPass.at) + 1000).toISOString() }], 'G-TWO').result, 'FAIL');
});

// ---------------------------------------------------------------- integration: conditional harness

const withMigration = (fx) => put(fx.root, 'supabase/migrations/001_x.sql', 'select 1;\n');

test('conditional harness: when the diff matches, the runner sets the harness variables and requires every cell', () => {
  const fx = makeFixture({ mode: 'cells-ok' });
  withMigration(fx);
  assert.equal(run(fx, 'G-HARN').status, 0);
  const env = seenEnv(fx);
  assert.equal(env.harness, '1'); assert.equal(env.require, '1');
  const e = last(fx);
  assert.deepEqual(e.required_cells, { expected: 2, passed: 2 });
  assert.deepEqual(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-HARN', { requireCells: true })), []);
});

test('conditional harness: a skipped, absent or missing cell, or a missing or malformed manifest, is FAIL', () => {
  for (const mode of ['cells-skip', 'cells-absent']) {
    const fx = makeFixture({ mode });
    withMigration(fx);
    assert.equal(run(fx, 'G-HARN').status, 1, mode);
    const e = last(fx);
    assert.equal(e.result, 'FAIL', mode);
    assert.equal(e.required_cells.expected, 2); assert.ok(e.required_cells.passed < 2);
  }
  for (const body of [null, 'not json', '{}', '{"cells":[]}', '{"cells":"x"}', '{"cells":[5]}', '[]']) {
    const fx = makeFixture({ mode: 'cells-ok' });
    withMigration(fx);
    if (body === null) fs.rmSync(path.join(fx.root, 'supabase/tests/cells.json')); else fs.writeFileSync(path.join(fx.root, 'supabase/tests/cells.json'), body);
    assert.equal(run(fx, 'G-HARN').status, 1, String(body));
    assert.equal(last(fx).result, 'FAIL', String(body));
  }
});

test('required cells: a FAILED or ERRORED required cell makes the gate FAIL and is never accepted', () => {
  for (const mode of ['cells-fail', 'cells-error']) {
    const fx = makeFixture({ mode });
    withMigration(fx);
    assert.equal(run(fx, 'G-HARN').status, 1, mode);
    const e = last(fx);
    assert.equal(e.result, 'FAIL', mode);
    assert.ok(core.evidenceAcceptanceProblems(e, acceptCtx(fx, 'G-HARN', { requireCells: true })).length > 0, mode);
  }
});

test('required cells: duplicate, empty-string and blank manifests are FAIL, never a vacuous PASS', () => {
  for (const body of ['{"cells":["t_cell_a","t_cell_a"]}', '["t_cell_a","t_cell_a"]', '[""]', '{"cells":[""]}', '{"cells":["t_cell_a",""]}', '{"cells":null}', '{"other":["t_cell_a"]}', 'null', '"t_cell_a"', '']) {
    const fx = makeFixture({ mode: 'cells-ok' });
    withMigration(fx);
    fs.writeFileSync(path.join(fx.root, 'supabase/tests/cells.json'), body);
    assert.equal(run(fx, 'G-HARN').status, 1, JSON.stringify(body));
    const e = last(fx);
    assert.equal(e.result, 'FAIL', JSON.stringify(body));
    assert.equal(e.required_cells, null, 'a rejected manifest yields no satisfied-cell claim');
  }
});

function junitCases(cases) {
  const body = cases.join('');
  const n = (re) => (body.match(re) || []).length; // the strict parser demands attribute totals that equal the element counts
  return rg.parseJunit(J(`errors="${n(/<error\b/g)}" failures="${n(/<failure\b/g)}" skipped="${n(/<skipped\b/g)}" tests="${cases.length}"`, body));
}
const TC = (name, classname = 'tests.test_h', body = '') => (body ? `<testcase classname="${classname}" name="${name}">${body}</testcase>` : `<testcase classname="${classname}" name="${name}"/>`);

test('checkCells: only a clean, fully matching testcase satisfies a cell (skip, failure, error, absence, partial id all count as unsatisfied)', () => {
  const cells = ['t_a', 'tests.test_h.t_b', 't_c', 't_d', 't_e', 't_f[1]'];
  const parsed = junitCases([
    TC('t_a'), TC('t_b'), TC('t_c', 'tests.test_h', '<skipped type="pytest.skip"/>'), TC('t_d', 'tests.test_h', '<failure message="x"/>'),
    TC('t_e', 'tests.test_h', '<error message="x"/>'), TC('t_f[1]'), TC('t_f[2]'),
  ]);
  assert.equal(parsed.ok, true, parsed.error);
  assert.deepEqual(rg.checkCells(cells, parsed), { expected: 6, passed: 3 }); // t_a, classname.name t_b, t_f[1]
  assert.deepEqual(rg.checkCells(['t_f'], parsed), { expected: 1, passed: 0 }); // a prefix of a parametrised id is not a match
  assert.deepEqual(rg.checkCells(['missing'], parsed), { expected: 1, passed: 0 });
});

test('checkCells: a cell matched by several testcases needs every one of them clean', () => {
  const parsed = junitCases([TC('t_a'), TC('t_a', 'tests.other', '<skipped type="pytest.skip"/>')]);
  assert.deepEqual(rg.checkCells(['t_a'], parsed), { expected: 1, passed: 0 });
  const clean = junitCases([TC('t_a'), TC('t_a', 'tests.other')]);
  assert.deepEqual(rg.checkCells(['t_a'], clean), { expected: 1, passed: 1 });
});

test('loadCells: accepts an array or {cells:[...]} of unique non-empty strings and rejects everything else', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ge2-cells-'));
  const f = path.join(dir, 'cells.json');
  const load = (body) => { fs.writeFileSync(f, body); return rg.loadCells(f); };
  assert.deepEqual(load('["a","b"]'), ['a', 'b']);
  assert.deepEqual(load('{"cells":["a"]}'), ['a']);
  for (const bad of ['[]', '{"cells":[]}', '["a","a"]', '[""]', '[5]', '{"cells":"a"}', '{}', 'null', '', 'not json', '[["a"]]']) assert.throws(() => load(bad), JSON.stringify(bad));
  assert.throws(() => rg.loadCells(path.join(dir, 'absent.json')));
  fs.rmSync(dir, { recursive: true, force: true });
});

test('conditional harness: when the diff does not match, the variables are not set and required_cells is null', () => {
  const fx = makeFixture({ mode: 'pass' });
  put(fx.root, 'backend/new.py', 'x = 1\n');
  assert.equal(run(fx, 'G-HARN').status, 0);
  const env = seenEnv(fx);
  assert.equal(env.harness, null); assert.equal(env.require, null);
  assert.equal(last(fx).required_cells, null);
});
