#!/usr/bin/env node
// PostToolUse (Bash|PowerShell): logs that a quality-gate-looking command was REPORTED to have run, and the outcome that report claimed.
// Entries are source="hook-observed": a convenience log derived from tool-call text (which an agent can fabricate, for example by echoing
// "500 passed"), so they NEVER satisfy a gate. Only entries written by .claude/orchestration/run-gate.mjs (source="runner") do.
// Never stores command output, only counts. If the tool_response shape cannot be interpreted the result is UNKNOWN.
// This hook never blocks (a PostToolUse failure must not break work); failures are logged to orchestration/hook-debug.log.
import fs from 'node:fs';
import path from 'node:path';
import { readInput } from './lib.mjs';
import { ORCH, getActive, appendEvidence, readActiveId, loadGates, sha256 } from '../orchestration/ledger-core.mjs';

function debug(msg) { try { fs.appendFileSync(path.join(ORCH, 'hook-debug.log'), `${new Date().toISOString()} ${msg}\n`); } catch { /* ignore */ } }

function flat(resp) {
  if (resp == null) return { text: '', code: undefined, keys: [] };
  if (typeof resp === 'string') return { text: resp, code: undefined, keys: ['<string>'] };
  const text = [resp.stdout, resp.stderr, resp.output, resp.content, resp.result].filter((x) => typeof x === 'string').join('\n');
  const code = [resp.exit_code, resp.exitCode, resp.returncode, resp.returnCode, resp.code, resp.status].find((x) => typeof x === 'number');
  return { text, code, keys: Object.keys(resp), interrupted: Boolean(resp.interrupted) };
}

function parsePytest(text) {
  const n = (re) => { const m = text.match(re); return m ? Number(m[1]) : 0; };
  return { passed: n(/(\d+) passed/), failed: n(/(\d+) failed/), errors: n(/(\d+) errors?\b/), collected: n(/(\d+) tests? collected/) };
}

function pytestTargets(tokens) {
  return tokens.filter((t) => /(^|[\\/])(tests?)([\\/]|$)|\.py(::|$)/.test(t) && !t.startsWith('-')).map((t) => t.replace(/\\/g, '/').split('::')[0]);
}

try {
  const input = readInput();
  const cmd = String((input.tool_input && input.tool_input.command) || '');
  const lc = cmd.toLowerCase();
  const { text, code, keys, interrupted } = flat(input.tool_response);
  // Shape discovery: log field NAMES (never values) of the first few gate-like commands even when no run is active,
  // so the real PostToolUse tool_response layout can be confirmed once hooks are live.
  if (/\bpytest\b|--test\b|npm run (build|lint)|\btsc\b/.test(lc)) debug(`PostToolUse keys=[${keys.join(',')}] exit=${code} interrupted=${interrupted} sub=${input.agent_type || 'main'} cmd_sha=${sha256(cmd).slice(0, 12)}`);
  const active = readActiveId() && getActive();
  if (!active || !active.approved) process.exit(0);
  const gates = loadGates().gates;
  const tokens = cmd.replace(/["']/g, ' ').split(/\s+/).filter(Boolean);

  const covers = []; let kind = null; let counts = {}; let result = 'UNKNOWN';
  const isPytest = /\bpytest\b/.test(lc);
  if (isPytest) {
    kind = 'pytest';
    counts = parsePytest(text);
    const targets = pytestTargets(tokens);
    const collectOnly = lc.includes('--collect-only') || lc.includes('--co ');
    if (code !== undefined) result = code === 0 ? 'PASS' : 'FAIL';
    else if (counts.failed || counts.errors) result = 'FAIL';
    else if (counts.passed > 0 || (collectOnly && counts.collected > 0)) result = 'PASS';
    // a PASS requires no failures even when the exit code is unavailable or 0
    if (result === 'PASS' && (counts.failed || counts.errors)) result = 'FAIL';
    const ran = new Set(targets.map((t) => path.posix.basename(t)));
    const wholeSuite = targets.some((t) => /^(\.\/)?(backend\/)?tests\/?$/.test(t)) || targets.length === 0;
    for (const g of gates) {
      if (!g.match || g.match.kind !== 'pytest' && g.match.kind !== 'scan_or_pytest') continue;
      const wantsCollect = (g.match.flags_any || []).includes('--collect-only');
      if (wantsCollect !== collectOnly) continue;
      const need = g.pytest_targets || [];
      if (!need.length) continue;
      const full = need.length === 1 && need[0] === 'tests';
      if (full ? wholeSuite : (wholeSuite || need.every((n) => ran.has(n)))) covers.push(g.id);
    }
    if (!/(^|[\s;&|])cd\s+backend|backend[\\/]/.test(lc) && !/pytest\.ini|--rootdir/.test(lc) && input.cwd && !/backend$/i.test(String(input.cwd).replace(/[\\/]+$/, ''))) {
      // pytest must run inside backend/ for pytest.ini (asyncio_mode=auto) to apply
      if (!/\b(-c|--rootdir|--config-file)\b/.test(lc)) { result = result === 'PASS' ? 'UNKNOWN' : result; debug('pytest cwd is not backend/; PASS downgraded to UNKNOWN'); }
    }
  } else if (/node\s+.*--test/.test(lc) && /tests[\\/]/.test(lc)) {
    kind = 'node_test'; result = code === undefined ? 'UNKNOWN' : code === 0 ? 'PASS' : 'FAIL'; covers.push('G-FE-UNIT');
  } else if (/\bnpm\s+run\s+(build|lint)\b/.test(lc)) {
    kind = 'npm'; result = code === undefined ? 'UNKNOWN' : code === 0 ? 'PASS' : 'FAIL'; covers.push(/run\s+build/.test(lc) ? 'G-FE-BUILD' : 'G-FE-LINT');
  } else if (/\btsc\b.*--noemit/.test(lc)) {
    kind = 'tsc'; result = code === undefined ? 'UNKNOWN' : code === 0 ? 'PASS' : 'FAIL'; covers.push('G-FE-TYPES');
  } else process.exit(0);

  appendEvidence(active.id, {
    source: 'hook-observed', kind, covers, result, exit_code: code ?? null, counts,
    command_sha: sha256(cmd).slice(0, 16), command_head: cmd.replace(/\s+/g, ' ').slice(0, 160),
    agent_type: input.agent_type || 'main', tool_use_id: input.tool_use_id || null,
  });
} catch (e) { debug(`record-gate error: ${e && e.message}`); }
process.exit(0);
