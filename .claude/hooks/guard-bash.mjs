#!/usr/bin/env node
// PreToolUse guard for Bash and PowerShell. Fail-closed.
// Blocks: git push/merge/commit/destructive history or tree operations, gh mutations, deploy/infra CLIs, production DB
// access and destructive SQL, secret exposure (.env reads, env dumps), dependency changes without an approved Change Set,
// writes to governance/secret paths, human-only approval commands. "ask" forces a human prompt (denied for subagents).
// LIMITATION (documented in orchestration/ARCHITECTURE.md): this is a static check of the command text. It cannot see what a
// script file, an interpreter program, or a variable expands to. It is a strong tripwire, not a sandbox.
import os from 'node:os';
import { execFileSync } from 'node:child_process';
import { assertWorktree, captureIdentity } from '../orchestration/evidence-policy.mjs';
import path from 'node:path';
import { readInput, block, ask, allow, guarded, isSubagent, agentName } from './lib.mjs';
import { decideWriteAbs } from './scope.mjs';
import { getActive, ROOT, appendEvent, sha256 } from '../orchestration/ledger-core.mjs';

const WRAPPERS = new Set(['sudo', 'env', 'nohup', 'time', 'command', 'exec', 'xargs', 'nice', 'timeout', 'stdbuf', 'builtin', 'call', 'start', 'start-process', 'invoke-expression', 'iex']);
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'pwsh', 'powershell', 'cmd', 'wsl']);
const INTERPRETERS = new Set(['python', 'python3', 'py', 'node', 'perl', 'ruby', 'php', 'deno', 'bun']);
const DEPLOY_CLIS = new Set(['railway', 'vercel', 'wrangler', 'flyctl', 'fly', 'netlify', 'heroku', 'render', 'kubectl', 'helm', 'terraform', 'pulumi', 'aws', 'gcloud', 'az', 'doctl', 'cloudflared', 'firebase', 'amplify', 'shopify', 'stripe', 'supabase']);
const DB_CLIS = new Set(['psql', 'pg_dump', 'pg_dumpall', 'pg_restore', 'pgcli', 'mysql', 'mariadb', 'mongosh', 'redis-cli', 'sqlcmd', 'alembic', 'flyway', 'sqitch']);
const READERS_SAFE_FOR_ENV = new Set(['ls', 'dir', 'stat', 'test', '[', 'find', 'file', 'test-path', 'get-childitem', 'gci', 'get-item', 'gi', 'realpath']);
const PROD_HOSTS = /(supabase\.co|supabase\.in|railway\.app|up\.railway|api\.stripe\.com|myshopify\.com|api\.cloudflare\.com|vercel\.app|vercel\.com)/i;
const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[?::1\]?|host\.docker\.internal|0\.0\.0\.0)(:\d+)?$/i;
const SENSITIVE_NAME = /(KEY|SECRET|TOKEN|PASS(WORD)?|DSN|DATABASE_URL|SERVICE_ROLE|JWT|CREDENTIAL|PRIVATE)/i;
const CACHE_DIRS = new Set(['__pycache__', '.pytest_cache', 'node_modules', '.next', 'htmlcov', '.mypy_cache', '.ruff_cache', 'dist', 'build']);

function tokenize(s) {
  const out = []; let cur = ''; let q = null; let has = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (q) { if (c === q) q = null; else if (c === '\\' && q === '"' && i + 1 < s.length) cur += s[++i]; else cur += c; continue; }
    if (c === '"' || c === "'") { q = c; has = true; continue; }
    if (/\s/.test(c)) { if (cur || has) { out.push(cur); cur = ''; has = false; } continue; }
    cur += c;
  }
  if (cur || has) out.push(cur);
  return out;
}

