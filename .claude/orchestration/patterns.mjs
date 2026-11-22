// Shared detection patterns (secrets, dangerous SQL). Findings report rule id + line only, NEVER the matched value.
// Opt-out marker for deliberately fake fixtures: a line containing `inboundcheck:allow-fake-secret`.
export const ALLOW_MARKER = 'inboundcheck:allow-fake-secret';

export const SECRET_RULES = [
  { id: 'private-key-block', re: /-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----/ },
  { id: 'stripe-secret-key', re: /\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}/ },
  { id: 'stripe-webhook-secret', re: /\bwhsec_[A-Za-z0-9]{16,}/ },
  { id: 'jwt-literal', re: /\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}/ },
  { id: 'aws-access-key-id', re: /\bAKIA[0-9A-Z]{16}\b/ },
  { id: 'github-token', re: /\bgh[pousr]_[A-Za-z0-9]{30,}/ },
  { id: 'slack-token', re: /\bxox[abprs]-[A-Za-z0-9-]{10,}/ },
  { id: 'telegram-bot-token', re: /\b\d{8,10}:[A-Za-z0-9_-]{35}\b/ },
  { id: 'dsn-with-password', re: /\bpostgres(?:ql)?:\/\/[^\s:@/]+:[^\s@/]{3,}@/ },
  { id: 'shopify-token', re: /\bshp(?:at|ss|ca|pa)_[A-Fa-f0-9]{24,}/ },
  { id: 'fernet-key-literal', re: /\b(?:FERNET|ENCRYPTION)_?KEY\s*[=:]\s*['"][A-Za-z0-9_-]{43}=['"]/i },
];

export const SQL_RULES = [
  { id: 'drop-table-or-database', re: /\bDROP\s+(?:TABLE|DATABASE|SCHEMA)\b/i },
  { id: 'truncate', re: /\bTRUNCATE\b/i },
  { id: 'delete-without-where', re: /\bDELETE\s+FROM\s+[\w."]+\s*;/i },
  { id: 'update-without-where', re: /\bUPDATE\s+[\w."]+\s+SET\b[^;]*;/i, requireNo: /\bWHERE\b/i },
  { id: 'disable-rls', re: /\bDISABLE\s+ROW\s+LEVEL\s+SECURITY\b|\bNO\s+FORCE\s+ROW\s+LEVEL\s+SECURITY\b/i },
  { id: 'drop-policy', re: /\bDROP\s+POLICY\b/i },
  { id: 'policy-using-true', re: /\bUSING\s*\(\s*true\s*\)|\bWITH\s+CHECK\s*\(\s*true\s*\)/i },
  { id: 'grant-to-anon-or-public', re: /\bGRANT\b[^;]*\bTO\s+(?:anon|PUBLIC)\b/i },
  { id: 'service-role-bypass', re: /\bBYPASSRLS\b/i },
];

export function scanText(text, rules) {
  const hits = [];
  const lines = String(text).split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(ALLOW_MARKER)) continue;
    for (const r of rules) {
      if (r.re.test(lines[i]) && !(r.requireNo && r.requireNo.test(lines[i]))) hits.push({ rule: r.id, line: i + 1 });
    }
  }
  return hits;
}
export const scanSecrets = (t) => scanText(t, SECRET_RULES);
export const scanSql = (t) => scanText(t, SQL_RULES);
