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
    const sessionPromise = supabase.auth.getSession();
    const timeoutPromise = new Promise<{ data: { session: null } }>((resolve) => {
      setTimeout(() => resolve({ data: { session: null } }), 1500);
    });

    const { data: { session } } = await Promise.race([sessionPromise, timeoutPromise]);
    if (session?.access_token) {
      headers["Authorization"] = `Bearer ${session.access_token}`;
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

