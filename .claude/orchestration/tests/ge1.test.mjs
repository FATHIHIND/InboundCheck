// GE1: manifest hashing, tree digest, strict schema-1 evidence validation, shared applicability predicate.
// Run: node --test .claude/orchestration/tests/ge1.test.mjs   (Node >= 18, no dependencies, no Python, no network)
// All filesystem and git work happens in fresh temp directories; the real ledger is never touched.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as core from '../ledger-core.mjs';

const REAL_ORCH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const h = (s) => crypto.createHash('sha256').update(s).digest('hex');
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'ge1-'));
function put(root, rel, content = 'x') {
  const p = path.join(root, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  return p;
}
function git(root, ...args) {
  return execFileSync('git', ['-C', root, '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}
function gitRepo() {
  const root = tmp();
  git(root, 'init', '-q');
  put(root, 'a.txt', 'alpha\n');
  put(root, 'dir with space/b.txt', 'beta\n');
  git(root, 'add', '-A');
  git(root, 'commit', '-q', '-m', 'init');
  return root;
}

// ---------------------------------------------------------------- manifest: H-set / E-set

test('H-set excludes runs, approvals, ACTIVE_RUN, hook-debug.log, reports and worktrees; includes everything else', () => {
  const root = tmp();
  const keep = ['settings.json', 'settings.local.json', 'skills/s/SKILL.md', 'references/r.md', 'agents/a.md', 'hooks/g.mjs', 'hooks/tests/t.mjs',
    'orchestration/x.mjs', 'orchestration/gates.json', 'orchestration/tests/t.test.mjs', 'orchestration/runs.txt', 'orchestration/reports-notes.md'];
  const drop = ['orchestration/runs/r1/ledger.json', 'orchestration/approvals/r1.json', 'orchestration/ACTIVE_RUN', 'orchestration/hook-debug.log',
    'reports/final.md', 'worktrees/w/file.txt'];
  for (const f of [...keep, ...drop]) put(root, `.claude/${f}`);
  assert.deepEqual(core.enumerateClaudeFiles(root), [...keep].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)));
});

test('manifest lines are "<lowercase sha256>  <path>" sorted by ordinal path, LF terminated; hash is sha256 of the text', () => {
  const root = tmp();
  put(root, '.claude/b.txt', 'two');
  put(root, '.claude/Z.txt', 'one'); // not B.txt: B.txt and b.txt are the same file on case-insensitive Windows
  put(root, '.claude/_u.txt', 'three');
  put(root, '.claude/a/z.txt', 'four');
  const m = core.hSetManifest(root);
  assert.deepEqual(m.rels, ['Z.txt', '_u.txt', 'a/z.txt', 'b.txt']); // ordinal: uppercase < underscore < lowercase
  assert.equal(m.text, [`${h('one')}  Z.txt`, `${h('three')}  _u.txt`, `${h('four')}  a/z.txt`, `${h('two')}  b.txt`].join('\n') + '\n');
  assert.equal(m.sha256, h(m.text));
  assert.ok(!m.text.includes('\r'));
});

test('E-set membership: orchestration/*.mjs|*.json, hooks/*.mjs, settings.json, agents/*.md only', () => {
  const yes = ['orchestration/x.mjs', 'orchestration/gates.json', 'orchestration/trusted-interpreters.json', 'hooks/guard.mjs', 'settings.json', 'agents/a.md'];
  const no = ['orchestration/sub/x.mjs', 'orchestration/tests/ge1.test.mjs', 'orchestration/x.md', 'hooks/tests/selftest.mjs', 'hooks/x.json',
    'settings.local.json', 'agents/sub/a.md', 'agents/a.txt', 'skills/s/SKILL.md', 'references/r.md', 'orchestration/runs/r/change-set.json'];
  for (const r of yes) assert.equal(core.isESetPath(r), true, r);
  for (const r of no) assert.equal(core.isESetPath(r), false, r);
});

test('E-set manifest changes when an evidence-relevant file changes, not when a skill or settings.local.json changes', () => {
  const root = tmp();
  put(root, '.claude/orchestration/ledger.mjs', 'v1');
  put(root, '.claude/skills/s/SKILL.md', 'v1');
  put(root, '.claude/settings.local.json', '{}');
  const e0 = core.eSetManifest(root).sha256;
  put(root, '.claude/skills/s/SKILL.md', 'v2');
  put(root, '.claude/settings.local.json', '{"a":1}');
  assert.equal(core.eSetManifest(root).sha256, e0);
  put(root, '.claude/orchestration/ledger.mjs', 'v2');
  assert.notEqual(core.eSetManifest(root).sha256, e0);
});

// ---------------------------------------------------------------- manifest parsing and scope diff

const GOOD_LINE = (c, p) => `${h(c)}  ${p}`;
test('parseManifest accepts a strict manifest and rejects every malformed form', () => {
  const ok = GOOD_LINE('a', 'a.txt') + '\n' + GOOD_LINE('b', 'b.txt') + '\n';
  assert.equal(core.parseManifest(ok).size, 2);
  const bad = {
    empty: '', 'no trailing LF': GOOD_LINE('a', 'a.txt'), CRLF: GOOD_LINE('a', 'a.txt') + '\r\n', BOM: '\ufeff' + ok,
    'uppercase hex': h('a').toUpperCase() + '  a.txt\n', 'single space': `${h('a')} a.txt\n`, 'short hash': 'abc  a.txt\n',
    unsorted: GOOD_LINE('b', 'b.txt') + '\n' + GOOD_LINE('a', 'a.txt') + '\n', duplicate: GOOD_LINE('a', 'a.txt') + '\n' + GOOD_LINE('b', 'a.txt') + '\n',
    'blank line': GOOD_LINE('a', 'a.txt') + '\n\n', backslash: GOOD_LINE('a', 'a\\b.txt') + '\n', absolute: GOOD_LINE('a', '/a.txt') + '\n',
    traversal: GOOD_LINE('a', '../a.txt') + '\n', 'not a string': null,
  };
  for (const [name, text] of Object.entries(bad)) assert.throws(() => core.parseManifest(text), name);
});

function scopeFixture() {
  const root = tmp();
  put(root, '.claude/orchestration/ledger.mjs', 'v1');
  put(root, '.claude/skills/s/SKILL.md', 'v1');
  const m0 = core.hSetManifest(root);
  const baseline = put(root, 'm0.txt', m0.text); // lives outside .claude, like the human M0
  const cs = {
    allowed_paths: ['.claude/orchestration/run-gate.mjs', '.claude/orchestration/tests/**'],
    forbidden_paths: ['.claude/settings.json', '.claude/skills/**'],
    baseline_manifest: { path: baseline, sha256: h(m0.text) },
  };
  return { root, cs, baseline, m0 };
}

test('manifestScopeCheck passes when nothing changed or only allowed paths were added', () => {
  const { root, cs } = scopeFixture();
  assert.equal(core.manifestScopeCheck(cs, root).ok, true);
  put(root, '.claude/orchestration/run-gate.mjs', 'new');
  put(root, '.claude/orchestration/tests/ge1.test.mjs', 'new');
  const r = core.manifestScopeCheck(cs, root);
  assert.equal(r.ok, true, r.problems.join(';'));
  assert.deepEqual(r.added.sort(), ['orchestration/run-gate.mjs', 'orchestration/tests/ge1.test.mjs']);
});

test('manifestScopeCheck fails for an out-of-scope addition, a forbidden modification, a deletion and an allowed-but-forbidden path', () => {
  let f = scopeFixture();
  put(f.root, '.claude/orchestration/other.mjs', 'x');
  assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);

  f = scopeFixture();
  put(f.root, '.claude/skills/s/SKILL.md', 'tampered');
  assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);

  f = scopeFixture();
  fs.rmSync(path.join(f.root, '.claude/orchestration/ledger.mjs'));
  const r = core.manifestScopeCheck(f.cs, f.root);
  assert.equal(r.ok, false);
  assert.deepEqual(r.deleted, ['orchestration/ledger.mjs']);

  f = scopeFixture(); // a path that is both allowed and forbidden is forbidden (forbidden wins)
  f.cs.allowed_paths.push('.claude/settings.json');
  put(f.root, '.claude/settings.json', '{}');
  assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);
});

