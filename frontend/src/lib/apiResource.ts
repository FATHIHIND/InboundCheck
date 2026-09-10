/**
 * Operational Data-State Contract & Normalized Error Typing
 * =========================================================
 * Enforces strict 4-state rendering for all backend resources:
 * loading -> ready -> empty -> error
 */

export interface ApiError {
  message: string;
  status?: number;
  referenceId?: string;
  retryable: boolean;
  endpoint: string;
  code?: string;
}

export type ApiResource<T> =
  | { state: "loading"; data: null; error: null }
  | { state: "ready"; data: T; error: null }
  | { state: "empty"; data: T; error: null }
  | { state: "error"; data: null; error: ApiError };

/**
 * Normalizes any caught runtime or HTTP rejection into a structured ApiError.
 */
export function normalizeApiError(cause: unknown, endpoint: string): ApiError {
  if (cause && typeof cause === "object") {
    const obj = cause as Record<string, any>;
    if (typeof obj.message === "string" && typeof obj.retryable === "boolean") {
      return cause as ApiError;
    }
    return {
      message: obj.detail || obj.message || "An unexpected error occurred while communicating with the server.",
      status: typeof obj.status === "number" ? obj.status : undefined,
      referenceId: obj.referenceId || obj.error_reference || obj.reference_id,
      retryable: obj.retryable ?? (typeof obj.status === "number" ? obj.status >= 500 || obj.status === 429 : true),
      endpoint,
      code: obj.code || (typeof obj.status === "number" ? `HTTP_${obj.status}` : "NETWORK_ERROR"),
    };
  }

  if (typeof cause === "string") {
    return {
      message: cause,
      retryable: true,
      endpoint,
      code: "UNKNOWN_EXCEPTION",
    };
  }

  return {
    message: "Failed to connect to the backend server. Please verify your network connection.",
    retryable: true,
    endpoint,
    code: "FETCH_FAILED",
  };
}
