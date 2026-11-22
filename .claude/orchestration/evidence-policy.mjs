// Evidence validation only; never grants approval, runs gates, or edits a ledger.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const canonical = x => JSON.stringify(x, Object.keys(x).sort());
export function supportedExecution(command) {
  const c = command.trim();
  // Only default interpreters whose identities are captured below. No shell/env wrappers.
  return /^(?:cd\s+backend\s*&&\s*)?py\s+-m\s+pytest(?:\s|$)/.test(c) ||
    /^(?:cd\s+frontend\s*&&\s*)?node\s+--loader\s+\.\/tests\/loader\.mjs\s+--test\s+tests\//.test(c) ||
    /^(?:cd\s+frontend\s*&&\s*)?npm\s+run\s+(build|lint)\s*$/.test(c);
}
export function assertWorktree(actual, expected) {
  const a = fs.statSync(fs.realpathSync(actual), { bigint: true });
  const b = fs.statSync(fs.realpathSync(expected), { bigint: true });
  if (!a.isDirectory() || !b.isDirectory() || a.dev !== b.dev || a.ino !== b.ino) throw new Error('wrong worktree');
}
export function resolveSkill(file) {
  const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  if (!/^---\r?\n[\s\S]*?^name:\s*\S+[\s\S]*?^description:\s*\S+[\s\S]*?^---/m.test(text)) throw new Error('invalid skill metadata');
  return text;
}
export function nextQuestion(decisions, settled) {
  return decisions.find(d => d.material && !settled.includes(d.id)) || null;
}
export function evidenceMatches(evidence, current) {
  if (!evidence || evidence.result !== 'PASS' || evidence.exit_code !== 0 || !evidence.command || !evidence.identity) return false;
  const old = evidence.identity;
  if (!evidence.before || JSON.stringify(evidence.before) !== JSON.stringify(old)) return false;
  return old.root === current.root && old.head === current.head &&
    canonical(old.inputs || {}) === canonical(current.inputs || {}) &&
    canonical(old.environment || {}) === canonical(current.environment || {});
}
export function releaseComplete(required, records, current, release) {
  return Boolean(release && required.length) && required.every(g =>
    evidenceMatches(records.filter(e => e.gate === g && e.release === release).at(-1), current));
}
export function captureIdentity(root) {
  const git = args => execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  const files = git(['ls-files', '--cached', '--others', '--exclude-standard', '-z']).split('\0').filter(Boolean);
  // Conservative invalidation: include tracked source/tests and declared dependencies.
  // Exclude credential files even if accidentally tracked. Their presence is a separate scan failure.
  const inputs = {};
  for (const f of files.sort()) {
    if (/(^|\/)\.env($|\.)|\.(pem|key|pfx|p12)$/i.test(f)) continue;
    const p = path.join(root, f);
    inputs[f] = fs.existsSync(p) ? hash(fs.readFileSync(p)) : 'DELETED';
  }
  for (const f of ['boundaries.json', 'gates.json', 'ledger.mjs', 'ledger-core.mjs', 'evidence-policy.mjs']) {
    const p = path.join(root, '.claude/orchestration', f);
    inputs['.claude/orchestration/' + f] = hash(fs.readFileSync(p));
  }
  for (const f of fs.readdirSync(path.join(root, '.claude/hooks')).filter(f => f.endsWith('.mjs'))) {
    inputs['.claude/hooks/' + f] = hash(fs.readFileSync(path.join(root, '.claude/hooks', f)));
  }
  for (const f of ['node_modules/.package-lock.json', 'frontend/node_modules/.package-lock.json']) {
    const p = path.join(root, f);
    inputs[f] = fs.existsSync(p) ? hash(fs.readFileSync(p)) : 'ABSENT';
  }
  let python = 'unavailable';
  try { python = hash(execFileSync(process.platform === 'win32' ? 'py' : 'python3',
    ['-c', 'import sys,importlib.metadata as m,json; print(json.dumps([sys.executable,sys.version,sorted((d.metadata["Name"],d.version) for d in m.distributions())]))'],
    { encoding: 'utf8', timeout: 10000 })); } catch {}
  let head; try { head = git(['rev-parse', 'HEAD']).trim(); } catch { head = 'UNBORN'; }
  return { root: fs.realpathSync(root), head, inputs,
    environment: { node: process.version, nodeExecutable: process.execPath, python, platform: process.platform, arch: process.arch } };
}