test('manifestScopeCheck fails closed on pin mismatch, missing, malformed or undeclared baseline', () => {
  let f = scopeFixture();
  f.cs.baseline_manifest.sha256 = h('other');
  assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);

  f = scopeFixture();
  fs.rmSync(f.baseline);
  assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);

  f = scopeFixture();
  const bad = 'not a manifest\n';
  fs.writeFileSync(f.baseline, bad);
  f.cs.baseline_manifest.sha256 = h(bad); // pin matches but content is malformed
  assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);

  f = scopeFixture();
  delete f.cs.baseline_manifest;
  assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);
  for (const bm of [null, [], 'x', { path: 5, sha256: 'x' }, { path: 'p' }]) {
    f = scopeFixture();
    f.cs.baseline_manifest = bm;
    assert.equal(core.manifestScopeCheck(f.cs, f.root).ok, false);
  }
});

// ---------------------------------------------------------------- tree digest

test('tree digest is content based: stable across mtime-only changes, sensitive to content, untracked, deleted and HEAD changes', () => {
  const root = gitRepo();
  const d0 = core.treeDigest(root);
  assert.match(d0.sha256, /^[0-9a-f]{64}$/);
  assert.match(d0.head, /^[0-9a-f]{40}$/);
  assert.equal(core.treeDigest(root).sha256, d0.sha256);

  const t = new Date(Date.now() + 3600_000);
  fs.utimesSync(path.join(root, 'a.txt'), t, t); // mtime only
  assert.equal(core.treeDigest(root).sha256, d0.sha256);

  put(root, 'a.txt', 'changed\n');
  const d1 = core.treeDigest(root).sha256;
  assert.notEqual(d1, d0.sha256);
  put(root, 'a.txt', 'alpha\n'); // restored bytes, new mtime: back to the original digest
  assert.equal(core.treeDigest(root).sha256, d0.sha256);

  put(root, 'untracked.txt', 'u');
  const d2 = core.treeDigest(root).sha256;
  assert.notEqual(d2, d0.sha256);
  fs.rmSync(path.join(root, 'untracked.txt'));

  fs.rmSync(path.join(root, 'dir with space/b.txt'));
  const d3 = core.treeDigest(root).sha256;
  assert.ok(d3 !== d0.sha256 && d3 !== d1 && d3 !== d2);
  git(root, 'checkout', '--', 'dir with space/b.txt');
  assert.equal(core.treeDigest(root).sha256, d0.sha256);

  put(root, 'c.txt', 'c');
  git(root, 'add', '-A');
  git(root, 'commit', '-q', '-m', 'second');
  const d4 = core.treeDigest(root);
  assert.notEqual(d4.head, d0.head);
  assert.notEqual(d4.sha256, d0.sha256);
});

