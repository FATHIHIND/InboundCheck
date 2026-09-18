# InboundCheck Enterprise — Master Agent Operating System (AGENTS.md)

> **Autonomous Agent Governance, Persona Roles, and Skill Execution Index**  
> **Target Project:** InboundCheck (Transactional Email Deliverability & DNS Governance for Shopify & DTC)  
> **Stack:** Next.js 14/15 (App Router, Tailwind CSS, TS), FastAPI (Python 3.12+, Pydantic v2), Supabase (PostgreSQL, RLS), Stripe Billing  
> **Supported Agents:** Antigravity, Claude Code, Cursor, GitHub Copilot, OpenAI Codex  

---

## 1. Executive Mission & System Architecture

**InboundCheck** is an institutional SaaS platform engineered to guarantee inbox delivery for Shopify transactional order receipts, shipping notifications, and marketing flows. It eliminates silent email revenue loss caused by strict 2024 Google/Yahoo mailbox deliverability rules, spam classification, misconfigured DNS records (SPF, DKIM, DMARC, BIMI), and RBL blacklists.

### Technology Blueprint
```
[ Client: Next.js 14 App Router (Obsidian Dark Glassmorphism) ]
                      ↓ (Supabase SSR Cookie Auth & JWT)
[ Edge Middleware: Route Guards (/dashboard/*) ]
                      ↓ (Authorization: Bearer <token>)
[ Backend: FastAPI Engine (FastAPI 0.111+, Python 3.12+) ]
    ├── Security: RateLimiter, Anti-SSRF Guard, Fernet Credential Vault
    ├── DNS Engine: dnspython multi-resolver (SPF, DKIM, DMARC, BIMI)
    ├── Remediation: 1-Click Cloudflare & GoDaddy Zone Manager
    ├── Failover Engine: Twilio WhatsApp / SMS Fallback Dispatch
    ├── AI Lab: Cryptographic Content Optimizer (Neutral Enterprise LLM Adapter)
    └── Monetization: Stripe Subscriptions & Webhook Idempotency
                      ↓
[ Data Layer: Supabase PostgreSQL (Strict RLS: auth.uid() = user_id) ]
```

---

## 2. Core Operating Rules for Autonomous Agents

1. **Skill-First Execution:** Never implement non-trivial changes directly without consulting the relevant skill in `.agent/skills/`.
2. **Zero-Exception Verification Bar:**
   - **Frontend:** Must pass `npm run build` in `frontend/` with 0 TypeScript and Webpack errors.
   - **Backend:** Must pass `py -m pytest tests/` in `backend/` with 100% of tests passing.
3. **Enterprise UI Naming Directive:** Never display raw LLM provider names (e.g., "Kimi", "DeepSeek", "ChatGPT", "GPT-4") in user-facing UI text. Always use institutional terminology:
   - `AI Content Lab & Cryptographic Content Optimizer`
   - `Deliverability Intelligence Engine`
   - `Polymorphic Copy Generator`
4. **Multi-Tenant Security Enforcement:** Never query data using a client-provided `user_id` alone. Always inject the `get_current_user_id` dependency from `app.core.security` to extract identity from the cryptographically verified Supabase JWT.
5. **Anti-SSRF Enforcement:** All outbound domain lookups must validate through `DNSDiagnosticEngine._clean_domain()` and verify that resolved IPs do not collide with restricted subnets (loopback, RFC 1918, carrier NAT, AWS metadata `169.254.169.254`).

---

## 3. Persona Roles & Perspectives

When tackling user tasks or complex workflows, agents should adopt the specialized perspective corresponding to the domain:

| Persona Role | Domain Responsibility | Primary Focus |
|---|---|---|
| **Lead Enterprise Architect** | System structure, data modeling, API boundaries | Modularity, RFC adherence, database normalization, scalable service design. |
| **Obsidian Design System Engineer** | Next.js App Router, Tailwind, Lucide, SVG visuals | Dark glassmorphism, responsive reflow, 60fps animations, zero hydration mismatches. |
| **Cloud Security & Cryptography Specialist** | FastAPI security, Fernet vault, anti-SSRF, JWT, RLS | Zero data loss, credential envelope encryption, fail-closed webhooks, OWASP mitigation. |
| **GEO & Technical Growth Engineer** | Generative Engine Optimization, AEO, Technical SEO | Schema.org JSON-LD, citation fidelity in ChatGPT/Perplexity, Next.js metadata. |
| **Micro-SaaS CRO & Onboarding Strategist** | Funnels, Shopify OAuth, activation velocity, paywalls | < 60s Time-to-Value (TTV), dead-flow elimination, 37.3x GMV protection ROI messaging. |
| **Pre-Flight QA & Release Commander** | Multi-tier test suites, build gates, deployment health | Pre-flight validation, Docker health checks, rollback safety, zero regression policy. |

