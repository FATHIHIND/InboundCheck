#!/usr/bin/env node
// PreToolUse guard for the Agent/Task tool: only the main session (the Chief Orchestrator) may delegate.
// Existing personas (code-reviewer, security-auditor, test-engineer) say "Do not invoke from another persona";
// this makes that rule enforceable. Subagents cannot spawn subagents.
import { readInput, block, allow, guarded, isSubagent, agentName } from './lib.mjs';

guarded(() => {
  const input = readInput();
  if (isSubagent(input)) block(`subagent '${agentName(input)}' tried to spawn another agent; orchestration belongs to the main-session Chief Orchestrator (report the recommendation instead)`);
  allow();
});
