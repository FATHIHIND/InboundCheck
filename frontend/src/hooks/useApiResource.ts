"use client";

import { useState, useEffect, useCallback } from "react";
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

  const load = useCallback(async () => {
    setResource({ state: "loading", data: null, error: null });

    try {
      const response = await apiFetch(endpoint);

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

      const parsedData = await parse(response);
      const isDataEmpty = isEmpty(parsedData);

      setResource({
        state: isDataEmpty ? "empty" : "ready",
        data: parsedData,
        error: null,
      });
    } catch (cause) {
      const error = normalizeApiError(cause, endpoint);
      setResource({
        state: "error",
        data: null,
        error,
      });
    }
  }, [endpoint, parse, isEmpty]);

  useEffect(() => {
    if (autoLoad) {
      void load();
    }
  }, [autoLoad, load]);

  return {
    resource,
    retry: load,
    reload: load,
  };
}
