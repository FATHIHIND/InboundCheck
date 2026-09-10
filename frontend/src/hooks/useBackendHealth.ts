"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "@/lib/api";

export type HealthStatus = "healthy" | "degraded" | "unavailable" | "checking";

export interface BackendHealthData {
  status: "healthy" | "degraded" | "unavailable";
  service: string;
  version: string;
  environment?: string;
  timestamp?: string;
  dependencies?: {
    database: "healthy" | "degraded" | "unavailable";
    scheduler: "healthy" | "degraded" | "unavailable";
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
    const timeoutId = setTimeout(() => controller.abort(), 7000);

    try {
      const response = await apiFetch("/api/v1/health", {
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        setStatus("degraded");
        return;
      }

      const result: BackendHealthData = await response.json();
      setData(result);
      setStatus(result.status || "healthy");
      setLastChecked(new Date());
    } catch {
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
