export type AuthSession = {
  access: string;
  refresh: string;
};

const ACCESS_STORAGE_KEY = "finora.access_token";
const REFRESH_STORAGE_KEY = "finora.refresh_token";
const listeners = new Set<() => void>();

function storage(): Storage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

function notify() {
  listeners.forEach((listener) => listener());
}

export function subscribeToAuthSession(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getStoredAccessToken(): string | null {
  return storage()?.getItem(ACCESS_STORAGE_KEY) ?? null;
}

export function getStoredRefreshToken(): string | null {
  return storage()?.getItem(REFRESH_STORAGE_KEY) ?? null;
}

export function storeAuthSession(session: AuthSession) {
  const localStorage = storage();
  if (!localStorage) return;
  localStorage.setItem(ACCESS_STORAGE_KEY, session.access);
  localStorage.setItem(REFRESH_STORAGE_KEY, session.refresh);
  notify();
}

export function replaceStoredAccessToken(access: string) {
  const localStorage = storage();
  if (!localStorage) return;
  localStorage.setItem(ACCESS_STORAGE_KEY, access);
  notify();
}

export function clearStoredAuthSession() {
  const localStorage = storage();
  if (!localStorage) return;
  localStorage.removeItem(ACCESS_STORAGE_KEY);
  localStorage.removeItem(REFRESH_STORAGE_KEY);
  notify();
}