---

## 4. Master Agent Skill Index (`.agent/skills/`)

All agent skills are stored in `.agent/skills/<skill-name>/SKILL.md`. Agents must invoke the matching skill based on user intent and task requirements:

### Group A: InboundCheck Specialized Enterprise Skills (5 Core Modules)

| Skill Name | Path | Trigger & Purpose |
|---|---|---|
| **`glassmorphic-frontend-architecture`** | [SKILL.md](file:///.agent/skills/glassmorphic-frontend-architecture/SKILL.md) | Next.js 14/15 App Router, dark obsidian palette, glassmorphism, Lucide icons, SVG micro-charts, mobile responsiveness. |
| **`fastapi-cloud-security`** | [SKILL.md](file:///.agent/skills/fastapi-cloud-security/SKILL.md) | Fernet encryption for API keys, anti-SSRF domain defense, strict Pydantic v2 typing, Supabase JWT auth, webhook HMAC signatures. |
| **`seo-geo-aeo-optimization`** | [SKILL.md](file:///.agent/skills/seo-geo-aeo-optimization/SKILL.md) | Technical SEO, Generative Engine Optimization (ChatGPT/Perplexity citation fidelity), JSON-LD schemas, Next.js metadata. |
| **`micro-saas-cro-and-onboarding`** | [SKILL.md](file:///.agent/skills/micro-saas-cro-and-onboarding/SKILL.md) | < 60s activation velocity, dead-flow detection, ObsidianPaywallModal triggers, Shopify OAuth onboarding, 37.3x GMV ROI calculator. |
| **`production-readiness-and-preflight`** | [SKILL.md](file:///.agent/skills/production-readiness-and-preflight/SKILL.md) | 4-tier pre-flight verification gates (npm build, pytest 100%, secrets audit, Docker health checks). |

---

### Group B: Architecture & Design Skills

| Skill Name | Path | Trigger & Purpose |
|---|---|---|
| **`api-and-interface-design`** | [SKILL.md](file:///.agent/skills/api-and-interface-design/SKILL.md) | Designing REST endpoints, Pydantic DTOs, TypeScript interfaces, module boundaries. |
| **`spec-driven-development`** | [SKILL.md](file:///.agent/skills/spec-driven-development/SKILL.md) | Creating comprehensive specifications and PRDs before implementing complex features. |
| **`planning-and-task-breakdown`** | [SKILL.md](file:///.agent/skills/planning-and-task-breakdown/SKILL.md) | Deconstructing large requests into ordered, testable, and bite-sized milestones. |
| **`frontend-ui-engineering`** | [SKILL.md](file:///.agent/skills/frontend-ui-engineering/SKILL.md) | Core UI engineering, WCAG accessibility, component composition, state management. |

---

### Group C: Implementation & Testing Skills

| Skill Name | Path | Trigger & Purpose |
|---|---|---|
| **`incremental-implementation`** | [SKILL.md](file:///.agent/skills/incremental-implementation/SKILL.md) | Implementing multi-file changes in thin, verifiable slices without breaking build. |
| **`test-driven-development`** | [SKILL.md](file:///.agent/skills/test-driven-development/SKILL.md) | Writing automated pytest and frontend unit tests before or alongside code modifications. |
| **`debugging-and-error-recovery`** | [SKILL.md](file:///.agent/skills/debugging-and-error-recovery/SKILL.md) | Systematic root-cause debugging for test breaks, runtime errors, or unexpected behavior. |
| **`browser-testing-with-devtools`** | [SKILL.md](file:///.agent/skills/browser-testing-with-devtools/SKILL.md) | Live browser verification, DOM inspection, console error capture, and network analysis. |

---

### Group D: Security, Performance & Observability Skills

| Skill Name | Path | Trigger & Purpose |
|---|---|---|
| **`security-and-hardening`** | [SKILL.md](file:///.agent/skills/security-and-hardening/SKILL.md) | Threat modeling (STRIDE), input sanitization, CSRF/CORS hardening, OWASP Top 10. |
| **`performance-optimization`** | [SKILL.md](file:///.agent/skills/performance-optimization/SKILL.md) | Core Web Vitals, database index tuning, query optimization, asset payload reduction. |
| **`observability-and-instrumentation`**| [SKILL.md](file:///.agent/skills/observability-and-instrumentation/SKILL.md) | Structured logging, diagnostic tracing, metric counters, deliverability telemetry. |

---

### Group E: Review, Governance & Process Skills

| Skill Name | Path | Trigger & Purpose |
|---|---|---|
| **`code-review-and-quality`** | [SKILL.md](file:///.agent/skills/code-review-and-quality/SKILL.md) | Multi-axis code review covering readability, performance, security, and edge cases. |
| **`code-simplification`** | [SKILL.md](file:///.agent/skills/code-simplification/SKILL.md) | Refactoring and decluttering code without modifying behavior. |
| **`constraint-driven-development`**| [SKILL.md](file:///.agent/skills/constraint-driven-development/SKILL.md) | Enforcing project quality bars, disallowing suppressed lints or weakened test assertions. |
| **`doubt-driven-development`** | [SKILL.md](file:///.agent/skills/doubt-driven-development/SKILL.md) | Adversarial stress-testing of assumptions before committing to irreversible actions. |
| **`documentation-and-adrs`** | [SKILL.md](file:///.agent/skills/documentation-and-adrs/SKILL.md) | Recording Architecture Decision Records (ADRs) and system documentation. |
| **`shipping-and-launch`** | [SKILL.md](file:///.agent/skills/shipping-and-launch/SKILL.md) | Pre-launch checklists, staged rollouts, rollback strategies, and release verification. |
| **`git-workflow-and-versioning`** | [SKILL.md](file:///.agent/skills/git-workflow-and-versioning/SKILL.md) | Clean atomic commits, semantic versioning, branching, and pull request hygiene. |
| **`deprecation-and-migration`** | [SKILL.md](file:///.agent/skills/deprecation-and-migration/SKILL.md) | Safe expand/contract database migrations and API deprecation cycles. |
| **`interview-me`** | [SKILL.md](file:///.agent/skills/interview-me/SKILL.md) | One-question-at-a-time user alignment when requirements are underspecified. |
| **`idea-refine`** | [SKILL.md](file:///.agent/skills/idea-refine/SKILL.md) | Divergent and convergent stress-testing for nascent product or feature concepts. |
| **`source-driven-development`** | [SKILL.md](file:///.agent/skills/source-driven-development/SKILL.md) | Grounding implementation choices strictly in authoritative official documentation. |
| **`context-engineering`** | [SKILL.md](file:///.agent/skills/context-engineering/SKILL.md) | Optimizing agent context windows, rule files, and memory tokens. |
| **`ci-cd-and-automation`** | [SKILL.md](file:///.agent/skills/ci-cd-and-automation/SKILL.md) | GitHub Actions automation, automated CI test gates, and container builds. |
| **`using-agent-skills`** | [SKILL.md](file:///.agent/skills/using-agent-skills/SKILL.md) | Meta-skill for dynamic skill discovery and multi-agent workflow coordination. |

---

## 5. Intent → Skill Dispatch Lifecycle

When an agent receives a prompt, it must follow the internal lifecycle mapping:

```
[ User Prompt Received ]
         │
         ▼
[ 1. Intent Mapping ]
  ├─ New Feature / Architecture  ──► `spec-driven-development` + `api-and-interface-design`
  ├─ Dark UI / Frontend / Chart  ──► `glassmorphic-frontend-architecture` + `frontend-ui-engineering`
  ├─ Security / SSRF / Fernet    ──► `fastapi-cloud-security` + `security-and-hardening`
  ├─ Landing Page / SEO / AEO    ──► `seo-geo-aeo-optimization`
  ├─ Funnel / Paywall / Shopify  ──► `micro-saas-cro-and-onboarding`
  ├─ Bug / Test Failure / 500    ──► `debugging-and-error-recovery` + `test-driven-development`
  └─ Release / Pre-Flight        ──► `production-readiness-and-preflight` + `shipping-and-launch`
         │
         ▼
[ 2. Implementation Execution ]
  └── Follow skill steps strictly using `incremental-implementation`
         │
         ▼
[ 3. Pre-Flight Verification Gate ]
  ├── Backend: py -m pytest tests/ (100% green)
  └── Frontend: npm run build (0 errors)
         │
         ▼
[ 4. Delivery Handoff ]
```

---

## 6. Verification Commands & Execution Guidelines

### Frontend Compilation Check
```powershell
# Always run inside the frontend directory
Set-Location "c:\Users\pc\Desktop\inboundcheck VERSION 1\frontend"
npm run build
```

### Backend Test Suite Check
```powershell
# Always run inside the backend directory
Set-Location "c:\Users\pc\Desktop\inboundcheck VERSION 1\backend"
py -m pytest tests/
```

### Docker Compose Container Health
```powershell
# Run from repository root
Set-Location "c:\Users\pc\Desktop\inboundcheck VERSION 1"
docker-compose up --build -d
curl http://localhost:8000/health
```
