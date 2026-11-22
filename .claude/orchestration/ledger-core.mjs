// InboundCheck autonomous team: shared ledger/approval/glob helpers.
// Used by hooks (guard-*.mjs, record-gate.mjs, ...) and by ledger.mjs. Node >= 18, no dependencies.
// Root and orchestration dir are derived from THIS file's location, never from env or tool input.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { captureIdentity } from './evidence-policy.mjs';
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
    const l = loadLedger(id);
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
    (l.evidence ||= []).push({ at: nowIso(), ...evd, ...(evd.source === 'ledger' ? { exit_code: evd.result === 'PASS' ? 0 : 1 } : {}), release: getActive()?.changeSet?.release_id || null, identity: captureIdentity(ROOT) });
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
