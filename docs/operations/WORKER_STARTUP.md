# Worker startup: source evidence and local verification

Reviewed 2026-11-04 against base HEAD `34dfb5cfd6cd41de453c3683f7d2dd365f940404` plus local, uncommitted fixes. This is not a deployed revision or a production-readiness certification.

## Commands represented in source

| Source | Command / behavior |
| --- | --- |
| `backend/Dockerfile` | `uvicorn app.main:app --host 0.0.0.0 --port 8000` (API default) |
| `docker-compose.yml`, audit-worker | `python -m app.workers.runner audit` |
| `docker-compose.yml`, failover-worker | `python -m app.workers.runner failover` |
| `backend/app/workers/runner.py` | Positional `audit`, `failover`, or `all`; default audit. `--once`; positive `--limit N` / `--limit=N`, default 25. |

Run module commands with `backend/` as the working directory, as the image does with `/app`. Worker commands can claim jobs, access databases and send notifications. `--once` means one processing cycle, not dry-run. The CLI does not select mode from the Railway service name, Docker service name, or an undocumented `WORKER_MODE` variable. An API-default image is not proof of a deployed worker misconfiguration.

Direct staging execution through the ordinary runner is rejected. `app.workers.staging_runner` exists and bootstraps staging isolation before delegating; it is not executed by the offline verification below. Project-ref constants in source do not verify the real production/staging mapping.

## API host configuration is separate from worker startup

`app.main` passes `core.trusted_hosts.get_allowed_hosts(settings)` to `TrustedHostMiddleware`. `config.ALLOWED_HOSTS` is a JSON list with default `[]`. Nonlocal API deployment must configure exact hostnames in that list or receive its exact `RAILWAY_PUBLIC_DOMAIN` from Railway. Schemes, ports and wildcards are rejected; no `*.railway` exception exists. Development/test adds local hosts only when staging mode is disabled. An empty nonlocal list aborts API initialization; this is not a worker-mode selector. API and worker environment guards normalize surrounding whitespace in `ENVIRONMENT` consistently with the host guard.

The current Compose API probe requests `http://localhost:8000/health`, hence sends Host `localhost`. A nonlocal configuration that allows only a public API hostname will reject that probe unless its Host header or exact allowlist is aligned. No deployed probe configuration was inferred, no wildcard was added and no container was started to validate this interaction.

## Confirmed local fixes

The previous hand-written parser silently ignored malformed limits/unknown switches, and `--limit 7` could replace the requested worker mode with `7`. Its outer `except (KeyboardInterrupt, SystemExit)` could swallow a nonzero exit and finish successfully. The runner now parses strictly before settings or worker imports and preserves nonzero `SystemExit` / runtime failures. Direct `main()` calls reject invalid modes and nonpositive/noninteger limits before validation or dispatch. The worker environment guard strips whitespace before deciding whether production/staging enforcement applies, consistent with the entrypoint staging gate.

The INV-01 fix remains the import of the existing `sanitize_log_message` from `app.services.failover.omnichannel_service`; no replacement sanitizer was added to `env_guard.py`.

## Offline verification

Use an interpreter with backend requirements installed; no service credentials are needed. From the repository root:

```powershell
python -I -B scripts/safe_backend_tests.py tests/test_worker_startup_regression.py tests/test_worker_import_regression.py tests/test_worker_env_guard.py tests/test_staging_worker_isolation.py -q
```

Latest local run: **87 passed, 3 warnings in 7.98s**, exit 0, using the parent verification environment, including the additional API normalization consistency regression. The runner denies repository dotenv reads and external networking and excludes the live staging lifecycle suite. The new startup tests load the real runner into a separate module namespace, exercise its actual CLI/validation and replace work functions before calling it; they introduce no subprocess exception. The existing approved isolated subprocess exercises the real failover lazy-import path with a pre-set stop event and checks that no Supabase client is initialized. No job claims or notifications are used as proof of startup.

## What remains unknown

No `railway.json`, `railway.toml`, or backend `railway*` manifest exists in the reviewed checkout. No manifest was invented. The earlier dashboard access returned 404/Login, so the actual service command, deployed commit, environment, healthcheck, startup logs and current queue health remain unverified. Do not call the deployment recovered based on these tests. No Docker build or Compose service start was performed in this check.

`supabase/migrations/` and `CANONICAL_MIGRATIONS` in `scripts/reconcile_migration_ledger.py` are migration source, not evidence of applied SQL. Local source-only changes remain unapplied; database migration, ledger reconciliation, environment changes, restart, deployment and git push require separate approval.

## Documentation corrections

README uses the restored committed environment templates. Cloudflare is the only automated DNS change provider accepted by `backend/app/services/dns/auto_fixer.py`; GoDaddy requires manual DNS entry. Historical audit statements about an existing Railway manifest or known deployed probe are not current evidence.
