#!/usr/bin/env node
// InboundCheck autonomous team: durable task ledger CLI.
// Usage: node .claude/orchestration/ledger.mjs <command> [--flag value ...]
// `approve` is the ONLY approval path and is meant to be typed by the human (prefix with `!` in Claude Code).
// Hooks (guard-bash.mjs / guard-write.mjs) deny agent attempts to run `approve` or edit ledger.json / approvals/.
import fs from 'node:fs';
import { captureIdentity, evidenceMatches, releaseComplete } from './evidence-policy.mjs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import {
  ROOT, RUNS, APPROVALS, ACTIVE, RUN_ID_RE, sha256, nowIso, readJson, writeJsonAtomic, withLock,
  matchesAny, runDir, ledgerPath, changeSetPath, approvalPath, getActive, readActiveId, loadLedger, mutateLedger,
  appendEvent, appendEvidence, summarize, loadBoundaries, loadGates, TASK_STATUSES,
} from './ledger-core.mjs';

const [cmd, ...rest] = process.argv.slice(2);
const flags = {};
const positional = [];
for (let i = 0; i < rest.length; i++) {
  if (rest[i].startsWith('--')) { flags[rest[i].slice(2)] = (rest[i + 1] && !rest[i + 1].startsWith('--')) ? rest[++i] : 'true'; }
  else positional.push(rest[i]);
}
// die() throws so withLock() can release its lock; the top-level catch prints and exits 1.
const die = (m) => { throw new Error(m); };
const ok = (m) => { console.log(m); process.exit(0); };
const csv = (s) => (s ? String(s).split(',').map((x) => x.trim()).filter(Boolean) : []);

function activeOrDie({ needApproved = true } = {}) {
  const a = getActive();
  if (!a) die('no active run (ACTIVE_RUN is empty). Use `init` first.');
  if (needApproved && !a.approved) die(`run ${a.id} is not approved: ${a.reason}`);
  return a;
}

