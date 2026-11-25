// InboundCheck autonomous team: shared ledger/approval/glob helpers.
// Used by hooks (guard-*.mjs, record-gate.mjs, ...) and by ledger.mjs. Node >= 18, no dependencies.
// Root and orchestration dir are derived from THIS file's location, never from env or tool input.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const ORCH = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(ORCH, '..', '..');
export const RUNS = path.join(ORCH, 'runs');
export const APPROVALS = path.join(ORCH, 'approvals');
export const ACTIVE = path.join(ORCH, 'ACTIVE_RUN');
export const RUN_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$/;

export const sha256 = (s) => crypto.createHash('sha256').update(s).digest('hex');
export const toPosix = (p) => p.split(path.sep).join('/');
export const nowIso = () => new Date().toISOString();

export function readJson(file, fallback = undefined) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (e) { if (fallback !== undefined) return fallback; throw e; }
}

export function writeJsonAtomic(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n', 'utf8');
  fs.renameSync(tmp, file);
}

// Directory-based lock (works on Windows and POSIX). Parallel subagents and hooks may write concurrently.
export function withLock(name, fn, timeoutMs = 8000) {
  const dir = path.join(ORCH, `.lock-${name}`);
  const start = Date.now();
  for (;;) {
    try { fs.mkdirSync(dir); break; }
    catch (e) {
      if (e.code !== 'EEXIST') throw e;
      try { if (Date.now() - fs.statSync(dir).mtimeMs > 30000) fs.rmdirSync(dir); } catch { /* raced */ }
      if (Date.now() - start > timeoutMs) throw new Error(`ledger lock timeout (${name})`);
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 40);
    }
  }
  try { return fn(); } finally { try { fs.rmdirSync(dir); } catch { /* ignore */ } }
}

// ---- globs (repo-relative, forward slashes, case-insensitive for Windows) ----
export function globToRegExp(glob) {
  let re = '';
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i];
    if (c === '*') {
      if (glob[i + 1] === '*') {
        if (glob[i + 2] === '/') { re += '(?:.*/)?'; i += 2; } else { re += '.*'; i += 1; }
      } else re += '[^/]*';
    } else if (c === '?') re += '[^/]';
    else re += c.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  }
  return new RegExp(`^${re}$`, 'i');
}
export const matchesAny = (rel, globs = []) => globs.some((g) => globToRegExp(g).test(rel));

export function relFromRoot(abs) {
  const r = path.relative(ROOT, path.resolve(abs));
  if (r === '' ) return '';
  if (r.startsWith('..') || path.isAbsolute(r)) return null; // outside repo
  return toPosix(r);
}

// ---- config ----
export const loadBoundaries = () => readJson(path.join(ORCH, 'boundaries.json'));
export const loadGates = () => readJson(path.join(ORCH, 'gates.json'));

// ---- runs / approval ----
export const runDir = (id) => path.join(RUNS, id);
export const ledgerPath = (id) => path.join(runDir(id), 'ledger.json');
export const changeSetPath = (id) => path.join(runDir(id), 'change-set.json');
export const approvalPath = (id) => path.join(APPROVALS, `${id}.json`);

export function readActiveId() {
  let raw;
  try { raw = fs.readFileSync(ACTIVE, 'utf8').trim(); } catch { return null; }
  if (!raw) return null;
  if (!RUN_ID_RE.test(raw)) throw new Error('ACTIVE_RUN contains an invalid run id');
  return raw;
}

// Returns null when no run is active. Otherwise { id, changeSet, approved, reason }.
export function getActive() {
  const id = readActiveId();
  if (!id) return null;
  let raw;
  try { raw = fs.readFileSync(changeSetPath(id), 'utf8'); }
  catch { return { id, changeSet: null, approved: false, reason: 'change-set.json is missing' }; }
  let changeSet;
  try { changeSet = JSON.parse(raw); }
  catch { return { id, changeSet: null, approved: false, reason: 'change-set.json is not valid JSON' }; }
  let marker = null;
  try { marker = readJson(approvalPath(id)); } catch { /* not approved */ }
  if (!marker) return { id, changeSet, approved: false, reason: 'no user approval marker (user must run: node .claude/orchestration/ledger.mjs approve ' + id + ')' };
  if (marker.run_id !== id || marker.change_set_sha256 !== sha256(raw)) {
    return { id, changeSet, approved: false, reason: 'change-set.json changed after approval; the user must re-approve' };
  }
  return { id, changeSet, approved: true, reason: 'approved' };
}

