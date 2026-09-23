# INBOUNDCHECK — PHASE 1 BASELINE AUDIT REPORT

**Date:** 2026-09-23  
**Target Environment:** Local Workspace / Staging Baseline  
**Branch:** `main`  
**Git Status:** Clean (`nothing to commit, working tree clean`)

---

## 1. Backend Test Suite Baseline

* **Command:** `py -m pytest tests/` in `c:\Users\pc\Desktop\inboundcheck VERSION 1\backend`
* **Test Platform:** Windows (Python 3.14.3, pytest-9.0.3, pluggy-1.6.0)
* **Results:**
  * **Passed:** 130 of 130 tests (100% pass rate)
  * **Failed:** 0 tests
  * **Duration:** 77.82s
  * **Warnings:** 133 warnings (primarily `datetime.datetime.utcnow()` deprecation warnings scheduled for removal in Python 3.15, plus minor Supabase SDK timeout/verify parameter deprecations)
* **Status:** GREEN / VERIFIED

---

## 2. Frontend Build Baseline

* **Command:** `npm run build` in `c:\Users\pc\Desktop\inboundcheck VERSION 1\frontend`
* **Build Engine:** Next.js 14.2.4 (App Router)
* **Results:**
  * **Compilation:** Successfully compiled
  * **Routes:** 25 of 25 routes generated cleanly (Static & Dynamic SSR)
  * **Errors:** 0 errors
  * **Warnings:** 10 ESLint warnings (`react-hooks/exhaustive-deps` in 3D canvas animation components: `StippleCanvas.tsx`, `InboxWitnessCanvas.tsx`, `ParticleStreamCanvas.tsx`, `RadarBeamCanvas.tsx`, `RblTopology3DCanvas.tsx`, `ScoreGauge3DCanvas.tsx`, `Sparkline3DCanvas.tsx`, `Hero3DCanvas.tsx`, `RadarPulseCanvas.tsx`, `WireframeGridCanvas.tsx`)
* **Status:** GREEN / VERIFIED

---

## 3. Git Status & Working Tree

```text
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```
* **Existing Uncommitted Changes:** 0 files modified or staged.
* **Preservation Guarantee:** Clean working state established.

---

## 4. Known Issues at Baseline

1. **Service-Role Key Bypasses RLS:** Backend uses service-role key for PostgREST calls; tenant scoping relies solely on query construction.
2. **False-Positive Health Check:** `/health` catches exceptions and reassigns `db_status = "healthy"`.
3. **In-Memory Persistence Fallbacks:** `SupabaseService` has in-memory dictionary fallbacks active in all environments.
4. **Permissive Profile Insert:** Migration RLS policy permits `WITH CHECK (auth.uid() = id OR auth.uid() IS NULL)`.
5. **Trial Expiration Fail-Open:** Null or missing `trial_ends_at` defaults to `return False` in `tier_guards.py`.
6. **Frontend Unit Tests:** 0 automated unit tests configured in `frontend/`.

---

## 5. Environment Assumptions

* `ENVIRONMENT`: `development` / `production`
* `SUPABASE_URL`: Connected
* `SUPABASE_SERVICE_ROLE_KEY`: Configured
* Python 3.14.3 with `pytest`, `fastapi`, `pydantic` v2, `dnspython`
* Node.js v20+ with Next.js 14.2.4
