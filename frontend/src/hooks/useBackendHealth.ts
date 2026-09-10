"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "@/lib/api";

export type HealthStatus = "healthy" | "operational" | "degraded" | "unavailable" | "checking";

export interface BackendHealthData {
  status: "healthy" | "operational" | "degraded" | "unavailable" | string;
  service: string;
  version: string;
  environment?: string;
  timestamp?: string;
  dependencies?: {
    database: "healthy" | "degraded" | "unavailable" | string;
    scheduler: "healthy" | "degraded" | "unavailable" | string;
  };
}

export function useBackendHealth(pollIntervalMs: number = 60000) {
  const [status, setStatus] = useState<HealthStatus>("checking");
  const [data, setData] = useState<BackendHealthData | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);

  const checkHealth = useCallback(async (retryCount = 0) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    let isTimeout = false;
    // Extended 15-second timeout ceiling to handle cold-starts and network latency
    const timeoutId = setTimeout(() => {
      isTimeout = true;
      controller.abort();
    }, 15000);

    try {
      // Primary health endpoint is /api/v1/health, fallback to /health if 404 or missing
      let response: Response;
      try {
        response = await apiFetch("/api/v1/health", {
          signal: controller.signal,
        });
        if (!response.ok && response.status === 404) {
          response = await apiFetch("/health", {
            signal: controller.signal,
          });
        }
      } catch (err: any) {
        const isSoftAbort =
          err?.name === "AbortError" ||
          (typeof DOMException !== "undefined" && err instanceof DOMException && err.name === "AbortError") ||
          (typeof err?.message === "string" && err.message.toLowerCase().includes("aborted"));

        if (isSoftAbort && !isTimeout) {
          // Do not switch UI to degraded/unavailable on soft aborts
          return;
        }

        // Fallback to root /health probe if /api/v1/health route was unreachable
        response = await apiFetch("/health", {
          signal: controller.signal,
        });
      }

      clearTimeout(timeoutId);

      const result: BackendHealthData = await response.json().catch(() => ({
        status: response.ok ? "healthy" : "unavailable",
        service: "InboundCheck API Engine",
        version: "1.0.0",
      }));

      // Trace logging for state transitions
      console.log("[Health Badge Response]", {
        statusCode: response.status,
        ok: response.ok,
        payload: result,
      });

      if (!isMountedRef.current) return;

      if (!response.ok) {
        setStatus(response.status >= 500 ? "unavailable" : "degraded");
        setData(result);
        return;
      }

      // Contract validation: accept "healthy", "operational", "ok", or "up" as operational
      const rawStatus = (typeof result.status === "string" ? result.status : "").toLowerCase();
      if (rawStatus === "degraded" || rawStatus === "warning") {
        setStatus("degraded");
      } else {
        setStatus("healthy");
      }

      setData(result);
      setLastChecked(new Date());
    } catch (err: any) {
      clearTimeout(timeoutId);

      const isAbort =
        err?.name === "AbortError" ||
        (typeof DOMException !== "undefined" && err instanceof DOMException && err.name === "AbortError") ||
        (typeof err?.message === "string" && err.message.toLowerCase().includes("aborted"));

      if (isAbort && !isTimeout) {
        // Soft abort from StrictMode remount or component unmount: do not set unavailable
        return;
      }

      console.warn("[Health Badge Error] Health probe failed:", err);

      // Attempt clean retry with exponential backoff on transient failure
      if (retryCount < 2 && isMountedRef.current) {
        const delay = Math.pow(2, retryCount) * 1000;
        setTimeout(() => {
          if (isMountedRef.current) {
            void checkHealth(retryCount + 1);
          }
        }, delay);
        return;
      }

      if (isMountedRef.current) {
        setStatus("unavailable");
        setData(null);
      }
    } finally {
      clearTimeout(timeoutId);
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    void checkHealth();

    const interval = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        void checkHealth();
      }
    }, pollIntervalMs);

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void checkHealth();
      }
    };

    window.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", () => void checkHealth());

    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
      window.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", () => void checkHealth());
      // Avoid killing request on initial StrictMode double-mount
      setTimeout(() => {
        if (!isMountedRef.current && abortControllerRef.current) {
          abortControllerRef.current.abort();
        }
      }, 100);
    };
  }, [checkHealth, pollIntervalMs]);

  return {
    status,
    data,
    lastChecked,
    refreshHealth: () => checkHealth(0),
  };
}