// ---- ledger ----
export const TASK_STATUSES = ['PENDING', 'IN_PROGRESS', 'IN_REVIEW', 'NEEDS_FIX', 'BLOCKED', 'DONE'];

export function loadLedger(id) { return readJson(ledgerPath(id)); }
export function mutateLedger(id, fn) {
  return withLock(`ledger-${id}`, () => {
    const raw = fs.readFileSync(ledgerPath(id), 'utf8');
    const l = JSON.parse(raw);
    // A hand-edited evidence record with a repeated key reads as its LAST value after JSON.parse, and this rewrite would erase the repeat. Persist a taint
    // marker on the record instead: the unknown key makes it fail the strict schema-1 validator forever, so it can never satisfy a gate.
    for (const i of taintedEvidenceIndexes(raw)) if (isObj(l.evidence && l.evidence[i])) l.evidence[i].tainted_duplicate_keys = true;
    const out = fn(l);
    l.updated_at = nowIso();
    writeJsonAtomic(ledgerPath(id), l);
    return out;
  });
}

export function appendEvent(id, ev) {
  return mutateLedger(id, (l) => { (l.events ||= []).push({ at: nowIso(), ...ev }); if (l.events.length > 2000) l.events.splice(0, l.events.length - 2000); });
}
export function appendEvidence(id, evd) {
  return mutateLedger(id, (l) => {
    (l.evidence ||= []).push({ at: nowIso(), ...evd });
    if (l.evidence.length > 1000) l.evidence.splice(0, l.evidence.length - 1000);
  });
}

// Compact recovery summary (used by SessionStart hook and `ledger.mjs status`). Intentionally short.
export function summarize(id) {
  const l = loadLedger(id);
  const t = l.tasks || [];
  const by = (s) => t.filter((x) => x.status === s).map((x) => x.id);
  const done = new Set(by('DONE'));
  const eligible = t.filter((x) => x.status === 'PENDING' && (x.depends_on || []).every((d) => done.has(d))).map((x) => x.id);
  const act = getActive();
  const lines = [
    `RUN ${l.run_id} | objective: ${l.objective}`,
    `change-set: ${act && act.id === id ? (act.approved ? 'APPROVED by user' : 'NOT APPROVED (' + act.reason + ')') : 'not the active run'} | base HEAD ${l.base_head || '?'}`,
    `tasks: ${t.length} total | DONE ${done.size} | IN_PROGRESS [${by('IN_PROGRESS')}] | IN_REVIEW [${by('IN_REVIEW')}] | NEEDS_FIX [${by('NEEDS_FIX')}] | BLOCKED [${by('BLOCKED')}]`,
    `next eligible: [${eligible}]`,
  ];
  for (const x of t.filter((x) => x.status !== 'DONE')) {
    lines.push(`  ${x.id} ${x.status} owner=${x.owner} risk=${x.risk} cycles=${x.correction_cycles || 0}/2 files=${(x.files || []).length}${x.blocked_reason ? ' blocked: ' + x.blocked_reason : ''}`);
  }
  lines.push('Resume: read the run ledger via `node .claude/orchestration/ledger.mjs status`, then follow skill inboundcheck-autonomous-orchestrator.');
  return lines.join('\n');
}

// =====================================================================================================================
// Trusted gate evidence helpers (design v1/v2/v2.1/v2.2). Shared by run-gate.mjs (producer) and ledger.mjs done() (verifier).
// Every function takes an explicit `root` (default: this checkout) so tests can run against temp trees. None of them writes.
// =====================================================================================================================
const HEX64_RE = /^[0-9a-f]{64}$/;
const SHA1_RE = /^[0-9a-f]{40}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const GATE_ID_RE = /^G-[A-Z0-9-]+$/;
const STEP_NAME_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ordinal = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const isObj = (o) => o !== null && typeof o === 'object' && !Array.isArray(o);
const isNat = (n) => Number.isInteger(n) && n >= 0;
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const sameKeys = (o, keys) => { const k = Object.keys(o); return k.length === keys.length && keys.every((x) => has(o, x)); };
const isIso = (s) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(s) && !Number.isNaN(Date.parse(s)) && new Date(s).toISOString() === s;