function splitSegments(s) {
  const segs = []; let cur = ''; let q = null;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (q) { cur += c; if (c === q) q = null; continue; }
    if (c === '"' || c === "'") { q = c; cur += c; continue; }
    if (c === '\n' || c === ';' || c === '|' || c === '&') {
      if ((c === '&' || c === '|') && s[i + 1] === c) i++;
      else if (c === '&' && (s[i - 1] === '>' || s[i + 1] === '>')) { cur += c; continue; } // 2>&1, &>
      segs.push(cur); cur = ''; continue;
    }
    cur += c;
  }
  segs.push(cur);
  const extra = [];
  for (const m of s.matchAll(/\$\(([^()]*)\)/g)) extra.push(m[1]);
  for (const m of s.matchAll(/`([^`]*)`/g)) extra.push(m[1]);
  return [...segs, ...extra].map((x) => x.trim()).filter(Boolean);
}

const base = (t) => path.basename(String(t)).toLowerCase().replace(/\.(exe|cmd|bat|ps1|com)$/, '');
const isEnvFile = (t) => /^\.env(\..+)?$/i.test(path.basename(String(t).replace(/\\/g, '/'))) && !/\.(example|sample|template)$/i.test(String(t));

function gitSub(tokens) {
  let i = 1;
  while (i < tokens.length) {
    const t = tokens[i];
    if (['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path'].includes(t)) { i += 2; continue; }
    if (t.startsWith('-')) { i++; continue; }
    return { sub: t.toLowerCase(), args: tokens.slice(i + 1) };
  }
  return { sub: '', args: [] };
}

function analyze(cmd, ctx, depth, out) {
  if (depth > 4) { out.push({ level: 'deny', reason: 'command nesting too deep to analyze' }); return; }
  if (/(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^|]*\|\s*(sudo\s+)?((ba|z)?sh|iex|invoke-expression|python3?|node|powershell|pwsh)\b/i.test(cmd)) out.push({ level: 'deny', reason: 'piping downloaded content into a shell/interpreter is not permitted' });
  for (const seg of splitSegments(cmd)) checkSegment(seg, ctx, depth, out);
}

function checkSegment(seg, ctx, depth, out) {
  const push = (level, reason) => out.push({ level, reason });
  let tokens = tokenize(seg);
  while (tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[0])) tokens.shift();
  if (!tokens.length) return;
  const prog = base(tokens[0]);
  const rest = tokens.slice(1);
  const lower = tokens.map((t) => t.toLowerCase());

  // human-only approval command; never runnable by an agent
  if (tokens.some((t) => /ledger\.mjs$/i.test(t)) && lower.includes('approve')) push('deny', "'ledger.mjs approve' is human-only: the user approves a Change Set by typing it themselves (prefix with !)");
  if (/approvals?[\\/]/i.test(seg) && !/^(ls|dir|cat|type|get-content|test-path)$/.test(prog)) push('deny', 'the approvals directory is human-controlled');

  // wrappers and nested shells
  if (WRAPPERS.has(prog) && rest.length) {
    let r = rest;
    while (r.length && (/^-/.test(r[0]) || /^\d+(\.\d+)?[smhd]?$/.test(r[0]))) r = r.slice(1);
    analyze(r.join(' '), ctx, depth + 1, out);
  }
  if (SHELLS.has(prog)) {
    const i = lower.findIndex((t) => ['-c', '-command', '/c', '-encodedcommand', '-ec'].includes(t));
    if (i >= 0) { if (lower[i].includes('enc') || lower[i] === '-ec') push('deny', 'encoded PowerShell commands cannot be inspected'); else analyze(tokens.slice(i + 1).join(' '), ctx, depth + 1, out); }
  }
  if (['eval', 'iex', 'invoke-expression'].includes(prog)) push('ask', 'eval/Invoke-Expression runs text that cannot be inspected');
  if (/\|\s*(ba|z)?sh\b|\|\s*(iex|invoke-expression)\b/i.test(seg) || /(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)[^|]*\|\s*(ba|z)?sh/i.test(seg)) push('deny', 'piping downloaded content into a shell is not permitted');

  // ---- git ----
  if (prog === 'git') {
    const { sub, args } = gitSub(tokens);
    const al = args.map((a) => a.toLowerCase());
    const DENY = new Set(['push', 'merge', 'commit', 'rebase', 'cherry-pick', 'revert', 'tag', 'am', 'pull', 'reset', 'clean', 'restore', 'rm', 'mv', 'update-ref', 'filter-branch', 'filter-repo', 'gc', 'prune', 'reflog', 'replace', 'send-email', 'bundle', 'fast-import']);
    if (DENY.has(sub)) push('deny', `git ${sub} is not permitted for the autonomous team (no commit/push/merge/history or working-tree destruction without explicit user approval; the user runs it themselves)`);
    else if (sub === 'stash' && !['list', 'show'].includes(al[0] || '')) push('deny', 'git stash would move working changes out of sight');
    else if (sub === 'branch' && al.some((a) => /^-(d|m|f|c)$/i.test(a) || ['--delete', '--move', '--force', '--copy'].includes(a))) push('deny', 'git branch delete/move/force is not permitted');
    else if (sub === 'remote' && al[0] && !['-v', 'show', 'get-url'].includes(al[0])) push('deny', 'git remote modification is not permitted');
    else if (sub === 'config') push('deny', 'git config can read or write credentials; not permitted');
    else if (sub === 'worktree' && ['remove', 'prune', 'move'].includes(al[0] || '')) push('deny', 'git worktree remove/prune/move is not permitted');
    else if (['checkout', 'switch', 'apply', 'submodule', 'fetch'].includes(sub)) push('ask', `git ${sub} changes the working tree or contacts the remote; confirm with the user`);
    if (args.some(isEnvFile) && !['check-ignore', 'status', 'ls-files'].includes(sub)) push('deny', 'git command touching a .env file');
  }

  // ---- gh ----
  if (prog === 'gh') {
    const g = lower[1] || ''; const h = lower[2] || '';
    const READ = { pr: ['view', 'list', 'diff', 'checks', 'status'], issue: ['view', 'list', 'status'], repo: ['view', 'list'], run: ['view', 'list'], auth: ['status'], release: ['list', 'view'] };
    const isApi = g === 'api';
    if (isApi) {
      if (lower.some((t, i) => (t === '-x' || t === '--method') && lower[i + 1] && lower[i + 1] !== 'get') || lower.some((t) => ['-f', '--field', '--raw-field', '--input'].includes(t))) push('deny', 'gh api with a mutating method or fields is not permitted');
      else push('ask', 'gh api reaches GitHub; confirm with the user');
    } else if (!(READ[g] && READ[g].includes(h)) && !['--version', 'version', 'help', '--help'].includes(g)) push('deny', `gh ${g} ${h} is not permitted (GitHub changes, merges, releases and secrets need explicit user approval)`);
  }

  // ---- deploy / infra / DB CLIs ----
  const checkCli = (name, toks) => {
    if (DEPLOY_CLIS.has(name)) {
      if (!toks.slice(1).every((t) => ['--version', '-v', 'version', '--help', '-h', 'help'].includes(t.toLowerCase()))) push('deny', `${name} operates on live external services; not permitted for the autonomous team`);
    }
    if (DB_CLIS.has(name)) push('deny', `${name} can read or mutate a database; autonomous testing never touches a production database`);
  };
  checkCli(prog, tokens);
  if (['npx', 'pnpx', 'bunx'].includes(prog) || (['npm', 'pnpm', 'yarn'].includes(prog) && ['exec', 'dlx', 'x'].includes(lower[1]))) {
    const first = tokens.findIndex((t, i) => i > 0 && !t.startsWith('-') && !['exec', 'dlx', 'x'].includes(t.toLowerCase()));
    if (first > 0) checkCli(base(tokens[first].replace(/@[^/]*$/, '')), tokens.slice(first));
    push('ask', 'npx/exec downloads and runs package code; confirm with the user');
  }
  if (tokens.some((t) => /\bapp[./]workers[./](runner|staging_runner|failover_worker|audit_worker)/i.test(t)) || /-m\s+app\.workers/i.test(seg)) push('deny', 'starting a worker connects to the configured database/services; running workers is not autonomous');
  if (/postgres(ql)?:\/\/(?!(localhost|127\.0\.0\.1|\[::1\]|host\.docker\.internal))/i.test(seg) || /--db-url|--linked|--project-ref/.test(seg)) push('deny', 'remote database connection string/flag in a command');
  if (prog === 'docker' || prog === 'docker-compose' || (prog === 'podman')) {
    const sub = prog === 'docker-compose' ? lower[1] : lower[1] === 'compose' ? 'compose ' + (lower[2] || '') : (lower[1] || '');
    if (/^(push|login|logout|trust|manifest)/.test(sub) || /^(system prune|volume rm|volume prune|network prune|image prune|builder prune)/.test(lower.slice(1).join(' ')) || /(compose )?config$/.test(sub) || sub === 'inspect' || lower.includes('psql')) push('deny', 'this docker operation can publish images, delete data, or print resolved environment values');
    else if (!['ps', 'images', 'version', 'info', 'logs', 'compose ps', 'compose logs', 'compose version'].includes(sub)) push('ask', 'docker run/compose can start containers that read local .env values; requires explicit user approval');
  }

  // ---- package managers (dependency changes) ----
  const isPip = ['pip', 'pip3'].includes(prog) || (INTERPRETERS.has(prog) && lower.includes('-m') && lower.includes('pip'));
  const pipSub = isPip ? lower.find((t, i) => i > 0 && ['install', 'uninstall', 'download', 'wheel'].includes(t)) : null;
  const jsSub = ['npm', 'pnpm', 'yarn', 'bun'].includes(prog) ? (lower[1] || '') : '';
  const jsDep = ['install', 'i', 'add', 'ci', 'update', 'up', 'upgrade', 'uninstall', 'remove', 'rm', 'link', 'dedupe', 'prune'].includes(jsSub) || (jsSub === 'audit' && lower.includes('fix'));
  const uvDep = ['uv', 'poetry', 'pipx', 'conda', 'mamba'].includes(prog) && ['add', 'remove', 'sync', 'lock', 'install', 'update', 'upgrade', 'pip'].includes(lower[1] || '');
  if (['publish', 'login', 'adduser', 'logout', 'token', 'owner'].includes(jsSub)) push('deny', `${prog} ${jsSub} publishes or handles registry credentials`);
  if (pipSub || jsDep || uvDep) {
    const a = getActive();
    if (a && a.approved && a.changeSet && a.changeSet.allow_dependency_changes) push('ask', 'dependency installation/update (approved by the Change Set) still needs a human confirmation');
    else push('deny', 'dependency installation/changes are outside the approved Change Set (allow_dependency_changes is not granted)');
  }
  if (['npm', 'pnpm', 'yarn'].includes(prog) && ['run', 'run-script'].includes(jsSub) && ['dev', 'start'].includes(lower[2])) push('ask', 'starting a dev/prod server needs confirmation');
  if (['uvicorn', 'gunicorn', 'hypercorn'].includes(prog)) push('ask', 'starting an API server needs confirmation');

  // ---- network ----
  if (['curl', 'wget', 'invoke-webrequest', 'iwr', 'invoke-restmethod', 'irm', 'http', 'https', 'xh'].includes(prog)) {
    const urls = tokens.filter((t) => /^https?:\/\//i.test(t));
    const nonLocal = urls.filter((u) => { try { return !LOCAL_HOST.test(new URL(u).host); } catch { return true; } });
    const mutating = tokens.includes('-F') || tokens.includes('-T') || lower.some((t, i) => ((t === '-x' || t === '--request' || t === '-method') && /^(post|put|patch|delete)$/i.test(lower[i + 1] || '')) || ['-d', '--form', '--upload-file', '-body', '-infile', '--json'].includes(t) || t.startsWith('--data') || t.startsWith('--post') || t.startsWith('--body-'));
    if (urls.some((u) => PROD_HOSTS.test(u))) push('deny', 'requests to production/hosting provider APIs are not permitted');
    else if (mutating && nonLocal.length) push('deny', 'state-changing HTTP request to a non-local host is not permitted');
    if (lower.some((t, i) => /^(-h|--header)$/.test(t) && /(authorization|apikey|api-key|x-api-key)\s*:\s*\S{12,}/i.test(tokens[i + 1] || ''))) push('deny', 'credential literal in an HTTP header');
  }

  // ---- secrets exposure ----
  const envTokens = tokens.slice(1).filter(isEnvFile);
  if (envTokens.length && !READERS_SAFE_FOR_ENV.has(prog) && prog !== 'git') push('deny', 'reading or copying a .env file is not permitted (secrets are never read; use .env.example for variable names)');
  if (prog === 'printenv' || (prog === 'env' && !rest.some((t) => !t.startsWith('-') && !/^[A-Za-z_]\w*=/.test(t) && !!t) && !rest.some((t) => /^[A-Za-z_]\w*=/.test(t))) || (['export', 'declare', 'typeset', 'compgen'].includes(prog) && rest.every((t) => t.startsWith('-'))) || (prog === 'set' && rest.length === 0)) push('deny', 'dumping environment variables can expose secrets');
  if (/\b(get-childitem|gci|dir|ls|get-item|gi)\s+(-path\s+)?env:/i.test(seg) || /\[environment\]::getenvironmentvariable/i.test(seg) || /\bos\.environ\b(?!\.get\(['"][A-Z_]*(URL|HOST|ENV|MODE)['"])|process\.env\b/.test(seg) && INTERPRETERS.has(prog)) push('deny', 'reading environment variables can expose secrets');
  if (['echo', 'printf', 'write-host', 'write-output', 'print', 'cat'].includes(prog)) {
    for (const m of seg.matchAll(/\$\{?env:?([A-Za-z_][A-Za-z0-9_]*)\}?|\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?|%([A-Za-z_][A-Za-z0-9_]*)%/gi)) {
      const name = m[1] || m[2] || m[3];
      if (name && SENSITIVE_NAME.test(name)) { push('deny', `printing the value of a sensitive variable (${name}) is not permitted`); break; }
    }
  }
  if (tokens.slice(1).some((t) => /(\.ssh[\\/]|\.aws[\\/]|\.netrc|\.pgpass|\.git-credentials|\.docker[\\/]config\.json|\.config[\\/]gh|\.npmrc|id_(rsa|ed25519)|\.claude[\\/]\.credentials|service-account.*\.json)/i.test(t)) && !READERS_SAFE_FOR_ENV.has(prog)) push('deny', 'access to credential stores is not permitted');

  // ---- destructive filesystem ----
  const recursive = lower.some((t) => (/^-[a-z]{1,4}$/.test(t) && t.includes('r')) || t === '--recursive' || t === '-recurse');
  if (['rm', 'del', 'erase', 'remove-item', 'ri', 'rmdir', 'rd', 'shred'].includes(prog) || (prog === 'find' && lower.includes('-delete'))) {
    const targets = tokens.slice(1).filter((t) => !t.startsWith('-') || (prog === 'remove-item' && false));
    const rec = recursive || prog === 'rmdir' || prog === 'rd' || (prog === 'find');
    if (rec) {
      for (const t of targets) {
        const abs = path.resolve(ctx.cwd, t.replace(/^~(?=$|[\\/])/, os.homedir()));
        const bn = path.basename(abs);
        const inside = path.relative(ctx.root, abs);
        const within = !inside.startsWith('..') && !path.isAbsolute(inside) && inside !== '';
        if (/[*?]/.test(t) && !CACHE_DIRS.has(bn)) push('deny', `recursive delete with a wildcard target '${t}' is not permitted`);
        else if (!within) push('deny', `recursive delete outside the repository ('${t}') is not permitted`);
        else if (!CACHE_DIRS.has(bn)) push(ctx.sub ? 'deny' : 'ask', `recursive delete of '${t}' (not a known cache directory) needs the user's confirmation`);
      }
    }
  }

  // ---- DDL/destructive SQL embedded in command text ----
  if (/\b(drop\s+(table|database|schema)|truncate\s+table|delete\s+from\s+\w+\s*(;|"|'|$)|disable\s+row\s+level\s+security|drop\s+policy)\b/i.test(seg) && !/^(grep|rg|egrep|findstr|select-string|sls|cat|type|get-content|echo|printf|git)$/.test(prog)) push('deny', 'destructive SQL statement in a command');

  // ---- write targets (redirects and write-capable programs) ----
  const targets = [];
  for (const m of seg.matchAll(/(?<![<>&\d])\d?>>?\s*(?!&)("[^"]+"|'[^']+'|[^\s;|&)]+)/g)) targets.push(m[1].replace(/^["']|["']$/g, ''));
  const nonFlag = tokens.slice(1).filter((t) => !t.startsWith('-'));
  if (['tee', 'touch', 'mkdir', 'md', 'new-item', 'ni', 'set-content', 'sc', 'add-content', 'ac', 'out-file', 'truncate', 'ln', 'install', 'rm', 'del', 'erase', 'remove-item', 'ri', 'rmdir', 'rd', 'mv', 'move', 'move-item', 'mi', 'ren', 'rename', 'rename-item', 'rni'].includes(prog)) targets.push(...nonFlag);
  if (['cp', 'copy', 'copy-item', 'cpi', 'install'].includes(prog) && nonFlag.length) targets.push(nonFlag[nonFlag.length - 1]);
  if (prog === 'sed' && lower.some((t) => /^-[a-z]*i/.test(t) || t.startsWith('--in-place'))) targets.push(...nonFlag.slice(1));
  if (prog === 'perl' && lower.some((t) => /^-[a-z]*i/.test(t))) targets.push(...nonFlag.slice(1));
  for (const t of targets) {
    if (!t || /^(\/dev\/(null|stderr|stdout)|nul|\$null)$/i.test(t)) continue;
    if (/[$%`*?]/.test(t)) { push(ctx.sub ? 'deny' : 'ask', `write target '${t}' contains a variable or wildcard that cannot be resolved`); continue; }
    const abs = path.resolve(ctx.cwd, t.replace(/^~(?=$|[\\/])/, os.homedir()));
    if (['rm', 'del', 'erase', 'remove-item', 'ri', 'rmdir', 'rd'].includes(prog) && CACHE_DIRS.has(path.basename(abs))) continue; // cache cleanup is handled by the recursive-delete rule
    const d = decideWriteAbs(abs, ctx, ctx.scratchpad);
    if (d.decision !== 'allow') push(d.decision, `shell write to '${t}': ${d.reason}`);
  }

  // ---- opaque interpreters that mention protected paths ----
  if (INTERPRETERS.has(prog) || ['powershell', 'pwsh'].includes(prog)) {
    if (/(\.claude[\\/](hooks|settings|agents|skills|orchestration)|ledger[.-](json|core)|approvals|\.env\b|\.git[\\/])/i.test(seg) && /(write|open\(|unlink|remove|rmtree|rename|replace|copy|move|appendfile|set-content|out-file|sed -i|>)/i.test(seg)) push('deny', 'interpreter code that appears to modify governance, approval, ledger, .env or .git paths');
  }
}

guarded(() => {
  const input = readInput();
  const worktree = execFileSync('git', ['-C', input.cwd || process.cwd(), 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
  assertWorktree(worktree, ROOT);
  const command = String((input.tool_input && input.tool_input.command) || '');
  if (!command.trim()) allow();
  const ctx = { agent: agentName(input), sub: isSubagent(input), cwd: input.cwd || process.cwd(), scratchpad: input.scratchpad_dir, root: ROOT };
  const findings = [];
  analyze(command, ctx, 0, findings);
  const denies = findings.filter((f) => f.level === 'deny' || (f.level === 'ask' && ctx.sub));
  if (denies.length) block(`${[...new Set(denies.map((f) => f.reason))].join(' | ')} [${ctx.agent}]`);
  const asks = findings.filter((f) => f.level === 'ask');
  if (asks.length) ask([...new Set(asks.map((f) => f.reason))].join(' | '));
  const active = getActive();
  if (active?.approved && input.tool_use_id && /pytest|--test|npm run (build|lint)|tsc.*--noEmit/.test(command)) {
    appendEvent(active.id, { type: 'gate_start', tool_use_id: input.tool_use_id, command_sha: sha256(command).slice(0,16), before: captureIdentity(ROOT) });
  }
  allow();
});
