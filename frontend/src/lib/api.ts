import type {
  AgentWorkflow,
  ConfirmWorkflowOverrides,
} from "@/lib/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

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
  token?: string | null
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export function login(username: string, password: string) {
  return request<{ access: string; refresh: string }>("/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
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
