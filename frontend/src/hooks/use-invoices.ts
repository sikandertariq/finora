"use client";

import { useQuery } from "@tanstack/react-query";

import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function useInvoices() {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["invoices"],
    queryFn: () => api.listInvoices(token as string),
    enabled: !!token,
  });
}

// The reminder inbox: needs_review invoice_chaser workflows a human hasn't acted on
// yet. Unlike receipts (one upload -> one known workflow id, tracked in Zustand),
// these appear on their own from the daily scheduler -- so this polls a *list*
// instead of a single id. 10s is slower than the 2s single-workflow poll in
// use-receipts.ts since nothing here is "actively processing" moment-to-moment.
export function usePendingReminders() {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["agent-workflows", { workflow_type: "invoice_chaser", status: "needs_review" }],
    queryFn: () =>
      api.listWorkflows(
        { workflow_type: "invoice_chaser", status: "needs_review" },
        token as string
      ),
    enabled: !!token,
    refetchInterval: 10000,
  });
}
