#!/usr/bin/env node
// InboundCheck trusted gate runner: the ONLY producer of satisfiable gate evidence (design v1/v2/v2.1/v2.2).
// Usage: node .claude/orchestration/run-gate.mjs <GATE_ID>     (nothing else is accepted)
//
// The runner never reads anything an agent typed or printed. It looks up a fixed definition in gates.json, runs the steps itself as child
// processes (argv arrays only, no shell, scrubbed environment) and measures what the agent does not control: the OS-reported exit status,
// a junit file the child writes into a directory the runner just created, and content digests of the git-visible tree and of the
// evidence-bound .claude files. One schema-1 entry is appended per invocation. Exit codes: 0 PASS, 1 FAIL or UNKNOWN, 2 refused (no evidence).
//
// Trust boundary (unchanged from the design): a same-user agent that rewrites this runner, gates.json, trusted-interpreters.json or the ledger
// directly is stopped only by the write guards and detected by the hashes, not prevented cryptographically.
//
// Run-directory protection (added in correction cycle 1). The junit file and child logs live in a fresh directory under the OS temp folder. The
// runner (a) rejects a temp base that other principals could write to (POSIX: group/world-writable without the sticky bit; Windows: any write-capable
// grant to a principal other than SYSTEM, Administrators or the current user), (b) creates the directory with mkdtemp, then forces it private
// (POSIX chmod 0700; Windows: remove inheritance and grant only the current user's SID via icacls) and verifies the result (POSIX owner, mode and
// not-a-symlink; Windows protected DACL, no foreign trustee, current user present, parsed from locale-independent SDDL), and (c) refuses to run at all
// (exit 2, no evidence) if any of that cannot be established. LIMIT (documented, not solvable here): this defends against OTHER local principals.
// A process running as the SAME user can always read the directory, reset its ACL or replace its files; against that, the controls remain the write
// guards, the content digests bound into every entry, and independent review.
//
// manifest-scan. `scan.mjs --changed` only sees git-visible files, and .claude/ is gitignored, so for a governance run it checks nothing. The
// `manifest-scan` builtin scans the files that actually differ from the human baseline (added + modified H-set files) with the existing
// patterns.mjs rules, fails closed on unreadable or oversized files, and refuses a vacuous PASS (declared baseline with nothing to scan).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  ROOT, ORCH, sha256, nowIso, getActive, readActiveId, changeSetPath, loadGates, appendEvidence, treeDigest, computeBindings, BINDING_KEYS,
  manifestScopeApplicability, manifestScopeCheck, conditionalHarnessApplies, validateEvidenceV1, NA_STEP_REASON,
} from './ledger-core.mjs';
import { scanSecrets, scanSql } from './patterns.mjs';

const GATE_ID_RE = /^G-[A-Z0-9-]+$/;
const STEP_NAME_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const isObj = (o) => o !== null && typeof o === 'object' && !Array.isArray(o);
const strArr = (a) => Array.isArray(a) && a.every((x) => typeof x === 'string');
const DEFAULT_TIMEOUT_S = { script: 300, pytest: 1800 };
const MAX_TIMEOUT_S = 7200;

class Refusal extends Error {}
const refuse = (m) => { throw new Refusal(m); };

// ---------------------------------------------------------------- environment, run directory

// Only these variables reach a child. Everything else (PYTEST_ADDOPTS, PYTEST_PLUGINS, PYTHONPATH, PYTHONSTARTUP, PYTHONHOME, NODE_OPTIONS, secrets...) is dropped.
const ENV_ALLOW = new Set(['PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA',
  'PROGRAMFILES', 'PROGRAMFILES(X86)', 'HOMEDRIVE', 'HOMEPATH', 'HOME', 'COMSPEC']);
export function scrubEnv(parent, extra = {}) {
  const out = {};
  for (const [k, v] of Object.entries(parent || {})) if (typeof v === 'string' && ENV_ALLOW.has(k.toUpperCase())) out[k] = v;
  out.PYTHONIOENCODING = 'utf-8';
  return Object.assign(out, extra);
}

export function assertEmptyDir(dir, fsx = fs) {
  if (fsx.readdirSync(dir).length !== 0) throw new Error(`run directory is not empty: ${dir}`);
}