export const EVIDENCE_MAX_AGE_MS = 12 * 3600 * 1000;
export const EVIDENCE_CLOCK_SKEW_MS = 5 * 60 * 1000;
export const NA_STEP_REASON = 'no_baseline_declared_scope_excludes_claude';

// ---- manifests: H-set (human manifests) and E-set (evidence-bound subset) ----
// Paths are relative to <root>/.claude with forward slashes. Excluded from H: runs, approvals, ACTIVE_RUN, hook-debug.log, reports, worktrees.
const H_EXCLUDED_DIRS = ['orchestration/runs', 'orchestration/approvals', 'reports', 'worktrees'];
const H_EXCLUDED_FILES = ['orchestration/ACTIVE_RUN', 'orchestration/hook-debug.log'];
export function isHSetPath(rel) {
  if (H_EXCLUDED_FILES.includes(rel)) return false;
  return !H_EXCLUDED_DIRS.some((d) => rel === d || rel.startsWith(d + '/'));
}
// E-set: orchestration/*.mjs, orchestration/*.json, hooks/*.mjs, settings.json, agents/*.md (direct children only).
// settings.local.json is deliberately outside E.
export function isESetPath(rel) {
  if (!isHSetPath(rel)) return false;
  const p = rel.split('/');
  if (p.length === 1) return rel === 'settings.json';
  if (p.length !== 2) return false;
  return (p[0] === 'orchestration' && /\.(mjs|json)$/.test(p[1])) || (p[0] === 'hooks' && p[1].endsWith('.mjs')) || (p[0] === 'agents' && p[1].endsWith('.md'));
}
export function enumerateClaudeFiles(root = ROOT) {
  const out = [];
  const walk = (dirAbs, relDir) => {
    for (const d of fs.readdirSync(dirAbs, { withFileTypes: true })) {
      const rel = relDir ? `${relDir}/${d.name}` : d.name;
      if (d.isSymbolicLink()) throw new Error(`symbolic link or junction under .claude is not supported: ${rel}`);
      if (d.isDirectory()) { if (!H_EXCLUDED_DIRS.includes(rel)) walk(path.join(dirAbs, d.name), rel); }
      else if (d.isFile() && isHSetPath(rel)) out.push(rel);
    }
  };
  walk(path.join(root, '.claude'), '');
  return out.sort(ordinal);
}
function buildManifest(root, rels) {
  const lines = rels.map((r) => `${sha256(fs.readFileSync(path.join(root, '.claude', r)))}  ${r}`);
  const text = lines.length ? lines.join('\n') + '\n' : '';
  return { rels, lines, text, sha256: sha256(text) };
}
export const hSetManifest = (root = ROOT) => buildManifest(root, enumerateClaudeFiles(root));
export const eSetManifest = (root = ROOT) => buildManifest(root, enumerateClaudeFiles(root).filter(isESetPath));

// Strict parser for a manifest text: '<64 lowercase hex>  <relative path>' per line, LF only, no BOM, strictly ordinal-sorted, no duplicates.
export function parseManifest(text) {
  if (typeof text !== 'string' || text.length === 0) throw new Error('manifest is empty or not text');
  if (text.charCodeAt(0) === 0xfeff) throw new Error('manifest starts with a BOM');
  if (text.includes('\r')) throw new Error('manifest contains CR characters');
  if (!text.endsWith('\n')) throw new Error('manifest lacks a trailing LF');
  const map = new Map();
  let prev = null;
  for (const line of text.slice(0, -1).split('\n')) {
    const m = /^([0-9a-f]{64})  (.+)$/.exec(line);
    if (!m) throw new Error('manifest line is malformed');
    const rel = m[2];
    if (rel.includes('\\') || rel.startsWith('/') || rel.split('/').some((s) => s === '' || s === '.' || s === '..')) throw new Error('manifest path is not a clean relative path');
    if (prev !== null && ordinal(prev, rel) >= 0) throw new Error('manifest is not strictly sorted or has a duplicate path');
    map.set(rel, m[1]);
    prev = rel;
  }
  return map;
}

