/**
 * InboundCheck Enterprise API Client
 * ===================================
 * Centralized fetch client that injects Supabase session JWT Bearer tokens
 * and resolves URLs against NEXT_PUBLIC_API_URL.
 */

import { supabase } from "./supabase/client";

// Primary branded production API domain
const PROD_CUSTOM_API_URL = "https://api.inboundcheck.com";
// Production Railway backend URL fallback
const PROD_RAILWAY_URL = "https://inboundcheck-production.up.railway.app";
// Exact canonical production Vercel hostname
const PROD_VERCEL_CANONICAL = "inbound-check-theta.vercel.app";

/**
 * Dynamically resolves the API base URL.
 * - Production custom domains (inboundcheck.com, www.inboundcheck.com) and canonical Vercel
 *   production domain (inbound-check-theta.vercel.app) strictly route to https://api.inboundcheck.com.
 * - Localhost and loopback (127.0.0.1) route to explicit valid development override, otherwise http://localhost:8000.
 * - Vercel Preview deployments (*.vercel.app or NEXT_PUBLIC_VERCEL_ENV === "preview"):
 *   - If an explicit valid remote staging URL is configured (NEXT_PUBLIC_API_URL), routes to that staging URL.
 *   - If missing, empty, invalid, or localhost: fails safely and returns "" to prevent silent fallback to Production.
 */
export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  const hasValidEnv = Boolean(envUrl && envUrl.trim() !== "" && !envUrl.includes("undefined"));
  const vercelEnv = process.env.NEXT_PUBLIC_VERCEL_ENV || process.env.VERCEL_ENV;
  const isPreviewEnv = vercelEnv === "preview";

  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;

    // 1. Production custom apex and www domains always route to branded production API
    if (hostname === "inboundcheck.com" || hostname === "www.inboundcheck.com") {
      return PROD_CUSTOM_API_URL;
    }

    // 2. Exact canonical production Vercel hostname routes to branded production API
    if (hostname === PROD_VERCEL_CANONICAL) {
      return PROD_CUSTOM_API_URL;
    }

    // 3. Localhost and loopback development
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      return hasValidEnv ? envUrl!.replace(/\/+$/, "") : "http://localhost:8000";
    }

    // 4. Preview deployments (*.vercel.app or explicit preview environment)
    const isPreviewHostname = (hostname.endsWith(".vercel.app") || hostname.includes("vercel.app")) && hostname !== PROD_VERCEL_CANONICAL;
    if (isPreviewEnv || isPreviewHostname) {
      if (hasValidEnv && !envUrl!.includes("localhost") && !envUrl!.includes("127.0.0.1")) {
        return envUrl!.replace(/\/+$/, "");
      }
      // Failsafe: Return empty string so preview deployments fail closed without targeting production
      return "";
    }

    // 5. Other custom environments (e.g. custom staging domain with explicit backend)
    if (hasValidEnv && !envUrl!.includes("localhost") && !envUrl!.includes("127.0.0.1")) {
      return envUrl!.replace(/\/+$/, "");
    }
    return "";
  }

  // Server-side rendering (SSR) / Node environment
  if (hasValidEnv) {
    if (!envUrl!.includes("localhost") || !isPreviewEnv) {
      return envUrl!.replace(/\/+$/, "");
    }
  }
  if (isPreviewEnv) {
    return "";
  }
  if (vercelEnv === "production") {
    return PROD_CUSTOM_API_URL;
  }
  return "http://localhost:8000";
}

export const API_BASE_URL = getApiBaseUrl();

/**
 * Retrieve the active Supabase JWT and format Authorization Bearer headers.
 * Employs a defensive timeout safeguard so auth queries never lock up requests indefinitely.
 */
export async function getAuthHeaders(customHeaders: HeadersInit = {}): Promise<HeadersInit> {
  const headers: Record<string, string> = {};

  try {
    let token: string | undefined;

    // 1. Primary: Retrieve session via Supabase JS client
    try {
      const sessionPromise = supabase.auth.getSession();
      const timeoutPromise = new Promise<{ data: { session: null } }>((resolve) => {
        setTimeout(() => resolve({ data: { session: null } }), 3000);
      });

      const { data: { session } } = await Promise.race([sessionPromise, timeoutPromise]);
      if (session?.access_token) {
        token = session.access_token;
      }
    } catch (e) {
      console.warn("Supabase getSession error:", e);
    }

    // 2. Secondary: Fallback to direct localStorage inspection for Supabase auth tokens
    if (!token && typeof window !== "undefined" && window.localStorage) {
      try {
        for (let i = 0; i < localStorage.length; i++) {
          const key = localStorage.key(i);
          if (key && (key.startsWith("sb-") || key.includes("supabase")) && key.endsWith("-auth-token")) {
            const raw = localStorage.getItem(key);
            if (raw) {
              const parsed = JSON.parse(raw);
              if (parsed?.access_token) {
                token = parsed.access_token;
                break;
              }
            }
          }
        }
      } catch {
        // Suppress localStorage parsing errors
      }
    }

    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  } catch (err) {
    console.warn("Failed to retrieve Supabase session JWT:", err);
  }

  return {
    ...headers,
    ...customHeaders,
  };
}

