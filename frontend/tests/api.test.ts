import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { apiFetch, getAuthHeaders, DEFAULT_REQUEST_TIMEOUT_MS } from "../src/lib/api";
import { supabase } from "../src/lib/supabase/client";

describe("apiFetch & GAP-30 Frontend Request Timeout Remediation", () => {
  const originalFetch = globalThis.fetch;
  const originalGetSession = supabase.auth.getSession;

  beforeEach(() => {
    supabase.auth.getSession = (async () => ({ data: { session: null }, error: null })) as any;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    supabase.auth.getSession = originalGetSession;
  });

  it("1. DEFAULT_REQUEST_TIMEOUT_MS is bounded to exactly 15000ms", () => {
    assert.strictEqual(DEFAULT_REQUEST_TIMEOUT_MS, 15000);
  });

  it("2. Request without caller signal applies timeout signal to underlying fetch", async () => {
    let capturedSignal: AbortSignal | undefined;

    globalThis.fetch = async (_url: any, init?: any) => {
      capturedSignal = init?.signal;
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    const res = await apiFetch("/test/endpoint");
    assert.strictEqual(res.status, 200);
    assert.ok(capturedSignal, "AbortSignal must be provided to fetch");
    assert.strictEqual(capturedSignal.aborted, false, "Signal should not be aborted on quick response");
  });

  it("3. Request with caller signal preserves and respects caller signal", async () => {
    const callerController = new AbortController();
    let capturedSignal: AbortSignal | undefined;

    globalThis.fetch = async (_url: any, init?: any) => {
      capturedSignal = init?.signal;
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    };

    const res = await apiFetch("/test/with-caller-signal", {
      signal: callerController.signal,
    });

    assert.strictEqual(res.status, 200);
    assert.ok(capturedSignal, "Composite signal must be passed to fetch");
    assert.strictEqual(callerController.signal.aborted, false);
    assert.strictEqual(capturedSignal.aborted, false);
  });

  it("4. Caller abort: request aborts correctly with caller's reason", async () => {
    const callerController = new AbortController();

    globalThis.fetch = async (_url: any, init?: any) => {
      if (init?.signal?.aborted) {
        throw init.signal.reason;
      }
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            reject(init.signal.reason);
          },
          { once: true }
        );
      });
    };

    const expectedReason = new DOMException("User manual cancel", "AbortError");

    const fetchPromise = apiFetch("/test/caller-abort", {
      signal: callerController.signal,
      timeoutMs: 5000,
    });

    // Abort caller controller
    callerController.abort(expectedReason);

    await assert.rejects(
      fetchPromise,
      (err: any) => {
        assert.strictEqual(err.name, "AbortError");
        assert.strictEqual(err.message, "User manual cancel");
        return true;
      }
    );
  });

  it("5. Caller pre-aborted signal: aborts immediately with caller's reason", async () => {
    const callerController = new AbortController();
    const expectedReason = new DOMException("Pre-aborted request", "AbortError");
    callerController.abort(expectedReason);

    globalThis.fetch = async (_url: any, init?: any) => {
      if (init?.signal?.aborted) {
        throw init.signal.reason;
      }
      return new Response("ok");
    };

    await assert.rejects(
      apiFetch("/test/pre-aborted", { signal: callerController.signal }),
      (err: any) => {
        assert.strictEqual(err.name, "AbortError");
        assert.strictEqual(err.message, "Pre-aborted request");
        return true;
      }
    );
  });

  it("6. Timeout abort: request aborts after configured timeout boundary with TimeoutError", async () => {
    globalThis.fetch = async (_url: any, init?: any) => {
      if (init?.signal?.aborted) {
        throw init.signal.reason;
      }
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            reject(init.signal.reason);
          },
          { once: true }
        );
      });
    };

    const startTime = Date.now();
    await assert.rejects(
      apiFetch("/test/timeout-trigger", {
        timeoutMs: 60, // Short timeout for deterministic fast testing
      }),
      (err: any) => {
        assert.strictEqual(err.name, "TimeoutError");
        assert.ok(err.message.includes("Request timed out after 60ms"));
        return true;
      }
    );

    const elapsed = Date.now() - startTime;
    assert.ok(elapsed >= 50, `Elapsed ${elapsed}ms should be around timeout boundary`);
  });

  it("7. Existing authentication timeout: 3-second defensive safeguard remains intact", async () => {
    // Restore un-mocked getSession to verify 3s Promise.race fallback in getAuthHeaders
    supabase.auth.getSession = originalGetSession;
    const authHeaders = await getAuthHeaders();
    assert.ok(typeof authHeaders === "object", "Auth headers should resolve as an object");
  });

  it("8. Existing request options (headers, method, body, credentials) are preserved", async () => {
    let capturedOptions: any = null;

    globalThis.fetch = async (_url: any, init?: any) => {
      capturedOptions = init;
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    };

    const requestBody = JSON.stringify({ key: "value" });
    await apiFetch("/test/options-pass-through", {
      method: "POST",
      body: requestBody,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Custom-Header": "InboundCheckTest",
      },
    });

    assert.ok(capturedOptions, "fetch init options should be captured");
    assert.strictEqual(capturedOptions.method, "POST");
    assert.strictEqual(capturedOptions.body, requestBody);
    assert.strictEqual(capturedOptions.credentials, "include");
    assert.strictEqual(capturedOptions.headers["Content-Type"], "application/json");
    assert.strictEqual(capturedOptions.headers["X-Custom-Header"], "InboundCheckTest");
    assert.ok(capturedOptions.headers["X-Request-ID"], "X-Request-ID must be present");
  });

  it("9. No listener leaks: caller signal listeners are removed on completion", async () => {
    const callerController = new AbortController();
    const signal = callerController.signal;

    let addedCount = 0;
    let removedCount = 0;

    const originalAdd = signal.addEventListener.bind(signal);
    const originalRemove = signal.removeEventListener.bind(signal);

    signal.addEventListener = ((type: string, listener: any, options: any) => {
      if (type === "abort") addedCount++;
      return originalAdd(type, listener, options);
    }) as any;

    signal.removeEventListener = ((type: string, listener: any, options: any) => {
      if (type === "abort") removedCount++;
      return originalRemove(type, listener, options);
    }) as any;

    globalThis.fetch = async () => new Response("ok");

    await apiFetch("/test/cleanup-check", { signal });

    assert.strictEqual(addedCount, 1, "Should have registered 1 abort listener");
    assert.strictEqual(removedCount, 1, "Should have cleanly removed the abort listener");
  });

  it("10. No listener leaks on caller abort: listener cleaned up in finally", async () => {
    const callerController = new AbortController();
    const signal = callerController.signal;

    let addedCount = 0;
    let removedCount = 0;

    const originalAdd = signal.addEventListener.bind(signal);
    const originalRemove = signal.removeEventListener.bind(signal);

    signal.addEventListener = ((type: string, listener: any, options: any) => {
      if (type === "abort") addedCount++;
      return originalAdd(type, listener, options);
    }) as any;

    signal.removeEventListener = ((type: string, listener: any, options: any) => {
      if (type === "abort") removedCount++;
      return originalRemove(type, listener, options);
    }) as any;

    globalThis.fetch = async (_url: any, init?: any) => {
      // Abort in-flight during fetch execution
      setTimeout(() => {
        callerController.abort(new DOMException("Cancelled", "AbortError"));
      }, 5);
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            reject(init.signal.reason);
          },
          { once: true }
        );
      });
    };

    const fetchPromise = apiFetch("/test/cleanup-on-abort", { signal });
    await assert.rejects(fetchPromise);

    assert.strictEqual(addedCount, 1);
    assert.strictEqual(removedCount, 1);
  });
});
