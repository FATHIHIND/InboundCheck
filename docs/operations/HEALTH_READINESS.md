# INBOUNDCHECK — HEALTH & READINESS PROBE SPECIFICATION

**Document Version:** 1.0 (Phase 1 P0 Hardening)  
**Target Environment:** Docker, Kubernetes, Railway, Ingress Load Balancers  
**Standard:** Cloud-Native Probing (RFC & Kubernetes Probe Semantics)

---

## 1. Architectural Distinction: Liveness vs. Readiness

In production environments, a container running a Python process must never report "healthy" if it is incapable of fulfilling user requests due to missing or broken downstream dependencies (such as PostgreSQL database outages). Conversely, a temporary database reconnection glitch must not immediately cause the container orchestrator to brutally terminate and restart the application pod if the event loop itself is healthy.

To prevent cascading container restart loops while protecting user traffic from entering broken pods, InboundCheck separates health probing into two distinct endpoints:

```
                            [ Traffic / Orchestrator ]
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
            [ GET /health ]                         [ GET /ready ]
            (Liveness Probe)                       (Readiness Probe)
                    │                                       │
        Is Python event loop alive?           Are dependencies functional?
        Does NOT probe database.               1. Supabase (Active Query)
                    │                          2. Scheduler / Worker State
                    │                                       │
            HTTP 200 {"status": "alive"}       ┌────────────┴────────────┐
                                               ▼                         ▼
                                          [ All OK ]              [ Failure ]
                                         HTTP 200 OK             HTTP 503 Unavailable
                                     (Route traffic in)        (Drop pod from ingress)
```

---

## 2. Endpoint Specifications

### A. Liveness Probe (`GET /health`)
* **Purpose:** Determine whether the Uvicorn/FastAPI process is running and able to process HTTP requests.
* **Orchestrator Action on Failure:** Restart the container pod after `failureThreshold` attempts.
* **Authentication:** Public / Unauthenticated.
* **Check Scope:**
  * In-process event loop responsiveness.
* **Response Status:**
  * **HTTP 200 OK:**
    ```json
    {
      "status": "alive",
      "service": "InboundCheck API",
      "environment": "production",
      "timestamp": "2026-09-23T15:30:00.000Z"
    }
    ```
* **Security Headers:** Enforces full enterprise security headers (`nosniff`, `DENY`, `max-age=31536000`).

---

### B. Readiness Probe (`GET /ready` & `GET /api/v1/health`)
* **Purpose:** Determine whether the application is fully ready to accept customer traffic.
* **Orchestrator Action on Failure:** Temporarily remove the pod from ingress routing pools until the check recovers.
* **Authentication:** Public / Unauthenticated.
* **Check Scope:**
  1. **Database Connectivity:**
     * In `production`: Executes a live probe (`select("id").limit(1)`) against Supabase. Fails closed if disconnected.
     * In `development` / `test`: Verifies client connection or authorized development mock.
  2. **Worker / Scheduler State:**
     * If `RUN_IN_PROCESS_SCHEDULER=true`: Asserts that `background_auditor.is_running` is active.
     * If `RUN_IN_PROCESS_SCHEDULER=false`: Acknowledges scheduler runs as an external dedicated daemon.
* **Response Status:**
  * **HTTP 200 OK (Ready):**
    ```json
    {
      "status": "ready",
      "service": "InboundCheck API",
      "environment": "production",
      "timestamp": "2026-09-23T15:30:00.000Z",
      "dependencies": {
        "database": "healthy",
        "scheduler": "healthy"
      }
    }
    ```
  * **HTTP 503 Service Unavailable (Database Outage):**
    ```json
    {
      "status": "unavailable",
      "service": "InboundCheck API",
      "environment": "production",
      "timestamp": "2026-09-23T15:30:00.000Z",
      "dependencies": {
        "database": "unhealthy",
        "scheduler": "healthy"
      },
      "reason": "Database connection probe failed"
    }
    ```

---

## 3. Production Configuration Safeguards

* **Zero Unconditional "Healthy" Logic:** The legacy defect `healthy if X else healthy` is permanently purged.
* **No Cascading Timeouts:** The database probe enforces a strict 2.0-second timeout to prevent readiness requests from piling up and exhausting the server worker pool during network partitions.
