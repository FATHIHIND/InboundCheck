# InboundCheck Enterprise Platform

High-precision transactional email deliverability and DNS governance platform engineered for eCommerce brands and Shopify senders.

---

## 1. System Architecture

```text
[ Client: Next.js 14 App Router (Tailwind CSS, SVG Micro-Charts) ]
                      ↓ (Supabase SSR Cookie Auth & JWT)
[ Edge Middleware: Route Guards (/dashboard/*) ]
                      ↓ (Authorization: Bearer <token>)
[ Backend: FastAPI Engine (FastAPI 0.111+, Python 3.11/3.12+) ]
    ├── Security: RateLimiter, Anti-SSRF Guard, Fernet Credential Vault
    ├── DNS Engine: dnspython multi-resolver (SPF, DKIM, DMARC, BIMI)
    ├── Diagnostics: Plain-English Translation & Remediation Layer
    ├── Remediation: Cloudflare automated DNS changes; GoDaddy manual DNS guidance
    ├── Failover Engine: Automated Omnichannel Fallback Dispatch
    └── Monetization: Stripe Subscriptions & Webhook Idempotency
                      ↓
[ Data Layer: Supabase PostgreSQL (Strict RLS: auth.uid() = user_id) ]
```

---

## 2. Merchant Dashboard Destinations

The merchant experience is organized into five primary destinations, supported by a canonical setup wizard:

1. **Overview (`/dashboard`):** Real-time store health score, top deliverability KPIs, SVG historical reputation trends, and monitored domain portfolio.
2. **Stores & Domains (`/dashboard/shopify`):** Shopify store connection, transactional sender alignment audit, and failover routing logs.
3. **Action Center (`/dashboard/inspector`):** DNS diagnostic inspector with merchant-friendly plain-English findings, step-by-step remediation guidance, and 1-click auto-fix triggers.
4. **Settings & Billing (`/dashboard/settings`):** Tenant configuration, alert rules, API credentials, and Stripe subscription portal.
5. **Template Optimizer (`/dashboard/content-lab`):** Deliverability spam keyword density analysis and copy optimization preserving Shopify Liquid tags.
6. **Canonical Setup Wizard (`/dashboard/wizard`):** Consolidated 4-step DNS diagnostic and Shopify store connection workflow.

---

## 3. Plain-English Diagnostic & Remediation Architecture

InboundCheck translates raw RFC DNS records and complex email authentication protocols into merchant-actionable insights:
- **Plain-English Translations:** Raw DNS findings (e.g. `p=none`, `~all`, missing CNAME selectors) are translated into clear merchant explanations detailing what was detected, why it impacts inbox delivery, and the exact corrective action needed.
- **Lightweight SVG Visualizations:** Replaced CPU-heavy Canvas animations with performant, accessible SVG and CSS micro-visualizations (`ScoreGauge3DCanvas`, `InboxWitnessCanvas`, `RadarBeamCanvas`, `Sparkline3DCanvas`).

---

## 4. Local Development Quickstart

### Prerequisites
- Node.js 24.x and npm 11.x (matches frontend/package.json)
- Python 3.11+ / 3.12+
- Supabase Project or local instance

### Environment Setup
Copy the committed, placeholder-only environment templates, then configure required values locally. Never commit the resulting files:
```powershell
# Unified workspace template
Copy-Item .env.example .env

# Backend configuration
Copy-Item backend/.env.example backend/.env

# Frontend configuration
Copy-Item frontend/.env.example frontend/.env.local
```

### API hosts outside local development
`ALLOWED_HOSTS` is a JSON list, default `[]`. Outside development/test, configure exact API hostnames, for example `ALLOWED_HOSTS=["api.your-domain.tld"]`, or use the exact `RAILWAY_PUBLIC_DOMAIN` supplied by Railway. Do not include schemes, ports or wildcards. Missing or invalid deployment hosts abort API initialization; do not use `*` or a shared hosting-domain wildcard. Local development/test adds localhost automatically. This HTTP host control does not select or configure a background worker.

### Running Backend (FastAPI)
```powershell
Set-Location "backend"
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Running Frontend (Next.js)
```powershell
# From the workspace root (uses the root lockfile)
npm ci
npm run dev --workspace frontend
```

---

## 5. Container & Runtime Operations

### Docker Compose
Compose starts the API, two dedicated workers and the frontend. This operational command can connect to configured services and process queued work; it is not an offline test.
```powershell
docker compose up --build -d
```

### Worker process selection
The backend Dockerfile defaults to the HTTP API, not a worker. Compose overrides its command with `python -m app.workers.runner audit` and `python -m app.workers.runner failover`. From the backend directory, the runner also accepts `all`, `--once` and `--limit 7` (or `--limit=7`); it defaults to audit with a limit of 25. These commands process work and are not safety checks. Direct staging execution is rejected; the separate staging bootstrap must be reviewed before use.

No Railway manifest is present in this checkout. The actual deployed command, service mode and healthcheck cannot be inferred from the Docker default or Compose overrides. Authenticated Railway logs/configuration are unavailable; local test success is not deployment recovery. See [Worker runtime evidence](docs/operations/WORKER_STARTUP.md).

### Health & Readiness Probes
- **Liveness Probe:** `GET /health` — Verifies Python process and event loop responsiveness.
- **Readiness Probe:** `GET /ready` (or `GET /api/v1/health`) — Verifies live database persistence and background scheduler status.
- **Frontend Health:** `GET /` — Verified via container HTTP probe.

### Build Arguments for Frontend Docker Image
Because Next.js inlines `NEXT_PUBLIC_*` variables at compile time, pass required public arguments during build:
```dockerfile
docker build \
  --build-arg NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co \
  --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 \
  -t inboundcheck-frontend ./frontend
```

---

## 6. Verification & Test Commands

### Backend Test Suite
```powershell
# From the repository root, with backend dependencies installed:
python -I -B scripts/safe_backend_tests.py -q

# Focused credential-free worker checks:
python -I -B scripts/safe_backend_tests.py tests/test_worker_import_regression.py tests/test_worker_startup_regression.py -q
```

### Frontend Test Suite & Production Build
```powershell
Set-Location "frontend"
# Unit and integration tests
node --loader ./tests/loader.mjs --test tests/*.test.ts

# Production build compilation check
npm run build
```

---

## 7. Security Architecture

- **Cryptographic JWT Verification:** Backend enforces Supabase JWT verification (`HS256` via `SUPABASE_JWT_SECRET`) on all protected `/api/v1/*` routes using `get_current_user_id`.
- **Anti-SSRF Protection:** Multi-resolver engine blocks private RFC 1918 subnets, loopbacks, and AWS metadata endpoints (`169.254.169.254`).
- **Credential Encryption:** Third-party DNS provider credentials (Cloudflare tokens, GoDaddy API keys) are stored envelope-encrypted with Fernet cryptography (`ENCRYPTION_KEY`).
- **Client/Server Secret Boundary:** Server-only secrets (`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `STRIPE_SECRET_KEY`) are strictly segregated from frontend bundles.

## Migration source and deployment state

Schema sources live in `supabase/migrations/`; the canonical source inventory is `CANONICAL_MIGRATIONS` in `scripts/reconcile_migration_ledger.py`. File presence and local inventory checks do not prove that a target database has applied those migrations. Database reconciliation, SQL, deployment and worker commands require target confirmation and approval.
