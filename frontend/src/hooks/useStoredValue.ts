"use client";

import { useSyncExternalStore } from "react";

type StorageArea = "local" | "session";

function getArea(area: StorageArea): Storage {
  return area === "session" ? window.sessionStorage : window.localStorage;
}

function subscribeToStorage(onStoreChange: () => void): () => void {
  window.addEventListener("storage", onStoreChange);
  return () => window.removeEventListener("storage", onStoreChange);
}

const getServerValue = (): string | null => null;

/**
 * Hydration-safe read of a Web Storage key via useSyncExternalStore.
 * The server render and hydration pass see `null` (as with the previous
 * read-in-useEffect pattern); the client then renders the stored value.
 * Storage exceptions (private mode, blocked storage) resolve to `null`.
 */
export function useStoredValue(key: string, area: StorageArea = "local"): string | null {
  return useSyncExternalStore(
    subscribeToStorage,
    () => {
      try {
        return getArea(area).getItem(key);
      } catch {
        return null;
      }
    },
    getServerValue
  );
}
