// Write-scope policy shared by guard-write.mjs (Edit/Write tools) and guard-bash.mjs (shell write targets).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ROOT, toPosix, matchesAny, getActive, loadBoundaries, loadLedger } from '../orchestration/ledger-core.mjs';

// Resolve through symlinks/junctions using the nearest existing ancestor, so `..` or link tricks cannot escape the checks.
export function resolveReal(abs) {
  let p = path.resolve(abs);
  const tail = [];
  for (;;) {
    try { const real = fs.realpathSync.native(p); return path.join(real, ...tail.reverse()); }
    catch { const parent = path.dirname(p); if (parent === p) return path.resolve(abs); tail.push(path.basename(p)); p = parent; }
  }
}
export function relInRepo(abs) {
  const r = path.relative(resolveReal(ROOT), resolveReal(abs));
  if (r === '') return '';
  if (r.startsWith('..') || path.isAbsolute(r)) return null;
  return toPosix(r);
}

const SECRET_FILE = /(^|\/)\.env(\.(?!example$|sample$|template$)[^/]*)?$/i;
const KEY_FILE = /\.(pem|key|pfx|p12)$/i;
const WRITABLE_ANY = ['.claude/reports/**', '.claude/orchestration/runs/*/notes/**'];
const WRITABLE_MAIN = ['.claude/orchestration/runs/*/change-set.json', '.claude/orchestration/ACTIVE_RUN'];

// ctx: { agent: string, sub: boolean }
// returns { decision: 'allow'|'ask'|'deny', reason }
export function decideWrite(rel, ctx) {
  const b = loadBoundaries();
  const deny = (reason) => ({ decision: 'deny', reason });
  if (SECRET_FILE.test(rel) || KEY_FILE.test(rel)) return deny(`'${rel}' is a secret/credential file; agents never write it`);
  if (rel === '.git' || rel.startsWith('.git/')) return deny('writing inside .git is not permitted');
  if (matchesAny(rel, b.never_writable_by_tools)) return deny(`'${rel}' is written only by ledger.mjs (ledger) or by the human (approvals)`);
  if (matchesAny(rel, WRITABLE_ANY)) return { decision: 'allow', reason: 'orchestration scratch/report path' };
  if (!ctx.sub && matchesAny(rel, WRITABLE_MAIN)) return { decision: 'allow', reason: 'orchestrator-owned planning file' };
  if (matchesAny(rel, b.governance_paths) || rel.startsWith('.claude/')) {
    return ctx.sub
      ? deny(`'${rel}' is governance configuration; subagents may not modify it`)
      : { decision: 'ask', reason: `'${rel}' is governance configuration (hooks/agents/skills/settings); the user must confirm` };
  }
  if ((b.read_only_roles || []).includes(ctx.agent)) return deny(`role '${ctx.agent}' is read-only; report findings instead of editing '${rel}'`);

  // application area
  const a = getActive();
  if (!a) {
    return ctx.sub
      ? deny(`no active approved Change Set; subagent '${ctx.agent}' may not edit application file '${rel}'`)
      : { decision: 'ask', reason: `no active autonomous run; confirm this manual edit of '${rel}'` };
  }
  if (!a.approved) return deny(`run ${a.id} is not approved (${a.reason}); application edits are blocked`);
  const cs = a.changeSet;
  if (matchesAny(rel, cs.forbidden_paths || [])) return deny(`'${rel}' is in the Change Set forbidden_paths`);
  if (!matchesAny(rel, cs.allowed_paths || [])) return deny(`'${rel}' is outside the approved Change Set allowed_paths (scope violation)`);
  if (matchesAny(rel, b.security_boundaries) && !matchesAny(rel, cs.boundary_ack || [])) return deny(`'${rel}' is a security boundary; the Change Set must list it in boundary_ack (user-approved)`);
  if (matchesAny(rel, b.dependency_and_deploy_files) && !cs.allow_dependency_changes) return deny(`'${rel}' is a dependency/deploy file; allow_dependency_changes is not approved`);
  if (rel.startsWith('supabase/migrations/') && !cs.allow_migrations) return deny('authoring migrations requires allow_migrations in the approved Change Set (applying them is never autonomous)');
  if (ctx.sub) {
    let owns = false;
    try {
      const l = loadLedger(a.id);
      owns = (l.tasks || []).some((t) => ['IN_PROGRESS', 'NEEDS_FIX'].includes(t.status) && t.owner === ctx.agent && matchesAny(rel, t.files || []));
    } catch { /* fail closed */ }
    if (!owns) return deny(`'${rel}' is not owned by '${ctx.agent}' in any IN_PROGRESS task (file-ownership rule)`);
  }
  return { decision: 'allow', reason: 'within approved Change Set' };
}

// Decide for an absolute path (handles outside-repo, scratchpad, global ~/.claude).
export function decideWriteAbs(abs, ctx, scratchpad) {
  const real = resolveReal(abs);
  const home = resolveReal(path.join(os.homedir(), '.claude'));
  const rel = relInRepo(abs);
  if (rel !== null) return decideWrite(rel, ctx);
  if (scratchpad) {
    const sp = path.relative(resolveReal(scratchpad), real);
    if (!sp.startsWith('..') && !path.isAbsolute(sp)) return { decision: 'allow', reason: 'session scratchpad' };
  }
  const h = path.relative(home, real);
  if (!h.startsWith('..') && !path.isAbsolute(h)) {
    const hp = toPosix(h);
    if (!ctx.sub && /^projects\/[^/]+\/memory\//.test(hp)) return { decision: 'allow', reason: 'auto-memory' };
    return { decision: 'deny', reason: 'global Claude Code configuration (~/.claude) must not be modified by this project' };
  }
  return ctx.sub
    ? { decision: 'deny', reason: `'${abs}' is outside the repository` }
    : { decision: 'ask', reason: `'${abs}' is outside the repository; confirm` };
}