// Detective check for ignored governance files: diff the current H-set against the human baseline pinned in the Change Set.
// Passes only if the pin matches, every added or modified path is allowed and not forbidden, and nothing was deleted.
export function manifestScopeCheck(cs, root = ROOT) {
  const res = { ok: false, problems: [], added: [], modified: [], deleted: [], baseline_manifest_sha256: null, h_manifest_sha256: null };
  const fail = (m) => { res.problems.push(m); return res; };
  const bm = isObj(cs) ? cs.baseline_manifest : null;
  if (!isObj(bm) || typeof bm.path !== 'string' || !bm.path || typeof bm.sha256 !== 'string' || !HEX64_RE.test(bm.sha256)) return fail('baseline_manifest is not declared with a path and a lowercase sha256');
  let bytes;
  try { bytes = fs.readFileSync(bm.path); } catch { return fail('baseline manifest is unreadable'); }
  const pinned = sha256(bytes);
  if (pinned !== bm.sha256) return fail('baseline manifest sha256 does not match the pin in the Change Set');
  res.baseline_manifest_sha256 = pinned;
  let base;
  try { base = parseManifest(bytes.toString('utf8')); } catch (e) { return fail(`baseline manifest is malformed: ${e.message}`); }
  let cur;
  try { cur = hSetManifest(root); } catch (e) { return fail(`cannot enumerate the current .claude files: ${e.message}`); }
  res.h_manifest_sha256 = cur.sha256;
  const now = new Map(cur.rels.map((r, i) => [r, cur.lines[i].slice(0, 64)]));
  for (const [rel, hash] of now) { if (!base.has(rel)) res.added.push(rel); else if (base.get(rel) !== hash) res.modified.push(rel); }
  for (const rel of base.keys()) if (!now.has(rel)) res.deleted.push(rel);
  if (res.deleted.length) res.problems.push(`deleted paths: ${res.deleted.join(', ')}`);
  if (!Array.isArray(cs.allowed_paths)) res.problems.push('allowed_paths is not an array');
  else {
    const forbidden = Array.isArray(cs.forbidden_paths) ? cs.forbidden_paths : [];
    for (const rel of [...res.added, ...res.modified]) {
      const rp = `.claude/${rel}`;
      if (matchesAny(rp, forbidden)) res.problems.push(`forbidden path changed: ${rp}`);
      else if (!matchesAny(rp, cs.allowed_paths)) res.problems.push(`outside allowed_paths: ${rp}`);
    }
  }
  res.ok = res.problems.length === 0;
  return res;
}

// ---- applicability of the manifest-scope step (design v2.2 section 1; one helper for the runner and done()) ----
const CLAUDE_SENTINELS = ['.claude', '.claude/x', '.claude/orchestration/x.mjs', '.claude/hooks/tests/x/y.mjs'];
const stripTrailingDotsSpaces = (s) => s.replace(/[ .]+$/, ''); // Windows ignores trailing dots and spaces in a path component
function inspectAllowedEntry(raw) {
  if (typeof raw !== 'string') return { bad: true };
  const g = raw.replace(/\\/g, '/').replace(/^(\.\/)+/, ''); // normalize separators BEFORE any validation
  if (g.trim() === '' || /[\u0000-\u001f]/.test(g)) return { bad: true };
  if (g.startsWith('/')) return { bad: true }; // rooted and UNC (both separator forms)
  if (g.includes(':')) return { bad: true }; // drive letters and alternate data streams
  const segs = g.split('/');
  if (segs.some((s) => /^[ .]+$/.test(s) && s !== '.')) return { bad: true }; // traversal: "..", ".. ", "...", " "
  return { bad: false, g, first: segs[0] };
}
function entryMayIncludeClaude(raw) {
  const e = inspectAllowedEntry(raw);
  if (e.bad) return true; // malformed: fail closed
  if (stripTrailingDotsSpaces(e.first).toLowerCase() === '.claude') return true;
  if (/[*?]/.test(e.first)) return true; // a wildcard first segment can match ".claude"
  if (e.first.includes('~')) return true; // 8.3 short-name alias such as CLAUDE~1
  const re = globToRegExp(e.g);
  return CLAUDE_SENTINELS.some((s) => re.test(s)); // semantic backstop with the guards' own glob compiler
}
// Returns 'RUN' | 'FAIL' | 'NOT_APPLICABLE'.
export function manifestScopeApplicability(cs) {
  if (!isObj(cs) || !Array.isArray(cs.allowed_paths)) return 'FAIL'; // malformed containers fail closed, with or without a baseline
  if (isObj(cs.baseline_manifest)) return 'RUN';
  return cs.allowed_paths.some(entryMayIncludeClaude) ? 'FAIL' : 'NOT_APPLICABLE';
}

