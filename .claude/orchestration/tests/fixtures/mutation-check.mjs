#!/usr/bin/env node
// Mutation check (reviewer tool, not a test): proves the GE tests fail when the trusted-evidence code is deliberately broken.
// Usage: node .claude/orchestration/tests/fixtures/mutation-check.mjs [--only <substring>]
// It copies .claude (minus runs, approvals, reports, worktrees, ACTIVE_RUN, hook-debug.log) into a temp directory, checks that the unmodified
// copy is fully green, then applies ONE mutation at a time to the COPY and runs the tests that should notice. The real files are never written.
// Exit 0 only if the baseline is green and every mutant is killed. Prints names and counts only.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..'); // the real .claude directory
const only = process.argv.includes('--only') ? process.argv[process.argv.indexOf('--only') + 1] : null;
const T = fs.mkdtempSync(path.join(os.tmpdir(), 'mutcheck-'));
const DEST = path.join(T, '.claude');

const EXCLUDE = [/^orchestration\/runs(\/|$)/, /^orchestration\/approvals(\/|$)/, /^reports(\/|$)/, /^worktrees(\/|$)/, /^orchestration\/ACTIVE_RUN$/, /^orchestration\/hook-debug\.log$/, /(^|\/)\.lock-/];
fs.cpSync(SRC, DEST, { recursive: true, filter: (s) => { const rel = path.relative(SRC, s).split(path.sep).join('/'); return !EXCLUDE.some((re) => re.test(rel)); } });
const csRel = 'orchestration/runs/gov-trusted-gate-evidence/change-set.json'; // the regression test reads the approved Change Set
if (fs.existsSync(path.join(SRC, csRel))) { fs.mkdirSync(path.dirname(path.join(DEST, csRel)), { recursive: true }); fs.copyFileSync(path.join(SRC, csRel), path.join(DEST, csRel)); }

const t = (n) => path.join(DEST, 'orchestration', 'tests', `ge${n}.test.mjs`);
const T5 = path.join(DEST, 'hooks', 'tests', 'ge5.test.mjs');
const ALL = [1, 2, 3, 4, 6].map(t).concat(T5);
const RG = 'orchestration/run-gate.mjs', CORE = 'orchestration/ledger-core.mjs', LED = 'orchestration/ledger.mjs';

