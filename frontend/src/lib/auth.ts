"use client";

import { useCallback, useSyncExternalStore } from "react";

// Deliberately not the Zustand store: an access token is persistent session
// state (survives a reload via localStorage), not the ephemeral, in-memory-only
// UI state Zustand is reserved for here (see store/workflow-ui-store.ts).
//
// useSyncExternalStore (not useState+useEffect) because localStorage is an
// external store React doesn't know about — this is exactly the primitive
// React ships for that, and it stays SSR-safe without a manual "hydrated" flag.
const STORAGE_KEY = "finora.access_token";
const listeners = new Set<() => void>();

function getSnapshot(): string | null {
  return window.localStorage.getItem(STORAGE_KEY);
}

function getServerSnapshot(): string | null {
  return null;
}

function subscribe(onStoreChange: () => void) {
  listeners.add(onStoreChange);
  return () => listeners.delete(onStoreChange);
}

function writeStoredToken(token: string | null) {
  if (token) window.localStorage.setItem(STORAGE_KEY, token);
  else window.localStorage.removeItem(STORAGE_KEY);
  listeners.forEach((notify) => notify());
}

export function useAuth() {
  const token = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const signIn = useCallback((newToken: string) => {
    writeStoredToken(newToken);
  }, []);

  const signOut = useCallback(() => {
    writeStoredToken(null);
  }, []);

  return { token, signIn, signOut };
}