test('tree digest distinguishes a change in one file from the same change in another file, and unicode / spaced paths work', () => {
  const root = gitRepo();
  put(root, 'dir with space/b.txt', 'beta2\n');
  const x = core.treeDigest(root).sha256;
  put(root, 'dir with space/b.txt', 'beta\n');
  put(root, 'a.txt', 'beta2\n');
  assert.notEqual(core.treeDigest(root).sha256, x);
  put(root, 'a.txt', 'alpha\n');
  put(root, 'caf\u00e9 \u2713.txt', 'u');
  assert.match(core.treeDigest(root).sha256, /^[0-9a-f]{64}$/);
});

test('tree digest throws (never returns a digest) when git state cannot be read', () => {
  const root = tmp(); // not a git repository
  assert.throws(() => core.treeDigest(root));
});

// ---------------------------------------------------------------- applicability predicate (focused; the 50 vectors live in GE6)

const ap = (...paths) => ({ allowed_paths: paths });
test('manifestScopeApplicability: declared baseline gives RUN; ordinary scope gives NOT_APPLICABLE; .claude scope without baseline gives FAIL', () => {
  const bm = { path: 'p', sha256: 's' };
  assert.equal(core.manifestScopeApplicability({ allowed_paths: ['.claude/orchestration/ledger.mjs'], baseline_manifest: bm }), 'RUN');
  assert.equal(core.manifestScopeApplicability({ allowed_paths: ['backend/**'], baseline_manifest: bm }), 'RUN');
  assert.equal(core.manifestScopeApplicability(ap('backend/**', 'docs/*.md')), 'NOT_APPLICABLE');
  assert.equal(core.manifestScopeApplicability(ap()), 'NOT_APPLICABLE');
  assert.equal(core.manifestScopeApplicability(ap('.claude/**')), 'FAIL');
  assert.equal(core.manifestScopeApplicability({ allowed_paths: ['.claude/x'], baseline_manifest: [] }), 'FAIL'); // array baseline counts as undeclared
});

test('AC-13/14: separators normalize before validation; UNC, rooted, drive, stream and traversal forms fail closed', () => {
  for (const p of ['..\\x', '../x', 'backend\\..\\.claude\\x', 'a/../.claude/x', '.. /x', '...\\x', '\\\\server\\share\\x', '//server/share/x', '/abs/x', '\\abs\\x', 'C:\\x', 'C:x', '.claude::$DATA']) {
    assert.equal(core.manifestScopeApplicability(ap(p)), 'FAIL', JSON.stringify(p));
  }
});

test('AC-15: malformed containers fail closed even with a baseline', () => {
  const bm = { path: 'p', sha256: 's' };
  for (const cs of [null, [], 'x', 7, {}, { allowed_paths: 'backend/**' }, { allowed_paths: null }, { allowed_paths: { a: 1 } }, { allowed_paths: 'x', baseline_manifest: bm }, { allowed_paths: 5, baseline_manifest: bm }]) {
    assert.equal(core.manifestScopeApplicability(cs), 'FAIL', JSON.stringify(cs));
  }
});

test('AC-16: ordinary backslash and dotted entries are not misclassified', () => {
  for (const p of ['backend\\sub\\x', 'docs/a.b./x', './backend/x']) assert.equal(core.manifestScopeApplicability(ap(p)), 'NOT_APPLICABLE', p);
});

test('Windows aliases of .claude (case, trailing dot/space, 8.3 short name, wildcard first segment) fail closed', () => {
  for (const p of ['.CLAUDE/x', '.claude /x', '.claude./x', 'CLAUDE~1/x', '.cl*/x', '*/foo.json', '**', '**/*.mjs', '.claude\\x', './.claude/x', '', '   ', 'a\u0000b']) {
    assert.equal(core.manifestScopeApplicability(ap(p)), 'FAIL', JSON.stringify(p));
  }
  for (const p of [5, null, ['backend/x']]) assert.equal(core.manifestScopeApplicability({ allowed_paths: [p] }), 'FAIL');
});

// ---------------------------------------------------------------- strict schema-1 evidence validator

const T = Date.parse('2026-01-01T12:00:00.000Z');
const iso = (ms) => new Date(ms).toISOString();
function pytestEntry(over = {}) {
  return {
    at: iso(T + 2000), source: 'runner', schema: 1, gate: 'G-BE-FULL', covers: ['G-BE-FULL'], kind: 'pytest', result: 'PASS', exit_status: 0,
    counts: { tests: 10, failures: 0, errors: 0, skipped: 1 }, run_id: crypto.randomUUID(), ledger_run: 'gov-x', change_set_sha256: h('cs'),
    steps: [{ name: 'pytest', argv_sha256: h('argv'), exit_status: 0 }], interpreter: { path: 'C:\\py\\python.exe', sha256: h('py') },
    tree_hash: h('tree'), head: 'a'.repeat(40), claude_e_sha256: h('e'), runner_sha256: h('r'), ledger_sha256: h('l'), ledger_core_sha256: h('lc'),
    gates_json_sha256: h('g'), interpreters_sha256: h('i'), baseline_manifest_sha256: null, h_manifest_sha256: null,
    started_at: iso(T), finished_at: iso(T + 1000), junit_sha256: h('junit'), required_cells: null, ...over,
  };
}
function scriptEntry(over = {}) {
  return pytestEntry({ gate: 'G-SCAN', covers: ['G-SCAN'], kind: 'script', counts: null, interpreter: null, junit_sha256: null, steps: [{ name: 'scan', argv_sha256: h('s'), exit_status: 0 }], ...over });
}