export interface ApiFetchErrorDetails {
  status: number;
  statusText: string;
  url: string;
  body: any;
  headers: Record<string, string>;
}

/**
 * Default request timeout ceiling (15,000ms / 15 seconds) to prevent unbounded hanging HTTP requests.
 */
export const DEFAULT_REQUEST_TIMEOUT_MS = 15000;

export interface ApiRequestInit extends RequestInit {
  timeoutMs?: number;
}

/**
 * Execute an authenticated HTTP request to the InboundCheck backend.
 * Enforces a bounded 15-second default request timeout while safely preserving
 * and honoring caller-provided AbortSignal cancellation and avoiding resource leaks.
 */
export async function apiFetch(endpoint: string, init: ApiRequestInit = {}): Promise<Response> {
  const isAbsoluteUrl = endpoint.startsWith("http://") || endpoint.startsWith("https://");
  const baseUrl = getApiBaseUrl();
  const cleanBase = baseUrl ? baseUrl.replace(/\/+$/, "") : "";

  // Fail-safe guard: If base URL is unconfigured (e.g. unconfigured preview deployment),
  // fail closed immediately without calling fetch, targeting Production API, or sending
  // relative requests to the Vercel frontend origin.
  if (!cleanBase && !isAbsoluteUrl) {
    const errorMsg =
      "InboundCheck API base URL is unconfigured for this environment. " +
      "Vercel Preview deployments require an explicit NEXT_PUBLIC_API_URL staging backend.";
    const configError = new Error(errorMsg);
    configError.name = "ConfigurationError";

    if (typeof console !== "undefined" && console.error) {
      console.error("[API_CONFIGURATION_ERROR]", {
        endpoint,
        message: errorMsg,
      });
    }

    throw configError;
  }

  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const url = isAbsoluteUrl ? endpoint : `${cleanBase}${path}`;

  const requestId = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

  const authHeaders = await getAuthHeaders(init.headers as Record<string, string>);

  const { timeoutMs: customTimeout, ...fetchInit } = init;
  const timeoutMs = typeof customTimeout === "number" && customTimeout > 0
    ? customTimeout
    : DEFAULT_REQUEST_TIMEOUT_MS;

  const controller = new AbortController();
  const callerSignal = init.signal;

  let onCallerAbort: (() => void) | null = null;
  if (callerSignal) {
    if (callerSignal.aborted) {
      if (callerSignal.reason !== undefined) {
        controller.abort(callerSignal.reason);
      } else {
        controller.abort();
      }
    } else {
      onCallerAbort = () => {
        if (callerSignal.reason !== undefined) {
          controller.abort(callerSignal.reason);
        } else {
          controller.abort();
        }
      };
      callerSignal.addEventListener("abort", onCallerAbort, { once: true });
    }
  }

  const timeoutId = setTimeout(() => {
    const timeoutErr = typeof DOMException !== "undefined"
      ? new DOMException(`Request timed out after ${timeoutMs}ms`, "TimeoutError")
      : Object.assign(new Error(`Request timed out after ${timeoutMs}ms`), { name: "TimeoutError" });
    controller.abort(timeoutErr);
  }, timeoutMs);

  try {
    const res = await fetch(url, {
      ...fetchInit,
      signal: controller.signal,
      headers: {
        "X-Request-ID": requestId,
        ...authHeaders,
      },
    });
    return res;
  } catch (networkErr: any) {
    console.error("[API_NETWORK_ERROR]", {
      url,
      method: init.method || "GET",
      message: networkErr?.message || "Network request failed",
      error: networkErr,
    });
    throw networkErr;
  } finally {
    clearTimeout(timeoutId);
    if (callerSignal && onCallerAbort) {
      callerSignal.removeEventListener("abort", onCallerAbort);
    }
  }
}