function git(args) {
  return execFileSync('git', ['-C', ROOT, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}
// Working-tree changes versus HEAD (tracked modifications + untracked, ignored files excluded). Read-only git only.
function changedFiles() {
  const out = git(['status', '--porcelain=v1', '--untracked-files=all']);
  const files = [];
  for (const line of out.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let p = line.slice(3);
    if (p.includes(' -> ')) p = p.split(' -> ')[1];
    files.push(p.replace(/^"|"$/g, '').replace(/\\/g, '/'));
  }
  return files;
}
function latestMtime(files) {
  let m = 0;
  for (const f of files) { try { m = Math.max(m, fs.statSync(path.join(ROOT, f)).mtimeMs); } catch { /* deleted */ } }
  return m;
}
function computeRisk(files, declared = 'LOW') {
  const b = loadBoundaries();
  const order = { LOW: 0, MEDIUM: 1, HIGH: 2 };
  let risk = declared;
  if (files.some((f) => matchesAny(f, b.security_boundaries))) risk = 'HIGH';
  return order[risk] >= order[declared] ? risk : declared;
}

function scopeCheck(cs) {
  const files = changedFiles();
  const bad = [];
  for (const f of files) {
    if (matchesAny(f, cs.forbidden_paths || [])) bad.push({ file: f, why: 'forbidden_paths' });
    else if (!matchesAny(f, cs.allowed_paths || [])) bad.push({ file: f, why: 'outside allowed_paths' });
  }
  return { files, bad };
}

const commands = {
  'release-check'() {
    const a = activeOrDie();
    const release = flags.release;
    if (!release || a.changeSet.release_id !== release) die('release identity requires explicit approved Change Set binding');
    const required = [...new Set(['G-BE-FULL', 'G-FE-BUILD', 'G-SCOPE', 'G-SCAN', 'G-DOCKER', ...(a.changeSet.release_gates || [])])];
    const records = (loadLedger(a.id).evidence || []).filter(e => ['hook', 'ledger'].includes(e.source))
      .flatMap(e => (e.covers || []).map(gate => ({ ...e, gate, command: e.command_head || e.command_sha || e.gate })));
    if (!releaseComplete(required, records, captureIdentity(ROOT), release)) die('mandatory release gates missing, stale, failed or from another release attempt');
    ok('release gate evidence verified; this does not grant merge/deployment permission or replace independent reviews/current CI');
  },
  init() {
    const id = flags['run-id'];
    if (!id || !RUN_ID_RE.test(id)) die('--run-id required, 3-64 chars [A-Za-z0-9._-]');
    if (!flags.objective) die('--objective required');
    const cur = readActiveId();
    if (cur && cur !== id) {
      let open = true;
      try { open = loadLedger(cur).tasks.some((t) => t.status !== 'DONE') || loadLedger(cur).status !== 'COMPLETE'; } catch { /* corrupt: treat as open */ }
      if (open) die(`run ${cur} is still open. Finish it (close) or ask the user; never overwrite an incomplete run.`);
    }
    if (fs.existsSync(runDir(id))) die(`run ${id} already exists`);
    let head = '?';
    try { head = git(['rev-parse', '--short', 'HEAD']).trim(); } catch { /* no git */ }
    fs.mkdirSync(path.join(runDir(id), 'notes'), { recursive: true });
    writeJsonAtomic(ledgerPath(id), { run_id: id, objective: flags.objective, status: 'PLANNING', created_at: nowIso(), base_head: head, tasks: [], evidence: [], events: [] });
    writeJsonAtomic(changeSetPath(id), {
      run_id: id, title: flags.objective, status: 'DRAFT',
      _how: 'Fill allowed_paths and boundary_ack, then ask the user to run: node .claude/orchestration/ledger.mjs approve ' + id,
      allowed_paths: [], forbidden_paths: ['.env', '.env.*', '**/*.pem', '**/*.key', 'supabase/migrations/**/apply*'],
      boundary_ack: [], allow_dependency_changes: false, allow_migrations: false, planned_tasks: [],
    });
    fs.writeFileSync(ACTIVE, id + '\n');
    ok(`run ${id} created (DRAFT). All app-code edits stay blocked until the user approves the change set.`);
  },

  approve() {
    const id = positional[0] || flags['run-id'];
    if (!id || !RUN_ID_RE.test(id)) die('usage: approve <run-id>');
    let raw;
    try { raw = fs.readFileSync(changeSetPath(id), 'utf8'); } catch { die('change-set.json not found'); }
    const cs = JSON.parse(raw);
    if (!Array.isArray(cs.allowed_paths) || cs.allowed_paths.length === 0) die('allowed_paths is empty; nothing to approve');
    fs.mkdirSync(APPROVALS, { recursive: true });
    writeJsonAtomic(approvalPath(id), { run_id: id, change_set_sha256: sha256(raw), approved_at: nowIso(), approved_by: 'human via ledger.mjs approve' });
    console.log(`APPROVED run ${id}\n  allowed_paths: ${cs.allowed_paths.join(', ')}\n  boundary_ack: ${(cs.boundary_ack || []).join(', ') || '(none)'}\n  dependency changes: ${cs.allow_dependency_changes ? 'ALLOWED' : 'no'}\n  migrations authored: ${cs.allow_migrations ? 'ALLOWED' : 'no'}\n  sha256: ${sha256(raw).slice(0, 16)}...`);
    try { appendEvent(id, { type: 'approved' }); } catch { /* ledger may not exist */ }
  },

  status() {
    const a = getActive();
    if (!a) ok('no active run');
    console.log(summarize(a.id));
  },

  recover() { commands.status(); },

  'add-task'() {
    const a = activeOrDie();
    const { id, title, owner } = flags;
    if (!id || !title || !owner) die('--id --title --owner required (also --files a,b --risk LOW|MEDIUM|HIGH --depends T1,T2 --gates G-X,G-Y [--read-only])');
    const files = csv(flags.files);
    const cs = a.changeSet;
    const stray = files.filter((f) => !matchesAny(f, cs.allowed_paths || []) || matchesAny(f, cs.forbidden_paths || []));
    if (stray.length) die(`files outside the approved change set: ${stray.join(', ')}`);
    const b = loadBoundaries();
    const boundary = files.filter((f) => matchesAny(f, b.security_boundaries));
    const unacked = boundary.filter((f) => !matchesAny(f, cs.boundary_ack || []));
    if (unacked.length) die(`security-boundary files not acknowledged in change-set boundary_ack (user must approve): ${unacked.join(', ')}`);
    const dep = files.filter((f) => matchesAny(f, b.dependency_and_deploy_files));
    if (dep.length && !cs.allow_dependency_changes) die(`dependency/deploy files require allow_dependency_changes in the approved change set: ${dep.join(', ')}`);
    const declared = (flags.risk || 'LOW').toUpperCase();
    if (!['LOW', 'MEDIUM', 'HIGH'].includes(declared)) die('--risk must be LOW|MEDIUM|HIGH');
    const risk = computeRisk(files, declared);
    mutateLedger(a.id, (l) => {
      if (l.tasks.some((t) => t.id === id)) die(`task ${id} exists`);
      for (const d of csv(flags.depends)) if (!l.tasks.some((t) => t.id === d)) die(`unknown dependency ${d}`);
      l.tasks.push({ id, title, owner, risk, files, depends_on: csv(flags.depends), gates: csv(flags.gates), read_only: flags['read-only'] === 'true', status: 'PENDING', correction_cycles: 0, reviews: [], created_at: nowIso() });
      l.status = 'RUNNING';
    });
    ok(`task ${id} added (risk ${risk}${risk !== declared ? ', raised from ' + declared + ' because a file is a security boundary' : ''})`);
  },

  start() {
    const a = activeOrDie();
    const tid = positional[0];
    mutateLedger(a.id, (l) => {
      const t = l.tasks.find((x) => x.id === tid) || die(`unknown task ${tid}`);
      if (!['PENDING', 'NEEDS_FIX'].includes(t.status)) die(`task ${tid} is ${t.status}; only PENDING or NEEDS_FIX can start`);
      const done = new Set(l.tasks.filter((x) => x.status === 'DONE').map((x) => x.id));
      const wait = (t.depends_on || []).filter((d) => !done.has(d));
      if (wait.length) die(`dependencies not DONE: ${wait.join(', ')}`);
      t.status = 'IN_PROGRESS'; t.started_at = nowIso();
    });
    ok(`task ${tid} IN_PROGRESS`);
  },

  submit() {
    const a = activeOrDie();
    const tid = positional[0];
    mutateLedger(a.id, (l) => {
      const t = l.tasks.find((x) => x.id === tid) || die(`unknown task ${tid}`);
      if (t.status !== 'IN_PROGRESS') die(`task ${tid} is ${t.status}`);
      t.status = 'IN_REVIEW'; t.submitted_at = nowIso();
    });
    ok(`task ${tid} IN_REVIEW`);
  },

  review() {
    const a = activeOrDie();
    const tid = positional[0];
    const { agent, verdict, ref } = flags;
    if (!agent || !['PASS', 'FAIL'].includes(String(verdict).toUpperCase())) die('--agent and --verdict PASS|FAIL required');
    mutateLedger(a.id, (l) => {
      const t = l.tasks.find((x) => x.id === tid) || die(`unknown task ${tid}`);
      const ran = (l.events || []).some((e) => e.type === 'agent_stop' && e.agent_type === agent && new Date(e.at) >= new Date(t.started_at));
      if (!ran) die(`no hook-logged invocation of agent "${agent}" since the task started; cannot record a review that was not actually run`);
      t.reviews.push({ agent, verdict: String(verdict).toUpperCase(), ref: ref || '', at: nowIso() });
    });
    ok(`review recorded: ${agent} ${verdict} for ${tid}`);
  },

  evidence() {
    const a = activeOrDie();
    appendEvidence(a.id, { source: 'orchestrator', gate: flags.gate || null, result: String(flags.result || 'UNKNOWN').toUpperCase(), ref: flags.ref || '' });
    ok('manual evidence recorded (source=orchestrator; it never satisfies a task completion check)');
  },

  fail() {
    const a = activeOrDie();
    const tid = positional[0];
    let msg = '';
    mutateLedger(a.id, (l) => {
      const t = l.tasks.find((x) => x.id === tid) || die(`unknown task ${tid}`);
      t.correction_cycles = (t.correction_cycles || 0) + 1;
      t.last_failure = flags.reason || '';
      if (t.correction_cycles > 2) { t.status = 'BLOCKED'; t.blocked_reason = `exceeded 2 correction cycles: ${flags.reason || ''}`; msg = `task ${tid} BLOCKED (3rd failure). Working changes are preserved. Report to the user; do not retry.`; }
      else { t.status = 'NEEDS_FIX'; msg = `task ${tid} NEEDS_FIX (correction cycle ${t.correction_cycles}/2)`; }
    });
    ok(msg);
  },

  block() {
    const a = activeOrDie();
    const tid = positional[0];
    mutateLedger(a.id, (l) => { const t = l.tasks.find((x) => x.id === tid) || die(`unknown task ${tid}`); t.status = 'BLOCKED'; t.blocked_reason = flags.reason || 'unspecified'; });
    ok(`task ${tid} BLOCKED: ${flags.reason || ''}. Stop and report to the user (ambiguous scope, security, architecture or authorization).`);
  },

  'scope-check'() {
    const a = activeOrDie();
    const before = captureIdentity(ROOT);
    const { files, bad } = scopeCheck(a.changeSet);
    appendEvidence(a.id, { before, source: 'ledger', gate: 'G-SCOPE', covers: ['G-SCOPE'], result: bad.length ? 'FAIL' : 'PASS', files: files.length });
    if (bad.length) { console.error('SCOPE VIOLATION:\n' + bad.map((b) => `  ${b.file} (${b.why})`).join('\n')); process.exit(1); }
    ok(`scope ok: ${files.length} changed file(s), all within allowed_paths`);
  },

  done() {
    const a = activeOrDie();
    const tid = positional[0];
    const gates = loadGates();
    let problems = [];
    mutateLedger(a.id, (l) => {
      const t = l.tasks.find((x) => x.id === tid) || die(`unknown task ${tid}`);
      if (!['IN_PROGRESS', 'IN_REVIEW'].includes(t.status)) { problems.push(`status is ${t.status}`); return; }
      let files; try { files = changedFiles(); } catch (e) { problems.push('cannot read git state: ' + e.message); return; }
      const sc = scopeCheck(a.changeSet);
      if (sc.bad.length) problems.push(`out-of-scope changes: ${sc.bad.map((b) => b.file).join(', ')}`);
      if (t.read_only && files.length) problems.push(`read-only task but the working tree has changes: ${files.join(', ')}`);
      const risk = computeRisk(t.files || [], t.risk);
      const req = gates.risk_requirements[risk];
      const needGates = [...new Set([...(req.gates || []), ...(t.gates || [])])];
      const latest = Math.max(latestMtime(files), new Date(t.started_at || 0).getTime());
      for (const g of needGates) {
        const def = gates.gates.find((x) => x.id === g);
        if (!def) { problems.push(`unknown gate ${g}`); continue; }
        if (def.autonomy !== 'autonomous') { problems.push(`gate ${g} is ${def.autonomy}/${def.status}; it cannot be satisfied autonomously (user approval required)`); continue; }
        const currentIdentity = captureIdentity(ROOT);
        const last = (l.evidence || []).filter(e => ['hook', 'ledger'].includes(e.source) && (e.covers || []).includes(g)).at(-1);
        const hit = last && new Date(last.at).getTime() >= latest && evidenceMatches({ ...last, command: last.command_head || last.command_sha || last.gate }, currentIdentity);
        if (!hit) problems.push(`gate ${g}: no hook-recorded PASS after the last edit`);
      }
      for (const r of req.reviews || []) {
        const rv = (t.reviews || []).find((x) => x.agent === r && x.verdict === 'PASS' && new Date(x.at).getTime() >= latest);
        const ran = (l.events || []).some((e) => e.type === 'agent_stop' && e.agent_type === r && new Date(e.at).getTime() >= latest);
        if (!rv || !ran) problems.push(`review by ${r}: no PASS recorded after the last edit (or the agent was not actually invoked after it)`);
      }
      if (!problems.length) { t.status = 'DONE'; t.done_at = nowIso(); t.final_risk = risk; }
    });
    if (problems.length) { console.error(`task ${tid} NOT done:\n  - ${problems.join('\n  - ')}`); process.exit(1); }
    ok(`task ${tid} DONE (verified from hook-recorded evidence)`);
  },

  close() {
    const a = activeOrDie({ needApproved: false });
    const l = loadLedger(a.id);
    const open = l.tasks.filter((t) => t.status !== 'DONE');
    if (open.length && flags.force !== 'true') die(`open tasks: ${open.map((t) => t.id + ':' + t.status).join(', ')}`);
    mutateLedger(a.id, (x) => { x.status = open.length ? 'ABANDONED' : 'COMPLETE'; x.closed_at = nowIso(); });
    fs.writeFileSync(ACTIVE, '');
    ok(`run ${a.id} closed; ACTIVE_RUN cleared, default (ask-first) guards apply again`);
  },
};

if (!cmd || !commands[cmd]) {
  console.error('commands: ' + Object.keys(commands).join(', '));
  process.exit(cmd ? 1 : 0);
}
try { commands[cmd](); } catch (e) { console.error(`ledger: ${e.message}`); process.exit(1); }