test('validator accepts well-formed pytest and script entries (PASS, FAIL and UNKNOWN shapes)', () => {
  assert.deepEqual(core.validateEvidenceV1(pytestEntry()), { ok: true, errors: [] });
  assert.deepEqual(core.validateEvidenceV1(scriptEntry()), { ok: true, errors: [] });
  assert.equal(core.validateEvidenceV1(pytestEntry({ result: 'FAIL', exit_status: 1, steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: 1 }] })).ok, true);
  assert.equal(core.validateEvidenceV1(pytestEntry({ result: 'UNKNOWN', exit_status: null, counts: null, junit_sha256: null, steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: null }] })).ok, true);
  assert.equal(core.validateEvidenceV1(pytestEntry({ required_cells: { expected: 4, passed: 4 }, baseline_manifest_sha256: h('b'), h_manifest_sha256: h('hm') })).ok, true);
});

test('validator rejects unknown keys, missing keys, and non-object input', () => {
  assert.equal(core.validateEvidenceV1(pytestEntry({ extra: 1 })).ok, false);
  for (const k of Object.keys(pytestEntry())) {
    const e = pytestEntry(); delete e[k];
    assert.equal(core.validateEvidenceV1(e).ok, false, `missing ${k}`);
  }
  for (const v of [null, undefined, 5, 'x', [], true]) assert.equal(core.validateEvidenceV1(v).ok, false);
});

test('validator rejects wrong sources, schema, types and formats', () => {
  const badFields = {
    source_hook: { source: 'hook' }, source_hook_observed: { source: 'hook-observed' }, source_ledger: { source: 'ledger' }, source_orch: { source: 'orchestrator' },
    schema2: { schema: 2 }, schema_str: { schema: '1' }, gate_bad: { gate: 'g-be-full' }, gate_inject: { gate: 'G-X; rm' },
    covers_two: { covers: ['G-BE-FULL', 'G-SCAN'] }, covers_other: { covers: ['G-SCAN'] }, covers_empty: { covers: [] }, covers_str: { covers: 'G-BE-FULL' },
    kind_bad: { kind: 'node' }, result_pass_lc: { result: 'pass' }, result_bad: { result: 'OK' }, exit_str: { exit_status: '0' }, exit_float: { exit_status: 0.5 },
    run_id_bad: { run_id: 'abc' }, run_id_upper: { run_id: crypto.randomUUID().toUpperCase() }, ledger_run_bad: { ledger_run: '../x' },
    cs_hash_bad: { change_set_sha256: 'abc' }, cs_hash_upper: { change_set_sha256: h('cs').toUpperCase() }, tree_bad: { tree_hash: 'x' }, head_short: { head: 'abc' },
    e_bad: { claude_e_sha256: null }, runner_bad: { runner_sha256: 'x' }, ledger_bad: { ledger_sha256: undefined }, core_bad: { ledger_core_sha256: 5 },
    gates_bad: { gates_json_sha256: '' }, interp_hash_bad: { interpreters_sha256: 'zz' }, bm_bad: { baseline_manifest_sha256: 'x' }, hm_bad: { h_manifest_sha256: 5 },
    at_bad: { at: 'yesterday' }, at_nonmillis: { at: '2026-01-01T12:00:00Z' }, started_bad: { started_at: 5 }, finished_bad: { finished_at: '2026-13-45T00:00:00.000Z' },
    junit_bad: { junit_sha256: 'x' }, cells_bad: { required_cells: { expected: 1 } }, cells_neg: { required_cells: { expected: -1, passed: 0 } }, cells_extra: { required_cells: { expected: 1, passed: 1, x: 1 } },
    counts_str: { counts: { tests: '10', failures: 0, errors: 0, skipped: 0 } }, counts_neg: { counts: { tests: -1, failures: 0, errors: 0, skipped: 0 } },
    counts_extra: { counts: { tests: 1, failures: 0, errors: 0, skipped: 0, x: 1 } }, counts_missing: { counts: { tests: 1, failures: 0, errors: 0 } },
    interp_bad: { interpreter: { path: 'x' } }, interp_extra: { interpreter: { path: 'x', sha256: h('p'), z: 1 } }, interp_pass_null: { interpreter: null },
    steps_str: { steps: 'x' }, steps_empty: { steps: [] }, steps_extra: { steps: [{ name: 'a', argv_sha256: h('a'), exit_status: 0, z: 1 }] },
    steps_badhash: { steps: [{ name: 'a', argv_sha256: 'x', exit_status: 0 }] }, steps_badname: { steps: [{ name: '', argv_sha256: h('a'), exit_status: 0 }] },
    pass_but_exit1: { exit_status: 1 }, pass_but_step_fail: { steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: 1 }] }, pass_null_exit: { exit_status: null },
    pass_junit_null: { junit_sha256: null },
  };
  for (const [name, over] of Object.entries(badFields)) assert.equal(core.validateEvidenceV1(pytestEntry(over)).ok, false, name);
});

test('script entries: counts must be null, interpreter null, junit null', () => {
  assert.equal(core.validateEvidenceV1(scriptEntry({ counts: { tests: 1, failures: 0, errors: 0, skipped: 0 } })).ok, false);
  assert.equal(core.validateEvidenceV1(scriptEntry({ interpreter: { path: 'x', sha256: h('p') } })).ok, false);
  assert.equal(core.validateEvidenceV1(scriptEntry({ junit_sha256: h('j') })).ok, false);
  assert.equal(core.validateEvidenceV1(scriptEntry({ required_cells: { expected: 1, passed: 1 } })).ok, true); // required_cells shape is checked, not forbidden
});

