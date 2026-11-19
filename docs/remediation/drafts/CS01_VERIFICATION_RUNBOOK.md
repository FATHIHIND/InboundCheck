# CS-01 verification runbook (security grants and search_path)

**Status: DRAFT. Not approved. Nothing in this document has been applied to any database.**

The SQL draft is `CS01_security_grants_search_path_DRAFT.sql` in this folder. It is deliberately
outside `supabase/migrations/` so migration tooling cannot execute it.

## 1. Evidence behind the draft

| Finding | Source | Confidence |
|---|---|---|
| `handle_new_user`, `increment_upload_count`, `protect_profile_billing_columns` executable by `anon` and `authenticated` as SECURITY DEFINER | Supabase security advisors (read-only), 2026-11-17 | High (advisor output) |
| `increment_upload_count`, `set_updated_at`, `update_updated_at_column` have mutable `search_path` | Same advisor run | High (advisor output) |
| `handle_new_user` and `protect_profile_billing_columns` bodies | Repository migrations `20260904000001`, `20260925000002`, `20260925000003` | High (repo source) |
| `update_updated_at_column` body | Repository migration `20260903000001` | High (repo source) |
| `increment_upload_count` and `set_updated_at` bodies | **Not in repository** (searched all tracked files and remote branches) | **Unknown** |
| Production function bodies and grants as they exist today | **Not verified** (no read-only SQL path) | **Unknown** |

## 2. Blockers before any use

1. **Owner-approved schema export** (`pg_dump --schema-only`, with privileges) or an approved read-only export, to confirm the bodies, grants and `search_path` of every listed function.
2. **Decision on `increment_upload_count`.** It is SECURITY DEFINER and callable by `anon`. Revoking EXECUTE breaks any client that calls `/rest/v1/rpc/increment_upload_count`. Confirm there are no callers (frontend search found none in `frontend/src`) or convert the function to SECURITY INVOKER after reviewing its body.
3. **Trigger behaviour without EXECUTE.** The draft assumes triggers fire for the table owner without `anon` or `authenticated` holding EXECUTE. This must be proven in staging before production use.

## 3. Staging rehearsal (owner-approved only)

1. Restore a staging copy of the schema from the approved export. Do not use production.
2. Record the pre-state with the verification queries in the draft.
3. Apply the draft **to staging only**, inside its `BEGIN`/`COMMIT`.
4. Run the verification queries. Expected: `anon_exec = false` and `authenticated_exec = false` for `handle_new_user` and `protect_profile_billing_columns`; `proconfig` contains `search_path=public, pg_temp` for each existing function listed.
5. Confirm the profile billing triggers still exist and still fire: run the Stripe and Shopify billing tests against staging.
6. Run the full backend test suite against staging.

## 4. Rollback

The draft's rollback block restores `PUBLIC` EXECUTE and resets `search_path`. Rehearse it on staging before production.

Note: rollback of the REVOKE restores the PostgreSQL default (`EXECUTE` to `PUBLIC`), which is the state that produced the advisor findings. Rollback is therefore a security regression and should only be used to recover service.

## 5. Production gate

Production application requires separate owner approval after staging passes. Until then, this runbook and the draft are documentation only.