// ---- content-based tree digest (git-visible state; time independent) ----
const gitBuf = (root, args) => execFileSync('git', ['--no-optional-locks', '-C', root, ...args], { stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 256 * 1024 * 1024 });
function pathDigest(root, rel) {
  const abs = path.join(root, rel);
  let st;
  try { st = fs.lstatSync(abs); } catch { return 'DELETED'; }
  if (st.isSymbolicLink()) return 'LINK:' + sha256(fs.readlinkSync(abs));
  if (st.isDirectory()) return 'DIR';
  return sha256(fs.readFileSync(abs));
}
// SHA-256 over HEAD and, for every changed or untracked path (sorted ordinal), the path and the SHA-256 of its bytes (DELETED when absent).
// Throws when git state cannot be read: callers must treat that as UNKNOWN, never as a digest.
export function treeDigest(root = ROOT) {
  const head = gitBuf(root, ['rev-parse', 'HEAD']).toString('utf8').trim();
  if (!SHA1_RE.test(head)) throw new Error('cannot read git HEAD');
  const parts = gitBuf(root, ['status', '--porcelain=v1', '-z', '--untracked-files=all']).toString('utf8').split('\0');
  const paths = new Set();
  for (let i = 0; i < parts.length; i++) {
    const rec = parts[i];
    if (!rec) continue;
    paths.add(rec.slice(3));
    if (/[RC]/.test(rec.slice(0, 2))) { i++; if (parts[i]) paths.add(parts[i]); } // rename/copy: the next record is the source path
  }
  const sorted = [...paths].sort(ordinal);
  const body = sorted.map((p) => `${p}\0${pathDigest(root, p)}\n`).join('');
  return { sha256: sha256(`HEAD ${head}\n${body}`), head, files: sorted.length, paths: sorted };
}

// ---- bindings that every runner entry carries and done() recomputes ----
export const BINDING_KEYS = ['tree_hash', 'head', 'claude_e_sha256', 'runner_sha256', 'ledger_sha256', 'ledger_core_sha256', 'gates_json_sha256', 'interpreters_sha256', 'baseline_manifest_sha256', 'h_manifest_sha256'];
export function computeBindings(changeSet, root = ROOT, td = treeDigest(root)) {
  const orch = path.join(root, '.claude', 'orchestration');
  const fh = (f) => sha256(fs.readFileSync(path.join(orch, f)));
  const b = {
    tree_hash: td.sha256, head: td.head, claude_e_sha256: eSetManifest(root).sha256, runner_sha256: fh('run-gate.mjs'), ledger_sha256: fh('ledger.mjs'),
    ledger_core_sha256: fh('ledger-core.mjs'), gates_json_sha256: fh('gates.json'), interpreters_sha256: fh('trusted-interpreters.json'),
    baseline_manifest_sha256: null, h_manifest_sha256: null,
  };
  if (manifestScopeApplicability(changeSet) === 'RUN') {
    // An unreadable baseline or H-set leaves the hash null instead of throwing: the manifest-scope step then FAILs, the runner records that FAIL
    // (revoking any older PASS), and a RUN entry with a null baseline hash is never acceptable to done().
    try { b.baseline_manifest_sha256 = sha256(fs.readFileSync(changeSet.baseline_manifest.path)); } catch { /* stays null */ }
    try { b.h_manifest_sha256 = hSetManifest(root).sha256; } catch { /* stays null */ }
  }
  return b;
}

// Ordered step names of a gate's runner block (what done() requires an entry's steps to equal), or null when the gate has no usable runner block.
export function runnerStepNames(gateDef) {
  const steps = isObj(gateDef) && isObj(gateDef.runner) ? gateDef.runner.steps : null;
  if (!Array.isArray(steps) || steps.length === 0 || !steps.every((s) => isObj(s) && typeof s.name === 'string')) return null;
  return steps.map((s) => s.name);
}

export function conditionalHarnessApplies(changedFiles, gateDef) {
  const c = isObj(gateDef) && isObj(gateDef.runner) ? gateDef.runner.conditional : null;
  if (!isObj(c) || !Array.isArray(c.when_diff_matches)) return false;
  return (changedFiles || []).some((f) => matchesAny(f, c.when_diff_matches));
}