test('manifest-scope step shapes: only the exact not-applicable record may carry applicable:false', () => {
  const na = { name: 'manifest-scope', applicable: false, reason: 'no_baseline_declared_scope_excludes_claude', exit_status: null };
  const scope = { name: 'scope-check', argv_sha256: h('sc'), exit_status: 0 };
  assert.equal(core.validateEvidenceV1(scriptEntry({ gate: 'G-SCOPE', covers: ['G-SCOPE'], steps: [scope, na] })).ok, true);
  for (const bad of [
    { ...na, reason: 'other' }, { ...na, name: 'scope-check' }, { ...na, exit_status: 0 }, { ...na, applicable: true }, { ...na, extra: 1 },
    { name: 'manifest-scope', applicable: false, exit_status: null },
  ]) assert.equal(core.validateEvidenceV1(scriptEntry({ gate: 'G-SCOPE', covers: ['G-SCOPE'], steps: [scope, bad] })).ok, false, JSON.stringify(bad));
});

// ---------------------------------------------------------------- newest-entry rule

test('newestRunnerEntry: newest runner entry per gate wins; ignores other sources; a newer FAIL revokes an older PASS; ties go to the later record', () => {
  const pass = pytestEntry({ at: iso(T + 1000) });
  const fail = pytestEntry({ at: iso(T + 2000), result: 'FAIL', exit_status: 1, steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: 1 }] });
  assert.equal(core.newestRunnerEntry([pass, fail], 'G-BE-FULL'), fail);
  assert.equal(core.newestRunnerEntry([fail, pass], 'G-BE-FULL'), fail);
  const hook = { source: 'hook', gate: 'G-BE-FULL', covers: ['G-BE-FULL'], result: 'PASS', at: iso(T + 9000) };
  assert.equal(core.newestRunnerEntry([pass, hook], 'G-BE-FULL'), pass);
  assert.equal(core.newestRunnerEntry([pass], 'G-SCAN'), null);
  assert.equal(core.newestRunnerEntry([], 'G-SCAN'), null);
  assert.equal(core.newestRunnerEntry(undefined, 'G-SCAN'), null);
  const a = pytestEntry({ at: iso(T + 1000) });
  const b = pytestEntry({ at: iso(T + 1000), result: 'FAIL', exit_status: 1, steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: 1 }] });
  assert.equal(core.newestRunnerEntry([a, b], 'G-BE-FULL'), b);
  assert.equal(core.newestRunnerEntry([null, 5, 'x', { source: 'runner' }], 'G-BE-FULL'), null);
});

// ---------------------------------------------------------------- duplicate-keyed records (JSON.parse silently keeps the last duplicate)

test('jsonDuplicateKeyPaths reports duplicate keys at any depth, including escaped-equal keys, and nothing for clean JSON', () => {
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"a":1,"b":{"c":1}}'), []);
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"a":1,"a":2}'), ['a']);
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"evidence":[{"x":1},{"result":"FAIL","result":"PASS"}]}'), ['evidence[1].result']);
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"a":1,"\\u0061":2}'), ['a']); // same key after unescaping
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"o":{"k":1,"k":2},"p":[[{"z":1,"z":1}]]}'), ['o.k', 'p[0][0].z']);
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"a":"x\\"y","b":"{\\"a\\":1,\\"a\\":2}"}'), []); // quotes and braces inside strings are not keys
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"a":{"k":1},"b":{"k":2}}'), []); // same key in different objects is fine
  assert.deepEqual(core.jsonDuplicateKeyPaths(' [ ] '), []);
  assert.deepEqual(core.jsonDuplicateKeyPaths('{"n":-1.5e+3,"t":true,"f":false,"z":null}'), []);
});

test('jsonDuplicateKeyPaths throws on malformed JSON (callers fail closed)', () => {
  for (const bad of ['', '{', '{"a":}', '{"a" 1}', '{"a":1,}', '[1,]', '{"a":1} x', '{a:1}', '"unterminated', '{"a":01x}']) assert.throws(() => core.jsonDuplicateKeyPaths(bad), bad);
});

test('taintedEvidenceIndexes returns the evidence indexes whose raw record has a duplicate key; the parsed copy would hide it', () => {
  const raw = '{"evidence":[{"gate":"G-A","result":"PASS"},{"gate":"G-B","result":"FAIL","result":"PASS"},{"gate":"G-C"}],"events":[{"t":1,"t":2}]}';
  assert.equal(JSON.parse(raw).evidence[1].result, 'PASS'); // the last duplicate wins silently
  assert.deepEqual([...core.taintedEvidenceIndexes(raw)], [1]);
  assert.deepEqual([...core.taintedEvidenceIndexes('{"evidence":[{"a":1}]}')], []);
  assert.deepEqual([...core.taintedEvidenceIndexes('{"evidence":[{"a":{"b":1,"b":2}}]}')], [0]); // nested duplicate taints the record
  assert.throws(() => core.taintedEvidenceIndexes('{"evidence":['));
});

test('newestRunnerIndex agrees with newestRunnerEntry and returns -1 when there is none', () => {
  const a = pytestEntry({ at: iso(T + 1000) });
  const b = pytestEntry({ at: iso(T + 2000), result: 'FAIL', exit_status: 1, steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: 1 }] });
  assert.equal(core.newestRunnerIndex([a, { source: 'hook' }, b], 'G-BE-FULL'), 2);
  assert.equal(core.newestRunnerIndex([b, a], 'G-BE-FULL'), 0);
  assert.equal(core.newestRunnerIndex([a], 'G-SCAN'), -1);
  assert.equal(core.newestRunnerIndex(undefined, 'G-SCAN'), -1);
});