// ---- run-directory protection (see the header) ----
// Windows access masks. Write-capable = anything that lets a principal create, change, delete or re-permission files: FILE_WRITE_DATA 0x2, APPEND 0x4,
// WRITE_EA 0x10, DELETE_CHILD 0x40, WRITE_ATTRIBUTES 0x100, DELETE 0x10000, WRITE_DAC 0x40000, WRITE_OWNER 0x80000, GENERIC_WRITE and GENERIC_ALL.
const SDDL_RIGHTS = { GA: 0x10000000, GR: 0x80000000, GW: 0x40000000, GX: 0x20000000, SD: 0x10000, RC: 0x20000, WD: 0x40000, WO: 0x80000, FA: 0x1f01ff, FR: 0x120089, FW: 0x120116, FX: 0x1200a0 };
const WIN_WRITE_BITS = 0x10000000 | 0x40000000 | 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000;
const WIN_ALLOW_TYPES = new Set(['A', 'OA', 'XA', 'ZA']);
const TRUSTED_INSTALLER_SID = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464';
const SID_RE = /^S-1-\d+(-\d+)+$/;
const ACL_SNAPSHOT = 'acl-snapshot.txt';

function rightsMask(s) {
  if (/^0x[0-9a-fA-F]+$/.test(s)) return Number.parseInt(s, 16) >>> 0;
  if (s.length === 0 || s.length % 2 !== 0) throw new Error(`unparsable access rights "${s}"`);
  let m = 0;
  for (let i = 0; i < s.length; i += 2) {
    const v = SDDL_RIGHTS[s.slice(i, i + 2)];
    if (v === undefined) throw new Error(`unknown access right "${s.slice(i, i + 2)}"`);
    m = (m | v) >>> 0;
  }
  return m;
}
// Parses the DACL line of `icacls /save` (SDDL: locale independent, unlike icacls' localized plain output). Anything unexpected throws (fail closed).
export function parseSddl(text) {
  const line = String(text).split(/\r?\n/).map((l) => l.trim()).find((l) => l.startsWith('D:'));
  if (!line) throw new Error('no DACL in the permission snapshot');
  const m = /^D:([A-Z]*)((?:\([^()]*\))*)$/.exec(line);
  if (!m) throw new Error('unparsable DACL');
  const aces = [...m[2].matchAll(/\(([^()]*)\)/g)].map((x) => {
    const f = x[1].split(';');
    if (f.length < 6 || !f[5]) throw new Error('unparsable access control entry');
    return { type: f[0], mask: rightsMask(f[2]), trustee: f[5] };
  });
  return { protectedDacl: m[1].includes('P'), aces };
}
function aclProblems(acl, sid, mode) {
  const own = new Set(['SY', 'BA', 'CO', 'OW', sid, TRUSTED_INSTALLER_SID]);
  const p = [];
  if (mode === 'private' && !acl.protectedDacl) p.push('the DACL still inherits permissions from its parent (not protected)');
  for (const a of acl.aces) {
    if (!WIN_ALLOW_TYPES.has(a.type) || own.has(a.trustee)) continue; // deny/audit entries never widen access; our own principals are fine
    if (mode === 'private') p.push(`grants access to ${a.trustee}`);
    else if ((a.mask & WIN_WRITE_BITS) !== 0) p.push(`grants write-capable access to ${a.trustee}`);
  }
  if (mode === 'private' && !acl.aces.some((a) => WIN_ALLOW_TYPES.has(a.type) && a.trustee === sid)) p.push('the current user has no access entry');
  return p;
}
function defaultOps() {
  const systemRoot = process.env.SystemRoot || process.env.SYSTEMROOT || process.env.windir || process.env.WINDIR || 'C:\\Windows';
  return {
    platform: process.platform, fs, systemRoot, getuid: typeof process.getuid === 'function' ? () => process.getuid() : undefined,
    icaclsExists: (p) => fs.existsSync(p),
    exec: (file, args) => spawnSync(file, args, { shell: false, encoding: 'utf8', timeout: 30000, windowsHide: true, env: scrubEnv(process.env) }),
  };
}
const sysTool = (ops, name) => path.join(ops.systemRoot, 'System32', name);
function mustRun(ops, tool, args, what) {
  if (!ops.icaclsExists(tool)) throw new Error(`${path.basename(tool)} was not found; cannot establish run-directory security`);
  const r = ops.exec(tool, args);
  if (!r || r.error || r.status !== 0) throw new Error(`${what} failed; cannot establish run-directory security`);
  return r;
}
function currentSid(ops) {
  const r = mustRun(ops, sysTool(ops, 'whoami.exe'), ['/user', '/fo', 'csv', '/nh'], 'whoami');
  const m = /"[^"]*","(S-1-[^"]+)"/.exec(String(r.stdout || ''));
  if (!m || !SID_RE.test(m[1])) throw new Error('could not determine the current user SID; cannot establish run-directory security');
  return m[1];
}
// Snapshot a directory's DACL through icacls into `scratchDir` (a directory we have already made private), parse and delete the snapshot.
function readWindowsAcl(dir, scratchDir, ops) {
  const file = path.join(scratchDir, ACL_SNAPSHOT);
  try {
    mustRun(ops, sysTool(ops, 'icacls.exe'), [dir, '/save', file], 'icacls /save');
    const b = ops.fs.readFileSync(file);
    const text = b.length >= 2 && b[0] === 0xff && b[1] === 0xfe ? b.subarray(2).toString('utf16le') : b.length >= 2 && b[1] === 0 ? b.toString('utf16le') : b.toString('utf8');
    return parseSddl(text);
  } finally { try { ops.fs.unlinkSync(file); } catch { /* absent */ } }
}

// Makes `dir` private to the current user (POSIX mode 0700; Windows: protected DACL granting only the current user's SID) and verifies the outcome by
// reading it back. Throws if security cannot be established.
export function securePrivateDir(dir, ops = defaultOps()) {
  if (ops.platform === 'win32') {
    const sid = currentSid(ops);
    const icacls = sysTool(ops, 'icacls.exe');
    mustRun(ops, icacls, [dir, '/inheritance:r'], 'icacls /inheritance:r');
    mustRun(ops, icacls, [dir, '/grant:r', `*${sid}:(OI)(CI)F`], 'icacls /grant:r');
    const problems = aclProblems(readWindowsAcl(dir, dir, ops), sid, 'private');
    if (problems.length) throw new Error(`run directory is not private: ${problems.join('; ')}`);
    return;
  }
  const before = ops.fs.lstatSync(dir);
  if (before.isSymbolicLink() || !before.isDirectory()) throw new Error('run directory is a symbolic link or not a directory');
  ops.fs.chmodSync(dir, 0o700);
  const st = ops.fs.lstatSync(dir);
  if ((st.mode & 0o777) !== 0o700) throw new Error(`run directory mode is ${(st.mode & 0o777).toString(8)}, not private (700)`);
  if (typeof ops.getuid === 'function' && st.uid !== ops.getuid()) throw new Error('run directory is not owned by the current user');
}
// Rejects a temp base that other principals could write to: they could delete or swap the run directory. `scratchDir` is our private directory.
function assertSafeBase(base, scratchDir, ops) {
  if (ops.platform === 'win32') {
    const sid = currentSid(ops);
    const problems = aclProblems(readWindowsAcl(base, scratchDir, ops), sid, 'nowrite');
    if (problems.length) throw new Error(`unsafe temp directory ${base} (${problems.join('; ')}); set TEMP/TMP to a private directory for this shell`);
    return;
  }
  const st = ops.fs.statSync(base);
  if (!st.isDirectory()) throw new Error(`temp base is not a directory: ${base}`);
  if ((st.mode & 0o022) !== 0 && (st.mode & 0o1000) === 0) throw new Error(`unsafe temp directory ${base}: group- or world-writable without the sticky bit (mode ${(st.mode & 0o7777).toString(8)}); set TMPDIR to a private directory`);
}
// A fresh, unpredictable, private directory that must start empty, created inside a verified-safe base. Fails closed; leaves nothing behind on failure.
export function freshRunDir(base = os.tmpdir(), ops = defaultOps()) {
  if (!path.isAbsolute(base)) throw new Error('temp base must be an absolute path');
  const d = ops.fs.mkdtempSync(path.join(base, 'gate-'));
  try {
    securePrivateDir(d, ops);
    assertSafeBase(base, d, ops);
    assertEmptyDir(d, ops.fs);
    return d;
  } catch (e) {
    try { ops.fs.unlinkSync(path.join(d, ACL_SNAPSHOT)); } catch { /* absent */ }
    try { ops.fs.rmdirSync(d); } catch { /* best effort: only ever an empty directory we just made */ }
    throw e;
  }
}

// ---------------------------------------------------------------- runner block validation

const cleanRel = (p) => {
  if (typeof p !== 'string' || !p.trim()) return false;
  const g = p.replace(/\\/g, '/');
  if (g.startsWith('/') || g.includes(':') || /[\u0000-\u001f]/.test(g)) return false;
  return !g.split('/').some((s) => s === '..' || s === '');
};
const timeoutOk = (t) => t === undefined || (Number.isInteger(t) && t >= 1 && t <= MAX_TIMEOUT_S);

export function validateRunnerBlock(def) {
  const p = [];
  const r = isObj(def) ? def.runner : null;
  if (!isObj(r)) return ['gate has no runner block'];
  if (!Array.isArray(r.steps) || r.steps.length === 0 || r.steps.length > 8) return ['runner.steps must be a non-empty array of at most 8 steps'];
  const names = new Set();
  let pytest = 0;
  r.steps.forEach((s, i) => {
    const w = `step ${i}`;
    if (!isObj(s)) { p.push(`${w} is not an object`); return; }
    if (typeof s.name !== 'string' || !STEP_NAME_RE.test(s.name)) p.push(`${w} has an invalid name`);
    else if (names.has(s.name)) p.push(`${w} duplicates the name ${s.name}`);
    else names.add(s.name);
    if (!timeoutOk(s.timeout_s)) p.push(`${w} has an invalid timeout_s`);
    if (s.kind === 'builtin') {
      if (!(['manifest-scope', 'manifest-scan'].includes(s.builtin) && s.name === s.builtin)) p.push(`${w}: a builtin step must be named exactly manifest-scope or manifest-scan and use the same builtin`);
      return;
    }
    if (s.cwd !== undefined && !(cleanRel(s.cwd) || s.cwd === '.')) p.push(`${w} has an invalid cwd`);
    if (s.kind === 'script') {
      if (!strArr(s.argv) || s.argv.length < 2 || s.argv[0] !== 'node') p.push(`${w}: script argv must be an array of strings starting with "node" plus a script`);
    } else if (s.kind === 'pytest') {
      pytest++;
      if (s.argv_tail !== undefined && !strArr(s.argv_tail)) p.push(`${w}: argv_tail must be an array of strings`);
      if (s.python_args !== undefined && !strArr(s.python_args)) p.push(`${w}: python_args must be an array of strings`);
      if (s.resolve_args !== undefined && !strArr(s.resolve_args)) p.push(`${w}: resolve_args must be an array of strings`);
      if (s.launcher !== undefined && !(strArr(s.launcher) && s.launcher.length > 0 && s.launcher.every((x) => x))) p.push(`${w}: launcher must be a non-empty array of strings`);
      if (s.collect_only !== undefined && typeof s.collect_only !== 'boolean') p.push(`${w}: collect_only must be a boolean`);
    } else p.push(`${w} has an unknown kind`);
  });
  if (pytest > 1) p.push('at most one pytest step is allowed');
  if (r.conditional !== undefined) {
    const c = r.conditional;
    if (!isObj(c)) p.push('conditional must be an object');
    else {
      if (pytest !== 1) p.push('conditional requires exactly one pytest step');
      if (!(strArr(c.when_diff_matches) && c.when_diff_matches.length > 0)) p.push('conditional.when_diff_matches must be a non-empty array of globs');
      if (!(isObj(c.env) && Object.entries(c.env).every(([k, v]) => /^[A-Z][A-Z0-9_]*$/.test(k) && typeof v === 'string'))) p.push('conditional.env must map variable names to strings');
      if (!cleanRel(c.required_testcase_manifest)) p.push('conditional.required_testcase_manifest must be a clean relative path');
      if (!timeoutOk(c.timeout_s)) p.push('conditional.timeout_s is invalid');
    }
  }
  return p;
}

// ---------------------------------------------------------------- junit extraction (no XML library; strict; independent recount)

const unescapeXml = (s) => s.replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const attrsOf = (s) => { const o = {}; for (const m of s.matchAll(/([A-Za-z_][\w:.-]*)\s*=\s*"([^"]*)"/g)) o[m[1]] = unescapeXml(m[2]); return o; };
const countOf = (re, s) => (s.match(re) || []).length;

// Returns { ok, error } or { ok:true, totals:{tests,failures,errors,skipped}, counted, cases:[{name,classname,failed,errored,skipped}] }.
// ok is false for anything unexpected: empty, truncated, unbalanced, missing attributes, attribute totals that disagree with the element counts.
export function parseJunit(text) {
  const bad = (error) => ({ ok: false, error });
  if (typeof text !== 'string' || !text.trim()) return bad('junit is empty');
  const t = text.replace(/^﻿/, '').replace(/<!\[CDATA\[[\s\S]*?\]\]>/g, '').replace(/<!--[\s\S]*?-->/g, '').replace(/^\s*<\?xml[^>]*\?>/, '').trim();
  const root = /^<(testsuites|testsuite)\b/.exec(t);
  if (!root) return bad('junit root element is not testsuites or testsuite');
  if (!t.endsWith(`</${root[1]}>`)) return bad('junit is truncated');
  const stack = [];
  const suiteAttrs = [];
  for (const m of t.matchAll(/<(\/?)(testsuites|testsuite)\b([^>]*?)(\/?)>/g)) {
    const [, closing, name, attrs, selfClose] = m;
    if (closing) { if (stack.pop() !== name) return bad('junit suite elements are unbalanced'); continue; }
    if (name === 'testsuite') suiteAttrs.push(attrsOf(attrs));
    if (!selfClose) stack.push(name);
  }
  if (stack.length || suiteAttrs.length === 0) return bad('junit suite elements are unbalanced or absent');
  const totals = { tests: 0, failures: 0, errors: 0, skipped: 0 };
  for (const a of suiteAttrs) for (const k of Object.keys(totals)) {
    if (!/^\d+$/.test(a[k] ?? '')) return bad(`junit testsuite attribute ${k} is missing or not an integer`);
    totals[k] += Number(a[k]);
  }
  const cases = [];
  let inCases = { failures: 0, errors: 0, skipped: 0 };
  for (const m of t.matchAll(/<testcase\b([^>]*?)(?:\/>|>([\s\S]*?)<\/testcase>)/g)) {
    const a = attrsOf(m[1]);
    const body = m[2] || '';
    const f = countOf(/<failure\b/g, body); const e = countOf(/<error\b/g, body); const s = countOf(/<skipped\b/g, body);
    inCases = { failures: inCases.failures + f, errors: inCases.errors + e, skipped: inCases.skipped + s };
    cases.push({ name: a.name ?? '', classname: a.classname ?? '', failed: f > 0, errored: e > 0, skipped: s > 0 });
  }
  const counted = { tests: cases.length, failures: countOf(/<failure\b/g, t), errors: countOf(/<error\b/g, t), skipped: countOf(/<skipped\b/g, t) };
  if (counted.failures !== inCases.failures || counted.errors !== inCases.errors || counted.skipped !== inCases.skipped) return bad('junit has result elements outside testcase elements');
  for (const k of Object.keys(totals)) if (totals[k] !== counted[k]) return bad(`junit attribute total for ${k} (${totals[k]}) disagrees with the element count (${counted[k]})`);
  return { ok: true, totals, counted, cases };
}

// Required harness cells: JSON array of strings, or { "cells": [...] }. A cell is satisfied when at least one testcase has name === cell or
// "classname.name" === cell and every such testcase has no failure, error or skip.
export function loadCells(file) {
  let j;
  try { j = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { throw new Error('required testcase manifest is missing, unreadable or not JSON'); }
  const cells = Array.isArray(j) ? j : isObj(j) && Array.isArray(j.cells) ? j.cells : null;
  if (!cells || cells.length === 0 || !cells.every((c) => typeof c === 'string' && c) || new Set(cells).size !== cells.length) throw new Error('required testcase manifest is malformed');
  return cells;
}
export function checkCells(cells, parsed) {
  let passed = 0;
  for (const cell of cells) {
    const m = parsed.cases.filter((c) => c.name === cell || `${c.classname}.${c.name}` === cell);
    if (m.length > 0 && m.every((c) => !c.failed && !c.errored && !c.skipped)) passed++;
  }
  return { expected: cells.length, passed };
}

// ---------------------------------------------------------------- interpreter allowlist (human-provisioned trusted-interpreters.json)

function loadAllowlist() {
  let j;
  try { j = JSON.parse(fs.readFileSync(path.join(ORCH, 'trusted-interpreters.json'), 'utf8')); } catch { throw new Error('interpreter allowlist is unreadable or not JSON'); }
  const ok = isObj(j) && j.schema === 1 && Object.keys(j).length === 2 && Array.isArray(j.interpreters) && j.interpreters.length > 0
    && j.interpreters.every((x) => isObj(x) && Object.keys(x).length === 2 && typeof x.path === 'string' && path.isAbsolute(x.path) && typeof x.sha256 === 'string' && HEX64_RE.test(x.sha256));
  if (!ok) throw new Error('interpreter allowlist is malformed (schema 1, non-empty, absolute paths, lowercase sha256)');
  return j.interpreters;
}
const normPath = (p) => (process.platform === 'win32' ? path.resolve(p).toLowerCase() : path.resolve(p));

// Resolve the launcher to the interpreter's real path, hash that file. The caller compares both with the allowlist and then runs THAT path.
function resolveInterpreter(step, env) {
  const [cmd, ...largs] = step.launcher || ['py'];
  const r = spawnSync(cmd, [...largs, ...(step.resolve_args || ['-c', 'import sys; print(sys.executable)'])], { cwd: ROOT, env, shell: false, encoding: 'utf8', timeout: 30000, windowsHide: true });
  if (r.error || r.status !== 0) return { reason: 'the interpreter launcher failed to report its interpreter' };
  const lines = String(r.stdout || '').split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  const p = lines[lines.length - 1];
  if (!p || !path.isAbsolute(p)) return { reason: 'the launcher did not report an absolute interpreter path' };
  let bytes;
  try { if (!fs.statSync(p).isFile()) return { reason: 'the reported interpreter is not a file' }; bytes = fs.readFileSync(p); } catch { return { reason: 'the reported interpreter does not exist or is unreadable' }; }
  return { path: path.resolve(p), sha256: sha256(bytes) };
}

// ---------------------------------------------------------------- step execution

const statusOf = (r) => (r.error || r.signal || typeof r.status !== 'number' ? null : r.status);
function spawnLogged(argv, { cwd, env, timeoutS, logFile }) {
  const fd = fs.openSync(logFile, 'w');
  try {
    return spawnSync(argv[0], argv.slice(1), { cwd, env, shell: false, timeout: timeoutS * 1000, killSignal: 'SIGKILL', stdio: ['ignore', fd, fd], windowsHide: true });
  } finally { fs.closeSync(fd); }
}
const tailOf = (file, bytes = 8192) => { try { const b = fs.readFileSync(file); return b.subarray(Math.max(0, b.length - bytes)).toString('utf8'); } catch { return ''; } };
const argvHash = (argv) => sha256(JSON.stringify(argv));

function runScriptStep(step, ctx) {
  const argv = [process.execPath, ...step.argv.slice(1)];
  const log = path.join(ctx.runDir, `${step.name}.log`);
  const r = spawnLogged(argv, { cwd: path.resolve(ROOT, step.cwd || '.'), env: scrubEnv(process.env), timeoutS: step.timeout_s ?? DEFAULT_TIMEOUT_S.script, logFile: log });
  const st = statusOf(r);
  return { rec: { name: step.name, argv_sha256: argvHash(argv), exit_status: st }, result: st === null ? 'UNKNOWN' : st === 0 ? 'PASS' : 'FAIL', log, reason: st === null ? 'killed, timed out or could not start' : '' };
}

function runManifestScopeStep(step, ctx) {
  const app = manifestScopeApplicability(ctx.cs);
  const sha = sha256('builtin:manifest-scope:v1');
  if (app === 'NOT_APPLICABLE') return { rec: { name: 'manifest-scope', applicable: false, reason: NA_STEP_REASON, exit_status: null }, result: 'PASS', reason: '' };
  if (app === 'FAIL') return { rec: { name: 'manifest-scope', argv_sha256: sha, exit_status: 1 }, result: 'FAIL', reason: 'the Change Set may include .claude/ or is malformed and declares no baseline_manifest' };
  const r = manifestScopeCheck(ctx.cs, ROOT);
  return { rec: { name: 'manifest-scope', argv_sha256: sha, exit_status: r.ok ? 0 : 1 }, result: r.ok ? 'PASS' : 'FAIL', reason: r.problems.slice(0, 8).join('; ') };
}

const MAX_SCAN_BYTES = 2_000_000;
const ordinalCmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
// Scans governance files (paths relative to <root>/.claude) with the existing patterns.mjs rules. Unlike scan.mjs, a file that cannot be read or is too
// large to scan is reported (and makes the step FAIL) instead of being skipped. `hashes` lists exactly the files that were really read and scanned.
export function scanGovernanceFiles(rels, root = ROOT, readFile = fs.readFileSync) {
  const res = { scanned: 0, findings: [], unreadable: [], oversized: [], hashes: [] };
  for (const rel of rels) {
    let bytes;
    try { bytes = readFile(path.join(root, '.claude', rel)); } catch { res.unreadable.push(rel); continue; }
    if (!bytes || typeof bytes.length !== 'number') { res.unreadable.push(rel); continue; }
    if (bytes.length > MAX_SCAN_BYTES) { res.oversized.push(rel); continue; }
    const text = Buffer.from(bytes).toString('utf8');
    const hits = scanSecrets(text).map((h) => ({ ...h, kind: 'secret' }));
    if (/\.sql$/i.test(rel)) hits.push(...scanSql(text).map((h) => ({ ...h, kind: 'sql' })));
    for (const h of hits) res.findings.push({ rel, line: h.line, kind: h.kind, rule: h.rule });
    res.scanned++;
    res.hashes.push([rel, sha256(bytes)]);
  }
  return res;
}

function runManifestScanStep(step, ctx) {
  const rec = (argv, exit) => ({ name: 'manifest-scan', argv_sha256: argv, exit_status: exit });
  const base = sha256('builtin:manifest-scan:v1');
  const fail = (reason, argv = base) => { console.log(`manifest-scan: ${reason}`); return { rec: rec(argv, 1), result: 'FAIL', reason }; };
  const app = manifestScopeApplicability(ctx.cs);
  if (app === 'NOT_APPLICABLE') return { rec: rec(sha256('builtin:manifest-scan:not-applicable:v1'), 0), result: 'PASS', reason: '' };
  if (app === 'FAIL') return fail('the Change Set may include .claude/ (or is malformed) and declares no baseline_manifest, so governance files cannot be enumerated');
  const r = manifestScopeCheck(ctx.cs, ROOT);
  if (r.h_manifest_sha256 === null) return fail(`cannot establish the baseline diff (${r.problems[0] || 'unknown'})`);
  const rels = [...r.added, ...r.modified].sort(ordinalCmp);
  if (rels.length === 0) return fail('nothing to scan: the baseline diff is empty (refusing a vacuous PASS)');
  const s = scanGovernanceFiles(rels, ROOT);
  for (const f of s.findings) console.log(`BLOCKING ${f.rel}:${f.line} ${f.kind}:${f.rule}`); // rule ids and line numbers only, never the matched value
  for (const u of s.unreadable) console.log(`manifest-scan: cannot read ${u}`);
  for (const u of s.oversized) console.log(`manifest-scan: ${u} is too large to scan (unscannable)`);
  const lines = [...s.hashes].sort((a, b) => ordinalCmp(a[0], b[0])).map(([rel, h]) => `${h}  ${rel}`);
  const argv = sha256(`builtin:manifest-scan:v1\n${lines.join('\n')}\n`); // binds the exact scanned files and their content digests into the evidence
  const bad = s.findings.length || s.unreadable.length || s.oversized.length || s.scanned !== rels.length;
  if (bad) return { rec: rec(argv, 1), result: 'FAIL', reason: `${s.findings.length} finding(s), ${s.unreadable.length} unreadable, ${s.oversized.length} oversized of ${rels.length} governance file(s)` };
  console.log(`manifest-scan: clean (${s.scanned} governance file(s) scanned)`);
  return { rec: rec(argv, 0), result: 'PASS', reason: '' };
}

function runPytestStep(step, ctx) {
  const out = { rec: { name: step.name, argv_sha256: argvHash(['pytest-step-not-run']), exit_status: null }, result: 'UNKNOWN', counts: null, junit_sha256: null, interpreter: null, requiredCells: null, reason: '' };
  let allow;
  try { allow = loadAllowlist(); } catch (e) { out.reason = e.message; return out; }
  const base = scrubEnv(process.env);
  const res = resolveInterpreter(step, base);
  if (!res.sha256) { out.reason = res.reason; return out; }
  out.interpreter = { path: res.path, sha256: res.sha256 };
  if (!allow.some((a) => normPath(a.path) === normPath(res.path) && a.sha256 === res.sha256)) { out.reason = 'the interpreter path and hash are not in the trusted allowlist'; return out; }
  const junit = path.join(ctx.runDir, 'junit.xml');
  const argv = [res.path, ...(step.python_args || ['-m', 'pytest']), ...(step.argv_tail || []), `--junitxml=${junit}`, '-p', 'no:cacheprovider'];
  out.rec.argv_sha256 = argvHash(argv);
  const timeoutS = ctx.harness && ctx.conditional.timeout_s ? ctx.conditional.timeout_s : step.timeout_s ?? DEFAULT_TIMEOUT_S.pytest;
  const log = path.join(ctx.runDir, `${step.name}.log`);
  out.log = log;
  const r = spawnLogged(argv, { cwd: path.resolve(ROOT, step.cwd || '.'), env: scrubEnv(process.env, ctx.harness ? ctx.conditional.env : {}), timeoutS, logFile: log });
  const st = statusOf(r);
  out.rec.exit_status = st;
  let bytes = null;
  try { bytes = fs.readFileSync(junit); } catch { /* missing */ }
  out.junit_sha256 = bytes ? sha256(bytes) : null;
  const parsed = bytes ? parseJunit(bytes.toString('utf8')) : null;
  if (parsed && parsed.ok) out.counts = { ...parsed.totals };
  if (st === null) { out.reason = 'the child was killed, timed out or could not start'; return out; }
  if (st !== 0) { out.result = 'FAIL'; out.reason = `exit status ${st}`; return out; } // the OS status wins over any junit content
  if (!parsed || !parsed.ok) { out.counts = null; out.reason = parsed ? parsed.error : 'junit.xml is missing'; return out; }
  if (step.collect_only) {
    const found = [...tailOf(log).matchAll(/(\d+) tests? collected/g)].pop();
    const n = found ? Number(found[1]) : 0;
    if (!(n > 0)) { out.counts = null; out.reason = 'no collected-test count was reported by the child'; return out; }
    out.counts = { tests: n, failures: parsed.totals.failures, errors: parsed.totals.errors, skipped: parsed.totals.skipped };
  } else if (parsed.totals.tests === 0) { out.reason = 'zero tests ran'; return out; }
  if (parsed.totals.failures > 0 || parsed.totals.errors > 0) { out.result = 'FAIL'; out.reason = 'junit reports failures or errors'; return out; }
  out.result = 'PASS';
  if (ctx.harness) {
    try {
      const cells = loadCells(path.resolve(ROOT, ctx.conditional.required_testcase_manifest));
      out.requiredCells = checkCells(cells, parsed);
      if (out.requiredCells.passed !== out.requiredCells.expected) { out.result = 'FAIL'; out.reason = `required harness cells not satisfied (${out.requiredCells.passed}/${out.requiredCells.expected})`; }
    } catch (e) { out.result = 'FAIL'; out.reason = e.message; }
  }
  return out;
}

// ---------------------------------------------------------------- main

function runGate(gateId) {
  if (!GATE_ID_RE.test(gateId)) refuse('gate id must match ^G-[A-Z0-9-]+$');
  let active;
  try { active = readActiveId() && getActive(); } catch (e) { refuse(`cannot read the active run: ${e.message}`); }
  if (!active) refuse('no active run');
  if (!active.approved) refuse(`run ${active.id} is not approved: ${active.reason}`);
  const def = loadGates().gates.find((g) => g.id === gateId);
  if (!def) refuse(`unknown gate ${gateId}`);
  if (def.autonomy !== 'autonomous') refuse(`gate ${gateId} is ${def.autonomy}/${def.status}; it cannot be run autonomously`);
  const problems = validateRunnerBlock(def);
  if (problems.length) refuse(`gate ${gateId} has no usable runner block: ${problems.join('; ')}`);
  const cs = active.changeSet;
  const csSha = sha256(fs.readFileSync(changeSetPath(active.id), 'utf8'));
  let td0; let b0;
  try { td0 = treeDigest(ROOT); b0 = computeBindings(cs, ROOT, td0); } catch (e) { refuse(`cannot read git state or a bound file: ${e.message}`); }

  const runDir = freshRunDir();
  const harness = conditionalHarnessApplies(td0.paths, def);
  const ctx = { runDir, cs, harness, conditional: def.runner.conditional };
  const startedAt = nowIso();
  const records = [];
  let pytestOut = null; let overall = 'PASS'; let failing = null; let reason = '';
  for (const step of def.runner.steps) {
    const o = step.kind === 'builtin' ? (step.builtin === 'manifest-scan' ? runManifestScanStep(step, ctx) : runManifestScopeStep(step, ctx)) : step.kind === 'script' ? runScriptStep(step, ctx) : (pytestOut = runPytestStep(step, ctx));
    records.push(o.rec);
    if (o.log) console.log(`--- ${step.name} (last lines of the child log; informational only) ---\n${tailOf(o.log, 1500).split(/\r?\n/).slice(-15).join('\n')}`);
    if (o.result !== 'PASS') { overall = o.result; failing = o; reason = `${step.name}: ${o.reason}`; break; }
  }
  const finishedAt = nowIso();
  if (overall === 'PASS') { // nothing the gate bound may have moved while it ran
    try { const td1 = treeDigest(ROOT); const b1 = computeBindings(cs, ROOT, td1); if (JSON.stringify(b0) !== JSON.stringify(b1)) { overall = 'UNKNOWN'; reason = 'the working tree or an evidence-bound file changed during the run'; } }
    catch (e) { overall = 'UNKNOWN'; reason = `cannot re-read state after the run: ${e.message}`; }
  }
  const pytest = pytestOut;
  const entry = {
    source: 'runner', schema: 1, gate: gateId, covers: [gateId], kind: def.runner.steps.some((s) => s.kind === 'pytest') ? 'pytest' : 'script', result: overall,
    exit_status: overall === 'PASS' ? 0 : failing ? failing.rec.exit_status : null, counts: pytest ? pytest.counts : null, run_id: crypto.randomUUID(), ledger_run: active.id,
    change_set_sha256: csSha, steps: records, interpreter: pytest ? pytest.interpreter : null, ...Object.fromEntries(BINDING_KEYS.map((k) => [k, b0[k]])),
    started_at: startedAt, finished_at: finishedAt, junit_sha256: pytest ? pytest.junit_sha256 : null, required_cells: pytest ? pytest.requiredCells : null,
  };
  if (entry.kind === 'script') { entry.counts = null; entry.interpreter = null; entry.junit_sha256 = null; }
  const v = validateEvidenceV1({ at: nowIso(), ...entry });
  if (!v.ok) refuse(`internal error: the runner produced an invalid entry (${v.errors.join('; ')}); no evidence was written`);
  appendEvidence(active.id, entry);
  console.log(`GATE ${gateId}: ${overall}${reason ? ` (${reason})` : ''} | run_id ${entry.run_id} | steps ${records.map((r) => `${r.name}=${r.applicable === false ? 'n/a' : r.exit_status}`).join(', ')} | run directory ${runDir}`);
  return overall === 'PASS' ? 0 : 1;
}

function main() {
  const args = process.argv.slice(2);
  try {
    if (args.length !== 1) refuse('usage: node .claude/orchestration/run-gate.mjs <GATE_ID> (exactly one argument)');
    process.exit(runGate(args[0]));
  } catch (e) {
    console.error(`run-gate refused: ${e.message}`); // any unexpected error also refuses: no evidence is written
    process.exit(2);
  }
}

const self = fileURLToPath(import.meta.url);
const invoked = process.argv[1] ? path.resolve(process.argv[1]) : '';
if (process.platform === 'win32' ? self.toLowerCase() === invoked.toLowerCase() : self === invoked) main();