// ---- strict schema-1 evidence validator ----
const EVIDENCE_KEYS = ['at', 'source', 'schema', 'gate', 'covers', 'kind', 'result', 'exit_status', 'counts', 'run_id', 'ledger_run', 'change_set_sha256', 'steps', 'interpreter',
  'tree_hash', 'head', 'claude_e_sha256', 'runner_sha256', 'ledger_sha256', 'ledger_core_sha256', 'gates_json_sha256', 'interpreters_sha256', 'baseline_manifest_sha256',
  'h_manifest_sha256', 'started_at', 'finished_at', 'junit_sha256', 'required_cells'];
const COUNT_KEYS = ['tests', 'failures', 'errors', 'skipped'];
const isNaStep = (s) => isObj(s) && has(s, 'applicable');
function stepShapeOk(s) {
  if (!isObj(s)) return false;
  if (isNaStep(s)) return sameKeys(s, ['name', 'applicable', 'reason', 'exit_status']) && s.name === 'manifest-scope' && s.applicable === false && s.reason === NA_STEP_REASON && s.exit_status === null;
  return sameKeys(s, ['name', 'argv_sha256', 'exit_status']) && typeof s.name === 'string' && STEP_NAME_RE.test(s.name) && HEX64_RE.test(s.argv_sha256) && (s.exit_status === null || Number.isInteger(s.exit_status));
}
// Returns { ok, errors }. Structural and internal-consistency checks only; acceptance equalities live in evidenceAcceptanceProblems.
export function validateEvidenceV1(e) {
  if (!isObj(e)) return { ok: false, errors: ['entry is not an object'] };
  const errors = [];
  const bad = (m) => errors.push(m);
  const missing = EVIDENCE_KEYS.filter((k) => !has(e, k));
  const extra = Object.keys(e).filter((k) => !EVIDENCE_KEYS.includes(k));
  if (missing.length) bad(`missing keys: ${missing.join(', ')}`);
  if (extra.length) bad(`unknown keys: ${extra.join(', ')}`);
  if (missing.length) return { ok: false, errors };
  if (!isIso(e.at)) bad('at');
  if (e.source !== 'runner') bad('source');
  if (e.schema !== 1) bad('schema');
  if (typeof e.gate !== 'string' || !GATE_ID_RE.test(e.gate)) bad('gate');
  if (!(Array.isArray(e.covers) && e.covers.length === 1 && e.covers[0] === e.gate)) bad('covers');
  if (!['pytest', 'script'].includes(e.kind)) bad('kind');
  if (!['PASS', 'FAIL', 'UNKNOWN'].includes(e.result)) bad('result');
  if (!(e.exit_status === null || Number.isInteger(e.exit_status))) bad('exit_status');
  if (e.kind === 'script') { if (e.counts !== null) bad('counts must be null for script'); }
  else if (!(e.counts === null || (isObj(e.counts) && sameKeys(e.counts, COUNT_KEYS) && COUNT_KEYS.every((k) => isNat(e.counts[k]))))) bad('counts');
  if (typeof e.run_id !== 'string' || !UUID_RE.test(e.run_id)) bad('run_id');
  if (typeof e.ledger_run !== 'string' || !RUN_ID_RE.test(e.ledger_run)) bad('ledger_run');
  for (const k of ['change_set_sha256', 'tree_hash', 'claude_e_sha256', 'runner_sha256', 'ledger_sha256', 'ledger_core_sha256', 'gates_json_sha256', 'interpreters_sha256']) if (typeof e[k] !== 'string' || !HEX64_RE.test(e[k])) bad(k);
  for (const k of ['baseline_manifest_sha256', 'h_manifest_sha256']) if (!(e[k] === null || (typeof e[k] === 'string' && HEX64_RE.test(e[k])))) bad(k);
  if (typeof e.head !== 'string' || !SHA1_RE.test(e.head)) bad('head');
  if (!(Array.isArray(e.steps) && e.steps.length > 0 && e.steps.every(stepShapeOk))) bad('steps');
  if (e.kind === 'script') { if (e.interpreter !== null) bad('interpreter must be null for script'); if (e.junit_sha256 !== null) bad('junit_sha256 must be null for script'); }
  else {
    if (!(e.interpreter === null || (isObj(e.interpreter) && sameKeys(e.interpreter, ['path', 'sha256']) && typeof e.interpreter.path === 'string' && e.interpreter.path && HEX64_RE.test(e.interpreter.sha256)))) bad('interpreter');
    if (!(e.junit_sha256 === null || (typeof e.junit_sha256 === 'string' && HEX64_RE.test(e.junit_sha256)))) bad('junit_sha256');
  }
  if (!isIso(e.started_at)) bad('started_at');
  if (!isIso(e.finished_at)) bad('finished_at');
  if (!(e.required_cells === null || (isObj(e.required_cells) && sameKeys(e.required_cells, ['expected', 'passed']) && isNat(e.required_cells.expected) && isNat(e.required_cells.passed)))) bad('required_cells');
  if (e.result === 'PASS') { // a PASS must be internally consistent
    if (e.exit_status !== 0) bad('PASS requires exit_status 0');
    if (Array.isArray(e.steps) && e.steps.some((s) => isObj(s) && !isNaStep(s) && s.exit_status !== 0)) bad('PASS requires every step to exit 0');
    if (e.kind === 'pytest' && (e.counts === null || e.interpreter === null || e.junit_sha256 === null)) bad('pytest PASS requires counts, interpreter and junit hash');
  }
  return { ok: errors.length === 0, errors };
}

