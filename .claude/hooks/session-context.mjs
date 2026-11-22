#!/usr/bin/env node
// SessionStart: if an autonomous run is active, print a compact recovery summary (added to context by Claude Code).
// Prints nothing when no run is active, so it costs zero tokens in normal sessions.
import { readActiveId, summarize } from '../orchestration/ledger-core.mjs';

try {
  const id = readActiveId();
  if (id) process.stdout.write(`InboundCheck autonomous run is ACTIVE.\n${summarize(id)}\n`);
} catch (e) { process.stdout.write(`InboundCheck: could not read the active run ledger (${e.message}). Run: node .claude/orchestration/ledger.mjs status\n`); }
process.exit(0);