// [name, file, find, replace, tests, replaceAll?]
const MUTANTS = [
  ['runner: a non-zero exit status is no longer FAIL', RG, "if (st !== 0) { out.result = 'FAIL';", "if (false) { out.result = 'FAIL';", [t(2), t(6)]],
  ['runner: PYTEST_ADDOPTS and PYTHONPATH pass the environment scrub', RG, "'HOME', 'COMSPEC']);", "'HOME', 'COMSPEC', 'PYTEST_ADDOPTS', 'PYTHONPATH']);", [t(2), t(6)]],
  ['runner: interpreter allowlist is not enforced', RG, 'if (!allow.some((a) => normPath(a.path) === normPath(res.path) && a.sha256 === res.sha256))', 'if (false)', [t(2), t(6)]],
  ['runner: tree/governance changes during the run are ignored', RG, 'if (JSON.stringify(b0) !== JSON.stringify(b1))', 'if (false)', [t(2), t(6)]],
  ['runner: junit attribute totals no longer checked against elements', RG, 'if (totals[k] !== counted[k]) return bad(', 'if (false) return bad(', [t(2)]],
  ['core: evidence from another run is accepted', CORE, 'if (e.ledger_run !== ctx.ledgerRun) p.push(', 'if (false) p.push(', [t(1), t(4), t(6)]],
  ['core: tree_hash staleness is ignored', CORE, 'for (const k of BINDING_KEYS) if (e[k] !== ctx.current[k])', "for (const k of BINDING_KEYS) if (k !== 'tree_hash' && e[k] !== ctx.current[k])", [t(1), t(4), t(6)]],
  ['core: validator accepts any evidence source', CORE, "if (e.source !== 'runner') bad('source');", '/* mutated */', [t(1), t(6)]],
  ['core: the 12 hour freshness bound is gone', CORE, 'if (ctx.nowMs - finished > EVIDENCE_MAX_AGE_MS)', 'if (false)', [t(1)]],
  ['core: drive-letter / stream entries no longer fail closed', CORE, "if (g.includes(':')) return { bad: true };", '/* mutated */', [t(1), t(6)]],
  ['core: the OLDEST runner entry wins instead of the newest', CORE, 'tt >= bestT', 'tt < bestT', [t(1), t(4)]],
  ['core: duplicate-key taint is not persisted', CORE, 'l.evidence[i].tainted_duplicate_keys = true;', 'void 0;', [t(1), t(4)]],
  ['core: deleted governance files are not reported by manifest-scope', CORE, 'if (res.deleted.length) res.problems.push(', 'if (false) res.problems.push(', [t(1)]],
  ['done(): any runner evidence is accepted without the acceptance checks', LED, 'for (const m of why) problems.push(', 'for (const m of []) problems.push(', [t(4)]],
  ['done(): .claude/ files no longer raise a task to HIGH', LED, '|| isClaudeFile(f)', '', [t(4)]],
  ['done(): reviews are not invalidated by later governance-file edits', LED, 'Math.max(latestMtime(files), govMtime, startedMs)', 'Math.max(latestMtime(files), startedMs)', [t(4)]],
  ['hook: record-gate writes source "hook" again', 'hooks/record-gate.mjs', "source: 'hook-observed'", "source: 'hook'", [T5, t(4), t(6)]],
  ['gates.json: pytest gates fall back to the default py launcher (3.14)', 'orchestration/gates.json', '"launcher": ["py", "-3.12"]', '"launcher": ["py"]', [t(3)], true],
  // correction cycle 1: manifest-scan, run-directory hardening, required cells
  ['manifest-scan: secret findings no longer fail the step', RG, 's.findings.length || s.unreadable.length || s.oversized.length || s.scanned !== rels.length', 's.unreadable.length', [t(2), t(6)]],
  ['manifest-scan: unreadable or oversized files are skipped instead of failing', RG, 's.findings.length || s.unreadable.length || s.oversized.length || s.scanned !== rels.length', 's.findings.length', [t(2)]],
  ['manifest-scan: an empty baseline diff passes vacuously', RG, 'if (rels.length === 0) return fail(', 'if (false) return fail(', [t(2)]],
  ['gates.json: G-SCAN loses the real manifest-scan step', 'orchestration/gates.json', '{ "name": "manifest-scan", "kind": "builtin", "builtin": "manifest-scan" }', '{ "name": "manifest-scan", "kind": "script", "cwd": ".", "argv": ["node", "-v"], "timeout_s": 60 }', [t(3)]],
  ['run dir (Windows): the private ACL is not verified after hardening', RG, 'if (problems.length) throw new Error(`run directory is not private', 'if (false) throw new Error(`run directory is not private', [t(2)]],
  ['run dir (Windows): an inheriting (unprotected) DACL is accepted as private', RG, "if (mode === 'private' && !acl.protectedDacl) p.push(", 'if (false) p.push(', [t(2)]],
  ['run dir (Windows): an unsafe, shared temp base is accepted', RG, 'if (problems.length) throw new Error(`unsafe temp directory', 'if (false) throw new Error(`unsafe temp directory', [t(2), t(6)]],
  ['run dir (Windows): write-capable rights of foreign principals are ignored', RG, 'else if ((a.mask & WIN_WRITE_BITS) !== 0) p.push(', 'else if (false) p.push(', [t(2)]],
  ['run dir (POSIX): a group/world-writable base without the sticky bit is accepted', RG, 'if ((st.mode & 0o022) !== 0 && (st.mode & 0o1000) === 0) throw', 'if (false) throw', [t(2)]],
  ['run dir (POSIX): the 0700 mode is not verified after chmod', RG, 'if ((st.mode & 0o777) !== 0o700) throw', 'if (false) throw', [t(2)]],
  ['cells: duplicate required cells are accepted', RG, ' || new Set(cells).size !== cells.length', '', [t(2)]],
  ['cells: an empty required-cell list is accepted', RG, 'cells.length === 0 || ', '', [t(2)]],
  ['cells: a skipped required cell counts as satisfied', RG, 'm.every((c) => !c.failed && !c.errored && !c.skipped)', 'm.every((c) => !c.failed && !c.errored)', [t(2)]],
];

const run = (files) => {
  const r = spawnSync(process.execPath, ['--test', ...files], { cwd: T, encoding: 'utf8', timeout: 900000 });
  const m = /ℹ fail (\d+)/.exec(r.stdout || '');
  const p = /ℹ pass (\d+)/.exec(r.stdout || '');
  return { fail: m ? Number(m[1]) : null, pass: p ? Number(p[1]) : null, status: r.status };
};

let exitCode = 0;
try {
  const base = run(ALL);
  console.log(`baseline (unmodified copy): pass=${base.pass} fail=${base.fail}`);
  if (base.fail !== 0 || !(base.pass > 0)) { console.log('BASELINE IS NOT GREEN: mutation results would be meaningless. Aborting.'); exitCode = 2; }
  else {
    let survived = 0; let ran = 0;
    for (const [name, rel, find, replace, tests, all] of MUTANTS) {
      if (only && !name.includes(only)) continue;
      const file = path.join(DEST, rel);
      const orig = fs.readFileSync(file, 'utf8');
      const count = orig.split(find).length - 1;
      if (count === 0 || (count > 1 && !all)) { console.log(`INVALID  ${name} (pattern matched ${count} times; update the mutation list)`); survived++; continue; }
      fs.writeFileSync(file, orig.split(find).join(replace));
      const r = run(tests);
      fs.writeFileSync(file, orig);
      ran++;
      const killed = r.fail === null ? r.status !== 0 : r.fail > 0;
      if (!killed) survived++;
      console.log(`${killed ? 'KILLED  ' : 'SURVIVED'} ${name}  (failing tests: ${r.fail === null ? 'run crashed' : r.fail})`);
    }
    console.log(`\nmutation check: ${ran - survived}/${ran} killed, ${survived} survived or invalid`);
    if (survived) exitCode = 1;
  }
} finally {
  try { fs.rmSync(T, { recursive: true, force: true }); } catch { /* best effort */ }
}
process.exit(exitCode);
