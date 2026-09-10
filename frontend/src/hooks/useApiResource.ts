"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "@/lib/api";
import { ApiError, ApiResource, normalizeApiError } from "@/lib/apiResource";

interface UseApiResourceOptions<T> {
  endpoint: string;
  parse?: (response: Response) => Promise<T>;
  isEmpty?: (data: T) => boolean;
  autoLoad?: boolean;
}

/**
 * Enterprise hook for managing deterministic API resource states.
 * Guarantees that empty data resolves to 'empty' and network/server failures
 * resolve to 'error' with technical reference correlation.
 *
 * Employs ref-stabilization on parse and isEmpty to prevent infinite re-render loops
 * caused by inline callback props, and implements defensive request timeouts.
 */
export function useApiResource<T>({
  endpoint,
  parse = async (res) => res.json(),
  isEmpty = (data) => Array.isArray(data) && data.length === 0,
  autoLoad = true,
}: UseApiResourceOptions<T>) {
  const [resource, setResource] = useState<ApiResource<T>>({
    state: "loading",
    data: null,
    error: null,
  });

  // Stabilize parse and isEmpty references to prevent re-triggering load on every render
  const parseRef = useRef(parse);
  parseRef.current = parse;

  const isEmptyRef = useRef(isEmpty);
  isEmptyRef.current = isEmpty;

  const abortControllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    // Abort previous in-flight request if any
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    setResource((prev) => (prev.state === "loading" ? prev : { state: "loading", data: null, error: null }));

    try {
      const response = await apiFetch(endpoint, {
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        const apiError: ApiError = {
          message: body.detail || body.message || `Request failed with status ${response.status}`,
          status: response.status,
          referenceId: body.error_reference || body.reference_id,
          retryable: response.status >= 500 || response.status === 429,
          endpoint,
          code: `HTTP_${response.status}`,
        };
        throw apiError;
      }

      const parsedData = await parseRef.current(response);
      const isDataEmpty = isEmptyRef.current(parsedData);

      console.log(`[ApiResource Response] ${endpoint}:`, {
        status: response.status,
        isEmpty: isDataEmpty,
        data: parsedData,
      });

      setResource({
        state: isDataEmpty ? "empty" : "ready",
        data: parsedData,
        error: null,
      });
    } catch (cause: any) {
      clearTimeout(timeoutId);
      if (cause?.name === "AbortError" && abortControllerRef.current !== controller) {
        // Ignored aborted request from subsequent trigger
        return;
      }

      const error = normalizeApiError(cause, endpoint);
      console.warn(`[ApiResource Error] ${endpoint}:`, error);

      setResource({
        state: "error",
        data: null,
        error,
      });
    }
  }, [endpoint]);

  useEffect(() => {
    if (autoLoad) {
      void load();
    }

    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [autoLoad, load]);

  return {
    resource,
    retry: load,
    reload: load,
  };
}
