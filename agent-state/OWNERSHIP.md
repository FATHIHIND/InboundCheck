# Worktree and File Ownership

Updated: 2026-11-23 (UTC; exact time not recorded)
Coordinator: Codex

| Workstream | Owner | Worktree | Branch | Owned files | State | Last verified |
|---|---|---|---|---|---|---|
| Shared project memory | Codex | `worktrees/shared-agent-memory` | `chore/shared-agent-memory` | `AGENTS.md`; `agent-state/**` | local implementation | 2026-11-23 |
| Telegram outbound entitlement PR #23 | Codex | `worktrees/telegram-outbound-entitlements` | `fix/telegram-outbound-entitlements` | `backend/app/api/v1/failover.py`; `backend/app/api/v1/settings.py`; `backend/tests/test_telegram_outbound_entitlements.py` | Draft PR; checks passed at last inspection | 2026-11-23 |
| Cloudflare DNS auto-fix tenant isolation | Cloudflare engineer / coordinator | `worktrees/cloudflare-autofix-tenant-isolation` | `fix/cloudflare-autofix-tenant-isolation` | `backend/app/api/v1/auto_fix.py`; `backend/app/services/dns/auto_fixer.py`; `backend/app/services/dns/cloudflare_client.py`; `backend/app/services/dns/record_policy.py`; five scoped tests | verification incomplete; no commit | 2026-11-23 |
| AI rate-limiter CI regression | Claude Code | Claude-owned worktree (path not recorded here) | Claude-owned branch (name not recorded here) | Claude-owned files only | active / external to Codex ownership | UNVERIFIED |

## Shared-file protocol

- Codex is the sole writer for files in this directory. Claude Code submits proposed concise updates to Codex; Claude does not edit shared state files.
- Codex updates only one shared-state patch at a time, checks `git status` and the diff, then records the update in `CURRENT.md`.
- Other agents and workstream owners must not stage or edit `agent-state/**` unless Codex explicitly transfers ownership in this file.
- Writers use separate worktrees and explicit source-file ownership. Read-only reviewers may inspect any worktree but do not edit it.
- If ownership is unclear or the recorded owner is active, stop the overlapping write and coordinate first.
