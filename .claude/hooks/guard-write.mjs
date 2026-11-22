#!/usr/bin/env node
// PreToolUse guard for Edit | Write | MultiEdit | NotebookEdit.
// Enforces: secret files, governance paths, approved Change Set scope, security-boundary acknowledgement,
// per-agent file ownership, read-only roles, and secret literals in written content. Fail-closed.
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { ROOT } from '../orchestration/ledger-core.mjs';
import { assertWorktree } from '../orchestration/evidence-policy.mjs';
import { readInput, block, ask, allow, guarded, isSubagent, agentName } from './lib.mjs';
import { decideWriteAbs } from './scope.mjs';
import { scanSecrets } from '../orchestration/patterns.mjs';

guarded(() => {
  const input = readInput();
  const worktree = execFileSync('git', ['-C', input.cwd || process.cwd(), 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
  assertWorktree(worktree, ROOT);
  const ti = input.tool_input || {};
  const target = ti.file_path || ti.notebook_path;
  if (!target) block('write tool call without a file path');
  const abs = path.isAbsolute(target) ? target : path.resolve(input.cwd || process.cwd(), target);
  const ctx = { agent: agentName(input), sub: isSubagent(input) };

  const d = decideWriteAbs(abs, ctx, input.scratchpad_dir);
  if (d.decision === 'deny') block(`${d.reason} [${ctx.agent}]`);

  const texts = [ti.content, ti.new_string, ti.new_source, ...(Array.isArray(ti.edits) ? ti.edits.map((e) => e && e.new_string) : [])].filter((x) => typeof x === 'string');
  const hits = texts.flatMap((t) => scanSecrets(t));
  if (hits.length) block(`content appears to contain secret material (${[...new Set(hits.map((h) => h.rule))].join(', ')}); secrets are never written to files. For a deliberate fake test fixture add the marker comment 'inboundcheck:allow-fake-secret' on that line.`);

  if (d.decision === 'ask') ask(d.reason);
  allow();
});