test('mutateLedger persists a duplicate-key taint on the affected evidence record, so a later rewrite (every hook event) cannot launder it into a clean-looking PASS', async () => {
  const root = tmp();
  const orch = path.join(root, '.claude', 'orchestration');
  fs.mkdirSync(path.join(orch, 'runs', 'r-x'), { recursive: true });
  fs.copyFileSync(path.join(REAL_ORCH, 'ledger-core.mjs'), path.join(orch, 'ledger-core.mjs'));
  const ledgerFile = path.join(orch, 'runs', 'r-x', 'ledger.json');
  fs.writeFileSync(ledgerFile, '{"run_id":"r-x","tasks":[],"events":[],"evidence":[{"gate":"G-A","result":"FAIL","result":"PASS"},{"gate":"G-B","result":"PASS"}]}');
  const tcore = await import(pathToFileURL(path.join(orch, 'ledger-core.mjs')).href);
  tcore.appendEvent('r-x', { type: 'noise' }); // any ordinary mutation rewrites the file through JSON.stringify
  const rewritten = fs.readFileSync(ledgerFile, 'utf8');
  assert.deepEqual(core.jsonDuplicateKeyPaths(rewritten), [], 'the rewritten file is clean JSON again');
  const l = JSON.parse(rewritten);
  assert.equal(l.evidence[0].tainted_duplicate_keys, true, 'but the affected record carries a persistent taint');
  assert.equal(l.evidence[1].tainted_duplicate_keys, undefined);
  assert.equal(core.validateEvidenceV1({ ...pytestEntry(), tainted_duplicate_keys: true }).ok, false, 'a tainted record fails the strict validator (unknown key) forever');
  tcore.appendEvent('r-x', { type: 'noise2' });
  assert.equal(JSON.parse(fs.readFileSync(ledgerFile, 'utf8')).evidence[0].tainted_duplicate_keys, true, 'the taint survives further rewrites');
});

test('mutateLedger leaves a clean ledger untouched apart from the mutation (no taint marks)', async () => {
  const root = tmp();
  const orch = path.join(root, '.claude', 'orchestration');
  fs.mkdirSync(path.join(orch, 'runs', 'r-y'), { recursive: true });
  fs.copyFileSync(path.join(REAL_ORCH, 'ledger-core.mjs'), path.join(orch, 'ledger-core.mjs'));
  const ledgerFile = path.join(orch, 'runs', 'r-y', 'ledger.json');
  fs.writeFileSync(ledgerFile, JSON.stringify({ run_id: 'r-y', tasks: [], events: [], evidence: [{ gate: 'G-A', result: 'PASS' }] }));
  const tcore = await import(pathToFileURL(path.join(orch, 'ledger-core.mjs')).href);
  tcore.appendEvidence('r-y', { source: 'hook-observed', gate: 'G-B', result: 'PASS' });
  const l = JSON.parse(fs.readFileSync(ledgerFile, 'utf8'));
  assert.equal(l.evidence.length, 2);
  assert.ok(l.evidence.every((e) => !('tainted_duplicate_keys' in e)));
});

test('acceptance rejects an entry whose raw record carried a duplicate key (ctx.tainted)', () => {
  const e = pytestEntry();
  assert.deepEqual(problems(e), []);
  assert.ok(problems(e, { tainted: true }).length > 0);
});

// ---------------------------------------------------------------- acceptance problems (what done() will call in GE4)

function ctxFor(entry, over = {}) {
  return {
    gate: entry.gate, ledgerRun: entry.ledger_run, changeSetSha256: entry.change_set_sha256, changeSet: { allowed_paths: ['backend/**'] },
    stepNames: entry.steps.map((s) => s.name), taskStartedAtMs: T - 1000, nowMs: T + 60_000,
    current: {
      tree_hash: entry.tree_hash, head: entry.head, claude_e_sha256: entry.claude_e_sha256, runner_sha256: entry.runner_sha256, ledger_sha256: entry.ledger_sha256,
      ledger_core_sha256: entry.ledger_core_sha256, gates_json_sha256: entry.gates_json_sha256, interpreters_sha256: entry.interpreters_sha256,
      baseline_manifest_sha256: entry.baseline_manifest_sha256, h_manifest_sha256: entry.h_manifest_sha256,
    }, ...over,
  };
}
const problems = (e, over) => core.evidenceAcceptanceProblems(e, ctxFor(e, over));

test('acceptance: a fully consistent PASS entry has no problems', () => {
  assert.deepEqual(problems(pytestEntry()), []);
  assert.deepEqual(problems(scriptEntry()), []);
});

test('acceptance rejects wrong run (replay across runs), wrong Change Set, wrong gate, non-runner sources', () => {
  assert.ok(problems(pytestEntry(), { ledgerRun: 'other-run' }).length);
  assert.ok(problems(pytestEntry(), { changeSetSha256: h('amended') }).length);
  assert.ok(problems(pytestEntry(), { gate: 'G-SCAN' }).length);
  for (const source of ['hook', 'hook-observed', 'ledger', 'orchestrator']) assert.ok(problems(pytestEntry({ source })).length, source);
});

test('acceptance rejects stale bindings: tree, E-set, runner, ledger, ledger-core, gates.json, interpreters, head', () => {
  const e = pytestEntry();
  for (const k of ['tree_hash', 'claude_e_sha256', 'runner_sha256', 'ledger_sha256', 'ledger_core_sha256', 'gates_json_sha256', 'interpreters_sha256', 'head']) {
    const c = ctxFor(e); c.current[k] = k === 'head' ? 'b'.repeat(40) : h('changed-' + k);
    assert.ok(core.evidenceAcceptanceProblems(e, c).length, k);
  }
});

