/**
 * InboundCheck Enterprise API Client
 * ===================================
 * Centralized fetch client that injects Supabase session JWT Bearer tokens
 * and resolves URLs against NEXT_PUBLIC_API_URL.
 */

import { supabase } from "@/lib/supabase/client";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

/**
 * Execute an authenticated HTTP request to the InboundCheck backend.
 */
export async function apiFetch(endpoint: string, init: RequestInit = {}): Promise<Response> {
  const rawBase = process.env.NEXT_PUBLIC_API_URL || API_BASE_URL;
  const cleanBase = rawBase.replace(/\/+$/, "");
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const url = endpoint.startsWith("http://") || endpoint.startsWith("https://")
    ? endpoint
    : `${cleanBase}${path}`;

  const requestId = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

  const authHeaders = await getAuthHeaders(init.headers as Record<string, string>);

  return fetch(url, {
    ...init,
    headers: {
      "X-Request-ID": requestId,
      ...authHeaders,
    },
  });
}

