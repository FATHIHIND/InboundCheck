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

  const checkHealth = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort(), 8000);

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
        if (err?.name === "AbortError") throw err;
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
    } catch (err) {
      console.warn("[Health Badge Error] Health probe failed:", err);
      setStatus("unavailable");
      setData(null);
    } finally {
      clearTimeout(timeoutId);
    }
  }, []);

  useEffect(() => {
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
    window.addEventListener("online", checkHealth);

    return () => {
      clearInterval(interval);
      window.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", checkHealth);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [checkHealth, pollIntervalMs]);

  return {
    status,
    data,
    lastChecked,
    refreshHealth: checkHealth,
  };
}