test('acceptance rejects non-PASS, non-zero exit and failing counts', () => {
  assert.ok(problems(pytestEntry({ result: 'FAIL', exit_status: 1, steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: 1 }] })).length);
  assert.ok(problems(pytestEntry({ result: 'UNKNOWN', exit_status: null, counts: null, junit_sha256: null, steps: [{ name: 'pytest', argv_sha256: h('a'), exit_status: null }] })).length);
  assert.ok(problems(pytestEntry({ counts: { tests: 0, failures: 0, errors: 0, skipped: 0 } })).length);
  assert.ok(problems(pytestEntry({ counts: { tests: 5, failures: 1, errors: 0, skipped: 0 } })).length);
  assert.ok(problems(pytestEntry({ counts: { tests: 5, failures: 0, errors: 1, skipped: 0 } })).length);
  assert.ok(problems(pytestEntry({ counts: null })).length);
});

test('acceptance enforces freshness: not before task start, not older than 12 hours, not from the future, ordering of timestamps', () => {
  assert.ok(problems(pytestEntry(), { taskStartedAtMs: T + 10_000 }).length);
  assert.ok(problems(pytestEntry(), { nowMs: T + 12 * 3600_000 + 5000 }).length);
  assert.deepEqual(problems(pytestEntry(), { nowMs: T + 12 * 3600_000 }), []);
  assert.ok(problems(pytestEntry(), { nowMs: T - 3600_000 }).length); // finished far in the future relative to now
  assert.ok(problems(pytestEntry({ at: iso(T + 500) })).length); // at earlier than finished_at
  assert.ok(problems(pytestEntry({ started_at: iso(T + 5000) })).length); // started after finished
});

test('acceptance: required_cells must be satisfied when present, and mandatory when the harness applies', () => {
  assert.deepEqual(problems(pytestEntry({ required_cells: { expected: 3, passed: 3 } })), []);
  assert.ok(problems(pytestEntry({ required_cells: { expected: 3, passed: 2 } })).length);
  assert.ok(problems(pytestEntry({ required_cells: { expected: 0, passed: 0 } })).length);
  assert.ok(problems(pytestEntry(), { requireCells: true }).length);
  assert.deepEqual(problems(pytestEntry({ required_cells: { expected: 3, passed: 3 } }), { requireCells: true }), []);
});

test('acceptance: step names must equal the gate definition exactly and in order', () => {
  const e = scriptEntry({ gate: 'G-SCOPE', covers: ['G-SCOPE'], steps: [{ name: 'scope-check', argv_sha256: h('s'), exit_status: 0 }] });
  assert.ok(core.evidenceAcceptanceProblems(e, ctxFor(e, { stepNames: ['scope-check', 'manifest-scope'] })).length); // missing manifest-scope step
  assert.ok(core.evidenceAcceptanceProblems(e, ctxFor(e, { stepNames: ['manifest-scope', 'scope-check'] })).length); // wrong order
  assert.deepEqual(core.evidenceAcceptanceProblems(e, ctxFor(e, { stepNames: ['scope-check'] })), []);
});

const NA = { name: 'manifest-scope', applicable: false, reason: 'no_baseline_declared_scope_excludes_claude', exit_status: null };
const SCOPE1 = (ms = 0) => ({ name: 'scope-check', argv_sha256: h('sc'), exit_status: ms });
const scopeEntry = (steps, over = {}) => scriptEntry({ gate: 'G-SCOPE', covers: ['G-SCOPE'], steps, ...over });
const SCOPE_NAMES = ['scope-check', 'manifest-scope'];

test('AC-3/4: NOT_APPLICABLE record accepted only when the current Change Set recomputes NOT_APPLICABLE', () => {
  const e = scopeEntry([SCOPE1(), NA]);
  assert.deepEqual(problems(e, { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['backend/**'] } }), []);
  assert.ok(problems(e, { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['backend/**'], baseline_manifest: { path: 'p', sha256: 's' } } }).length); // now RUN
  assert.ok(problems(e, { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['.claude/x'] } }).length); // now FAIL
});

test('AC-1/4: with a declared baseline the manifest-scope step must be a normal step with exit 0 and baseline hashes bound', () => {
  const bm = { path: 'p', sha256: 's' };
  const run = { name: 'manifest-scope', argv_sha256: h('ms'), exit_status: 0 };
  const e = scopeEntry([SCOPE1(), run], { baseline_manifest_sha256: h('b'), h_manifest_sha256: h('hm') });
  assert.deepEqual(problems(e, { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['.claude/x'], baseline_manifest: bm } }), []);
  const nullBound = scopeEntry([SCOPE1(), run]); // RUN but baseline hashes not recorded
  assert.ok(problems(nullBound, { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['.claude/x'], baseline_manifest: bm } }).length);
  const failedStep = scopeEntry([SCOPE1(), { ...run, exit_status: 1 }], { result: 'FAIL', exit_status: 1, baseline_manifest_sha256: h('b'), h_manifest_sha256: h('hm') });
  assert.ok(problems(failedStep, { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['.claude/x'], baseline_manifest: bm } }).length);
});

test('AC-2: a FAIL-class Change Set (no baseline, .claude scope) can never be accepted, even with a forged normal step', () => {
  const run = { name: 'manifest-scope', argv_sha256: h('ms'), exit_status: 0 };
  assert.ok(problems(scopeEntry([SCOPE1(), run]), { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['.claude/x'] } }).length);
  assert.ok(problems(scopeEntry([SCOPE1(), NA]), { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['.claude/x'] } }).length);
});

test('a NOT_APPLICABLE Change Set must record null baseline hashes; non-null hashes without a declared baseline are rejected', () => {
  const e = scopeEntry([SCOPE1(), NA], { baseline_manifest_sha256: h('b'), h_manifest_sha256: h('hm') });
  assert.ok(problems(e, { stepNames: SCOPE_NAMES, changeSet: { allowed_paths: ['backend/**'] } }).length);
});

