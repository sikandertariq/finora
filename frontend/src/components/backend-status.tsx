"use client";

import { useQuery } from "@tanstack/react-query";

import { getBackendHealth } from "@/lib/api";

export function BackendStatus() {
  const health = useQuery({
    queryKey: ["backend-health"],
    queryFn: getBackendHealth,
    retry: false,
    refetchInterval: 30_000,
  });

  if (!health.isError) return null;

  return (
    <p
      className="w-full max-w-md rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"
      role="status"
    >
      The demo backend is currently offline. It is intentionally stopped when not
      in use; please try again shortly.
    </p>
  );
}
