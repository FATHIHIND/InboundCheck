"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "@/lib/api";
import { ApiError, ApiResource, normalizeApiError } from "@/lib/apiResource";

interface UseApiResourceOptions<T> {
  endpoint: string;
  parse?: (response: Response) => Promise<T>;
  isEmpty?: (data: T) => boolean;
  autoLoad?: boolean;
  maxRetries?: number;
}

/**
 * Enterprise hook for managing deterministic API resource states.
 * Guarantees that empty data resolves to 'empty' and network/server failures
 * resolve to 'error' with technical reference correlation.
 *
 * Employs ref-stabilization on parse and isEmpty to prevent infinite re-render loops,
 * an extended 15-second request timeout ceiling for cold-start latency, StrictMode double-mount protection,
 * and graceful exponential backoff on soft aborts and network interrupts.
 */
export function useApiResource<T>({
  endpoint,
  parse = async (res) => res.json(),
  isEmpty = (data) => Array.isArray(data) && data.length === 0,
  autoLoad = true,
  maxRetries = 2,
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
  const isMountedRef = useRef(true);
  const retryCountRef = useRef(0);

  const load = useCallback(async (retryAttempt = 0) => {
    // Abort previous in-flight request if manually re-triggered
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let isTimeout = false;
    // 15-second timeout ceiling to accommodate cold-starts and remote database queries
    const timeoutId = setTimeout(() => {
      isTimeout = true;
      controller.abort();
    }, 15000);

    // Only transition to loading if this is the initial trigger, not an internal retry
    if (retryAttempt === 0) {
      setResource((prev) => (prev.state === "loading" ? prev : { state: "loading", data: null, error: null }));
    }

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

      // Reset retry count on successful response
      retryCountRef.current = 0;

      if (isMountedRef.current) {
        setResource({
          state: isDataEmpty ? "empty" : "ready",
          data: parsedData,
          error: null,
        });
      }
    } catch (cause: any) {
      clearTimeout(timeoutId);

      const isAbort =
        cause?.name === "AbortError" ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException && cause.name === "AbortError") ||
        (typeof cause?.message === "string" && cause.message.toLowerCase().includes("aborted"));

      // If soft abort (StrictMode cycle, unmount, or navigation) and not a true timeout, return cleanly
      if (isAbort && !isTimeout && !isMountedRef.current) {
        return;
      }

      // If aborted due to timeout or network glitch and retries remain, retry with exponential backoff
      if ((isAbort || cause?.retryable) && retryAttempt < maxRetries && isMountedRef.current) {
        const backoffDelay = Math.pow(2, retryAttempt) * 1000;
        console.warn(`[ApiResource Retry] Retrying ${endpoint} (attempt ${retryAttempt + 1}/${maxRetries}) in ${backoffDelay}ms...`);
        setTimeout(() => {
          if (isMountedRef.current) {
            void load(retryAttempt + 1);
          }
        }, backoffDelay);
        return;
      }

      // If soft abort without timeout occurred while mounted, do not switch UI to fatal error
      if (isAbort && !isTimeout) {
        return;
      }

      const error = normalizeApiError(cause, endpoint);
      console.warn(`[ApiResource Error] ${endpoint}:`, error);

      if (isMountedRef.current) {
        setResource({
          state: "error",
          data: null,
          error,
        });
      }
    }
  }, [endpoint, maxRetries]);

  useEffect(() => {
    isMountedRef.current = true;

    if (autoLoad) {
      void load();
    }

    return () => {
      isMountedRef.current = false;
      // Protect against StrictMode double-mount: debounce abort so immediate remount keeps request alive
      setTimeout(() => {
        if (!isMountedRef.current && abortControllerRef.current) {
          abortControllerRef.current.abort();
        }
      }, 100);
    };
  }, [autoLoad, load]);

  return {
    resource,
    retry: () => load(0),
    reload: () => load(0),
  };
}
