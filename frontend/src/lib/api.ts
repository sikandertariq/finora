import type {
  AgentWorkflow,
  ConfirmWorkflowOverrides,
  Invoice,
} from "@/lib/types";
import {
  clearStoredAuthSession,
  getStoredAccessToken,
  getStoredRefreshToken,
  replaceStoredAccessToken,
} from "@/lib/auth-session";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  (process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8000/api");

let refreshInFlight: Promise<string | null> | null = null;

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(
      typeof body === "string"
        ? body
        : (body as { detail?: string })?.detail ?? "Request failed"
    );
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
  hasRetriedAfterRefresh = false
): Promise<T> {
  const headers = new Headers(options.headers);
  const accessToken = token ?? getStoredAccessToken();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (
    res.status === 401 &&
    !hasRetriedAfterRefresh &&
    path !== "/token/" &&
    path !== "/token/refresh/"
  ) {
    const refreshedAccess = await refreshStoredAccessToken();
    if (refreshedAccess) {
      return request(path, options, refreshedAccess, true);
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function refreshStoredAccessToken(): Promise<string | null> {
  const refresh = getStoredRefreshToken();
  if (!refresh) return null;
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE_URL}/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    })
      .then(async (response) => {
        if (!response.ok) return null;
        const { access } = (await response.json()) as { access?: string };
        return access ?? null;
      })
      .then((access) => {
        if (access) replaceStoredAccessToken(access);
        else clearStoredAuthSession();
        return access;
      })
      .catch(() => {
        clearStoredAuthSession();
        return null;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export function login(username: string, password: string) {
  return request<{ access: string; refresh: string }>("/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function getBackendHealth() {
  return request<{ status: "ok" }>("/health/");
}

export function uploadReceipt(file: File, token: string) {
  const formData = new FormData();
  formData.append("file", file);
  return request<AgentWorkflow>(
    "/receipts/",
    { method: "POST", body: formData },
    token
  );
}

export function getWorkflow(id: number, token: string) {
  return request<AgentWorkflow>(`/agent-workflows/${id}/`, {}, token);
}

export function confirmWorkflow(
  id: number,
  overrides: ConfirmWorkflowOverrides,
  token: string
) {
  return request<AgentWorkflow>(
    `/agent-workflows/${id}/confirm/`,
    { method: "POST", body: JSON.stringify(overrides) },
    token
  );
}

export function rejectWorkflow(id: number, token: string) {
  return request<AgentWorkflow>(
    `/agent-workflows/${id}/reject/`,
    { method: "POST", body: JSON.stringify({}) },
    token
  );
}

export function listInvoices(token: string) {
  return request<Invoice[]>("/invoices/", {}, token);
}

export function listWorkflows(
  params: { workflow_type?: string; status?: string },
  token: string
) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v) as [string, string][]
  ).toString();
  return request<AgentWorkflow[]>(
    `/agent-workflows/${query ? `?${query}` : ""}`,
    {},
    token
  );
}
