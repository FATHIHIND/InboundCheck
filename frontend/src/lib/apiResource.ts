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
 * Safely extracts human-readable text from any error detail:
 * handles plain strings, Pydantic validation arrays [{loc, msg}], and nested objects.
 * Guarantees '[object Object]' is NEVER rendered.
 */
export function formatApiErrorMessage(detail: unknown, fallback = "An unexpected error occurred"): string {
  if (!detail) return fallback;
  if (typeof detail === "string") {
    const trimmed = detail.trim();
    return trimmed.length > 0 ? trimmed : fallback;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const loc = Array.isArray(item.loc)
            ? item.loc.filter((segment: unknown) => segment !== "body").join(".")
            : "";
          const msg = item.msg || item.message || JSON.stringify(item);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(item);
      })
      .filter(Boolean);
    return messages.length > 0 ? messages.join("; ") : fallback;
  }
  if (typeof detail === "object") {
    const obj = detail as Record<string, any>;
    if (typeof obj.message === "string") return obj.message;
    if (obj.detail) return formatApiErrorMessage(obj.detail, fallback);
    if (typeof obj.error === "string") return obj.error;
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return String(detail);
}

/**
 * Normalizes any caught runtime or HTTP rejection into a structured ApiError.
 */
export function normalizeApiError(cause: unknown, endpoint: string): ApiError {
  if (cause && typeof cause === "object") {
    const obj = cause as Record<string, any>;
    if (typeof obj.message === "string" && typeof obj.retryable === "boolean") {
      return cause as ApiError;
    }
    const isAbort =
      obj.name === "AbortError" ||
      (typeof obj.message === "string" && obj.message.toLowerCase().includes("aborted"));

    if (isAbort) {
      return {
        message: "Request timed out or was interrupted. Retrying connection...",
        retryable: true,
        endpoint,
        code: "REQUEST_ABORTED",
      };
    }

    const rawMessage = obj.detail || obj.message;
    const cleanMessage = formatApiErrorMessage(
      rawMessage,
      "An unexpected error occurred while communicating with the server."
    );

    return {
      message: cleanMessage,
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
