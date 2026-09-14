/**
 * InboundCheck Enterprise API Client
 * ===================================
 * Centralized fetch client that injects Supabase session JWT Bearer tokens
 * and resolves URLs against NEXT_PUBLIC_API_URL.
 */

import { supabase } from "@/lib/supabase/client";

// Production Railway backend URL fallback
const PROD_RAILWAY_URL = "https://inboundcheck-production.up.railway.app";

/**
 * Dynamically resolves the API base URL.
 * - If NEXT_PUBLIC_API_URL is set and valid, it is prioritized.
 * - When running in production on Vercel (*.vercel.app), falls back to Railway backend instead of localhost.
 * - Defaults to http://localhost:8000 for local development.
 */
export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && envUrl.trim() !== "" && !envUrl.includes("undefined")) {
    // If envUrl is explicitly set to localhost:8000 but the browser is on Vercel, redirect to Railway
    if (typeof window !== "undefined") {
      const hostname = window.location.hostname;
      if ((hostname.includes("vercel.app") || hostname === "inbound-check-theta.vercel.app") && envUrl.includes("localhost")) {
        return PROD_RAILWAY_URL;
      }
    }
    return envUrl;
  }

  // Runtime browser check: If on Vercel or any remote non-localhost domain, fallback to Railway
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    if (hostname.includes("vercel.app") || hostname === "inbound-check-theta.vercel.app" || (hostname !== "localhost" && hostname !== "127.0.0.1")) {
      return PROD_RAILWAY_URL;
    }
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
 * Execute an authenticated HTTP request to the InboundCheck backend.
 */
export async function apiFetch(endpoint: string, init: RequestInit = {}): Promise<Response> {
  const cleanBase = getApiBaseUrl().replace(/\/+$/, "");
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const url = endpoint.startsWith("http://") || endpoint.startsWith("https://")
    ? endpoint
    : `${cleanBase}${path}`;

  const requestId = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

  const authHeaders = await getAuthHeaders(init.headers as Record<string, string>);

  try {
    const res = await fetch(url, {
      ...init,
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
  }
}