// ---------------------------------------------------------------- bindings

test('computeBindings returns every bound hash for a fixture tree and tracks content', () => {
  const root = gitRepo();
  for (const f of ['run-gate.mjs', 'ledger.mjs', 'ledger-core.mjs']) put(root, `.claude/orchestration/${f}`, f);
  put(root, '.claude/orchestration/gates.json', '{}');
  put(root, '.claude/orchestration/trusted-interpreters.json', '{}');
  const cs = { allowed_paths: ['backend/**'] };
  const b0 = core.computeBindings(cs, root);
  for (const k of ['tree_hash', 'claude_e_sha256', 'runner_sha256', 'ledger_sha256', 'ledger_core_sha256', 'gates_json_sha256', 'interpreters_sha256']) assert.match(b0[k], /^[0-9a-f]{64}$/, k);
  assert.match(b0.head, /^[0-9a-f]{40}$/);
  assert.equal(b0.baseline_manifest_sha256, null);
  assert.equal(b0.h_manifest_sha256, null);
  assert.equal(b0.runner_sha256, h('run-gate.mjs'));
  put(root, '.claude/orchestration/run-gate.mjs', 'changed');
  const b1 = core.computeBindings(cs, root);
  assert.notEqual(b1.runner_sha256, b0.runner_sha256);
  assert.notEqual(b1.claude_e_sha256, b0.claude_e_sha256);
  assert.equal(b1.gates_json_sha256, b0.gates_json_sha256);
});

test('computeBindings includes baseline and H-set hashes only when a baseline is declared, and throws when a bound file is missing', () => {
  const root = gitRepo();
  for (const f of ['run-gate.mjs', 'ledger.mjs', 'ledger-core.mjs', 'gates.json', 'trusted-interpreters.json']) put(root, `.claude/orchestration/${f}`, f);
  const m0 = core.hSetManifest(root);
  const baseline = put(root, 'm0.txt', m0.text);
  const cs = { allowed_paths: ['backend/**'], baseline_manifest: { path: baseline, sha256: h(m0.text) } };
  const b = core.computeBindings(cs, root);
  assert.equal(b.baseline_manifest_sha256, h(m0.text));
  assert.equal(b.h_manifest_sha256, m0.sha256);
  fs.rmSync(path.join(root, '.claude/orchestration/gates.json'));
  assert.throws(() => core.computeBindings(cs, root));
});

test('computeBindings records null baseline hashes (instead of throwing) when the declared baseline is unreadable, so the runner can write a FAIL entry', () => {
  const root = gitRepo();
  for (const f of ['run-gate.mjs', 'ledger.mjs', 'ledger-core.mjs', 'gates.json', 'trusted-interpreters.json']) put(root, `.claude/orchestration/${f}`, f);
  const cs = { allowed_paths: ['backend/**'], baseline_manifest: { path: path.join(root, 'no-such-baseline.txt'), sha256: h('x') } };
  const b = core.computeBindings(cs, root);
  assert.equal(b.baseline_manifest_sha256, null);
  assert.match(b.h_manifest_sha256, /^[0-9a-f]{64}$/); // the H-set itself is still readable
  const e = pytestEntry({ baseline_manifest_sha256: null, h_manifest_sha256: b.h_manifest_sha256 });
  assert.ok(core.evidenceAcceptanceProblems(e, ctxFor(e, { changeSet: cs })).length > 0); // RUN with a null baseline hash is never acceptable
});

test('treeDigest also returns the sorted changed paths, and computeBindings reuses a supplied digest', () => {
  const root = gitRepo();
  put(root, 'z.txt', 'z');
  put(root, 'a.txt', 'changed\n');
  const td = core.treeDigest(root);
  assert.deepEqual(td.paths, ['a.txt', 'z.txt']);
  assert.equal(td.files, 2);
  for (const f of ['run-gate.mjs', 'ledger.mjs', 'ledger-core.mjs', 'gates.json', 'trusted-interpreters.json']) put(root, `.claude/orchestration/${f}`, f);
  const supplied = { sha256: h('supplied'), head: 'c'.repeat(40), files: 0, paths: [] };
  const b = core.computeBindings({ allowed_paths: ['backend/**'] }, root, supplied);
  assert.equal(b.tree_hash, h('supplied'));
  assert.equal(b.head, 'c'.repeat(40));
});

test('runnerStepNames lists the configured step names in order, or null for a gate without a runner block', () => {
  assert.deepEqual(core.runnerStepNames({ runner: { steps: [{ name: 'scope-check' }, { name: 'manifest-scope' }] } }), ['scope-check', 'manifest-scope']);
  for (const g of [{}, { runner: {} }, { runner: { steps: [] } }, { runner: { steps: 'x' } }, { runner: { steps: [{ name: 5 }] } }, null, undefined]) assert.equal(core.runnerStepNames(g), null, JSON.stringify(g));
});

test('conditionalHarnessApplies matches changed files against when_diff_matches globs', () => {
  const gate = { runner: { conditional: { when_diff_matches: ['supabase/migrations/**', 'backend/tests/test_pr_sec_01_db_harness.py'] } } };
  assert.equal(core.conditionalHarnessApplies(['supabase/migrations/001_x.sql'], gate), true);
  assert.equal(core.conditionalHarnessApplies(['backend/tests/test_pr_sec_01_db_harness.py'], gate), true);
  assert.equal(core.conditionalHarnessApplies(['backend/app/x.py'], gate), false);
  assert.equal(core.conditionalHarnessApplies([], gate), false);
  assert.equal(core.conditionalHarnessApplies(['x'], { runner: {} }), false);
  assert.equal(core.conditionalHarnessApplies(['x'], {}), false);
});
