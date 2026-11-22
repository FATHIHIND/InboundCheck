// Shared helpers for InboundCheck project hooks. FAIL-CLOSED: any internal error in a guard exits 2 (block),
// because Claude Code treats other non-zero exits as non-blocking errors (the action would proceed).
import fs from 'node:fs';

export function readInput() {
  const raw = fs.readFileSync(0, 'utf8');
  if (!raw.trim()) throw new Error('empty hook input');
  return JSON.parse(raw);
}

export function block(reason) {
  process.stderr.write(`BLOCKED by InboundCheck guard: ${reason}\n`);
  process.exit(2);
}

// "ask" forces a human confirmation prompt (used for main-session actions that are risky but legitimate).
export function ask(reason) {
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'ask', permissionDecisionReason: `InboundCheck guard: ${reason}` } }));
  process.exit(0);
}

export function allow() { process.exit(0); }

export function guarded(fn) {
  try { fn(); }
  catch (e) { block(`guard error (fail-closed): ${e && e.message ? e.message : e}`); }
}

export const isSubagent = (input) => Boolean(input.agent_type || input.agent_id);
export const agentName = (input) => input.agent_type || (input.agent_id ? 'unknown-subagent' : 'main');
