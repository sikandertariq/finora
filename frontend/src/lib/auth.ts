"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  clearStoredAuthSession,
  getStoredAccessToken,
  storeAuthSession,
  subscribeToAuthSession,
  type AuthSession,
} from "@/lib/auth-session";

// Deliberately not the Zustand store: an access token is persistent session
// state (survives a reload via localStorage), not the ephemeral, in-memory-only
// UI state Zustand is reserved for here (see store/workflow-ui-store.ts).
//
// useSyncExternalStore (not useState+useEffect) because localStorage is an
// external store React doesn't know about — this is exactly the primitive
// React ships for that, and it stays SSR-safe without a manual "hydrated" flag.
function getSnapshot(): string | null {
  return getStoredAccessToken();
}

function getServerSnapshot(): string | null {
  return null;
}

export function useAuth() {
  const token = useSyncExternalStore(
    subscribeToAuthSession,
    getSnapshot,
    getServerSnapshot
  );

  const signIn = useCallback((session: AuthSession) => {
    storeAuthSession(session);
  }, []);

  const signOut = useCallback(() => {
    clearStoredAuthSession();
  }, []);

  return { token, signIn, signOut };
}
