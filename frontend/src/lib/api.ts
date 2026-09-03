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
 */
export async function getAuthHeaders(customHeaders: HeadersInit = {}): Promise<HeadersInit> {
  const headers: Record<string, string> = {};

  try {
    const { data: { session } } = await supabase.auth.getSession();
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
  const base = process.env.NEXT_PUBLIC_API_URL || API_BASE_URL;
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const url = endpoint.startsWith("http://") || endpoint.startsWith("https://")
    ? endpoint
    : `${base}${path}`;

  const headers = await getAuthHeaders(init.headers as Record<string, string>);

  return fetch(url, {
    ...init,
    headers,
  });
}
