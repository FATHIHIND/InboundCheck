#!/usr/bin/env node
// SubagentStop: records that a subagent of a given type actually finished (proof of invocation for review gates).
// Stores only agent type/id and message length; never the message text. Never blocks.
import fs from 'node:fs';
import path from 'node:path';
import { readInput } from './lib.mjs';
import { ORCH, getActive, appendEvent } from '../orchestration/ledger-core.mjs';

try {
  const input = readInput();
  const a = getActive();
  if (a) appendEvent(a.id, { type: 'agent_stop', agent_type: input.agent_type || 'unknown', agent_id: input.agent_id || null, message_chars: String(input.last_assistant_message || '').length });
} catch (e) { try { fs.appendFileSync(path.join(ORCH, 'hook-debug.log'), `${new Date().toISOString()} subagent-log error: ${e && e.message}\n`); } catch { /* ignore */ } }
process.exit(0);