// ---- duplicate-keyed records: JSON.parse silently keeps the LAST duplicate, which would let a hand-edited "FAIL","PASS" pair read as PASS ----
// Walks the raw JSON text and returns the paths (e.g. "evidence[3].result") of every key that repeats inside one object. Throws on malformed JSON.
export function jsonDuplicateKeyPaths(text) {
  const dups = [];
  let i = 0;
  const n = text.length;
  const ws = () => { while (i < n && ' \t\r\n'.includes(text[i])) i++; };
  const bad = (m) => { throw new Error(`malformed JSON: ${m} at ${i}`); };
  const str = () => {
    const start = i;
    i++;
    while (i < n && text[i] !== '"') { if (text[i] === '\\') i++; i++; }
    if (i >= n) bad('unterminated string');
    i++;
    return JSON.parse(text.slice(start, i)); // decodes escapes, so "a" and "a" collide as they should
  };
  const LITERAL = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/y;
  const val = (p) => {
    ws();
    const c = text[i];
    if (c === '{') {
      i++;
      const seen = new Set();
      ws();
      if (text[i] === '}') { i++; return; }
      for (;;) {
        ws();
        if (text[i] !== '"') bad('expected a key');
        const k = str();
        const kp = p ? `${p}.${k}` : k;
        if (seen.has(k)) dups.push(kp);
        seen.add(k);
        ws();
        if (text[i] !== ':') bad('expected ":"');
        i++;
        val(kp);
        ws();
        if (text[i] === ',') { i++; continue; }
        if (text[i] === '}') { i++; return; }
        bad('expected "," or "}"');
      }
    } else if (c === '[') {
      i++;
      ws();
      if (text[i] === ']') { i++; return; }
      for (let idx = 0; ; idx++) {
        val(`${p}[${idx}]`);
        ws();
        if (text[i] === ',') { i++; continue; }
        if (text[i] === ']') { i++; return; }
        bad('expected "," or "]"');
      }
    } else if (c === '"') str();
    else {
      LITERAL.lastIndex = i;
      const m = LITERAL.exec(text);
      if (!m) bad('unexpected token');
      i += m[0].length;
    }
  };
  val('');
  ws();
  if (i !== n) bad('trailing characters');
  return dups;
}
// Indexes of ledger evidence records whose raw text has a duplicate key anywhere inside the record. done() treats these as malformed.
export function taintedEvidenceIndexes(rawLedgerText) {
  const out = new Set();
  for (const d of jsonDuplicateKeyPaths(rawLedgerText)) { const m = /^evidence\[(\d+)\]/.exec(d); if (m) out.add(Number(m[1])); }
  return out;
}

// done() accepts a gate only through the NEWEST runner entry for it; a newer FAIL or UNKNOWN (or malformed) entry revokes an older PASS.
// Ties on `at` go to the later record in the array.
export function newestRunnerIndex(evidence, gate) {
  let best = -1;
  let bestT = -Infinity;
  (Array.isArray(evidence) ? evidence : []).forEach((e, idx) => {
    if (!isObj(e) || e.source !== 'runner') return;
    if (e.gate !== gate && !(Array.isArray(e.covers) && e.covers.includes(gate))) return;
    const t = Date.parse(e.at);
    const tt = Number.isNaN(t) ? -Infinity : t;
    if (best === -1 || tt >= bestT) { best = idx; bestT = tt; }
  });
  return best;
}
export function newestRunnerEntry(evidence, gate) {
  const i = newestRunnerIndex(evidence, gate);
  return i === -1 ? null : evidence[i];
}

