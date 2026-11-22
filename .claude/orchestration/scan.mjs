#!/usr/bin/env node
// Gate G-SCAN: secret and dangerous-SQL scan of the working-tree diff (or explicit files).
//   node .claude/orchestration/scan.mjs --changed
//   node .claude/orchestration/scan.mjs path/a path/b
// Prints rule ids and line numbers only. Matched values are never printed. Exit 1 on any blocking finding.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { ROOT, getActive, appendEvidence } from './ledger-core.mjs';
import { scanSecrets, scanSql } from './patterns.mjs';
import { captureIdentity } from './evidence-policy.mjs';

const before = captureIdentity(ROOT);

const args = process.argv.slice(2);
let files = args.filter((a) => !a.startsWith('--'));
if (args.includes('--changed')) {
  try {
    const out = execFileSync('git', ['-C', ROOT, 'status', '--porcelain=v1', '--untracked-files=all'], { encoding: 'utf8' });
    files = out.split(/\r?\n/).filter(Boolean).map((l) => l.slice(3).split(' -> ').pop().replace(/^"|"$/g, ''));
  } catch (e) { console.error('scan: cannot read git state: ' + e.message); process.exit(2); }
}
const SKIP = /\.(png|jpe?g|gif|ico|webp|woff2?|ttf|pdf|lock)$|(^|\/)(node_modules|\.next|__pycache__)\//i;
let blocking = 0;
for (const f of files) {
  const rel = f.replace(/\\/g, '/');
  if (SKIP.test(rel)) continue;
  const abs = path.resolve(ROOT, rel);
  let txt; try { txt = fs.readFileSync(abs, 'utf8'); } catch { continue; }
  if (txt.length > 2_000_000) { console.log(`${rel}: skipped (large file)`); continue; }
  const hits = [...scanSecrets(txt).map((h) => ({ ...h, kind: 'secret' }))];
  if (/\.sql$/i.test(rel)) hits.push(...scanSql(txt).map((h) => ({ ...h, kind: 'sql' })));
  for (const h of hits) { blocking++; console.log(`BLOCKING ${rel}:${h.line} ${h.kind}:${h.rule}`); }
}
if (args.includes('--changed')) {
  try {
    const a = getActive();
    if (a) appendEvidence(a.id, { before, source: 'ledger', gate: 'G-SCAN', covers: ['G-SCAN'], result: blocking ? 'FAIL' : 'PASS', files: files.length, findings: blocking });
  } catch { /* evidence is best effort here; DONE re-checks */ }
}
console.log(blocking ? `scan: ${blocking} blocking finding(s) in ${files.length} file(s)` : `scan: clean (${files.length} file(s) checked)`);
process.exit(blocking ? 1 : 0);