// All acceptance equalities of design v2 section 2 and v2.1 section 2. Returns [] when the entry may satisfy the gate.
// ctx: { gate, ledgerRun, changeSetSha256, changeSet, stepNames, taskStartedAtMs, nowMs, current (computeBindings result), requireCells?, tainted? }
// ctx.tainted: the raw ledger text of this record had a duplicate key (see taintedEvidenceIndexes).
export function evidenceAcceptanceProblems(e, ctx) {
  const v = validateEvidenceV1(e);
  if (!v.ok) return [`malformed runner evidence: ${v.errors.join('; ')}`];
  const p = [];
  if (ctx.tainted) p.push('the raw ledger record contains a duplicate key (a hand-edited record cannot be trusted)');
  if (e.gate !== ctx.gate) p.push(`entry is for ${e.gate}, not ${ctx.gate}`);
  if (e.result !== 'PASS') p.push(`result is ${e.result}`);
  if (e.ledger_run !== ctx.ledgerRun) p.push('evidence belongs to a different run (ledger_run mismatch)');
  if (e.change_set_sha256 !== ctx.changeSetSha256) p.push('evidence was produced under a different Change Set (change_set_sha256 mismatch)');
  if (e.kind === 'pytest') {
    const c = e.counts;
    if (c === null || !(c.tests > 0) || c.failures !== 0 || c.errors !== 0) p.push('pytest counts are not a passing run (tests > 0, failures 0, errors 0 required)');
  }
  const names = e.steps.map((s) => s.name);
  if (!Array.isArray(ctx.stepNames) || JSON.stringify(names) !== JSON.stringify(ctx.stepNames)) p.push(`steps ${JSON.stringify(names)} do not match the gate definition ${JSON.stringify(ctx.stepNames)}`);
  const app = manifestScopeApplicability(ctx.changeSet);
  const ms = e.steps.find((s) => s.name === 'manifest-scope');
  const gateHasMs = Array.isArray(ctx.stepNames) && ctx.stepNames.includes('manifest-scope');
  if (e.steps.some(isNaStep) && !gateHasMs) p.push('not-applicable step recorded for a gate without a manifest-scope step');
  if (gateHasMs && ms) {
    if (app === 'FAIL') p.push('the Change Set requires a declared baseline_manifest (manifest-scope cannot be satisfied)');
    else if (app === 'RUN' && isNaStep(ms)) p.push('manifest-scope was recorded not-applicable but the Change Set declares a baseline');
    else if (app === 'NOT_APPLICABLE' && !isNaStep(ms)) p.push('manifest-scope was run but the Change Set recomputes not-applicable');
  }
  if (!isObj(ctx.current)) p.push('current bindings are unavailable');
  else {
    for (const k of BINDING_KEYS) if (e[k] !== ctx.current[k]) p.push(`stale: ${k} changed since the gate ran`);
  }
  if (app === 'RUN' && (e.baseline_manifest_sha256 === null || e.h_manifest_sha256 === null)) p.push('baseline hashes are not recorded although the Change Set declares a baseline');
  if (app !== 'RUN' && (e.baseline_manifest_sha256 !== null || e.h_manifest_sha256 !== null)) p.push('baseline hashes are recorded although the Change Set declares no baseline');
  const started = Date.parse(e.started_at); const finished = Date.parse(e.finished_at); const at = Date.parse(e.at);
  if (!Number.isFinite(ctx.taskStartedAtMs) || !Number.isFinite(ctx.nowMs)) p.push('task start or current time is unavailable');
  else {
    if (finished < ctx.taskStartedAtMs) p.push('evidence finished before the task started');
    if (ctx.nowMs - finished > EVIDENCE_MAX_AGE_MS) p.push('evidence is older than 12 hours');
    if (finished > ctx.nowMs + EVIDENCE_CLOCK_SKEW_MS) p.push('evidence finished in the future');
  }
  if (started > finished) p.push('started_at is after finished_at');
  if (at < finished) p.push('recorded before the run finished');
  if (e.required_cells !== null && !(e.required_cells.expected > 0 && e.required_cells.passed === e.required_cells.expected)) p.push('required harness cells are not all satisfied');
  if (ctx.requireCells && e.required_cells === null) p.push('the harness applies to this diff but no required_cells were recorded');
  return p;
}
