"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AgentWorkflow, ConfirmWorkflowOverrides } from "@/lib/types";

const ACTIVELY_PROCESSING: AgentWorkflow["status"][] = ["pending", "running"];

export function useUploadReceipt() {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => {
      if (!token) throw new Error("Not signed in.");
      return api.uploadReceipt(file, token);
    },
    onSuccess: (workflow) => {
      queryClient.setQueryData(["agent-workflow", workflow.id], workflow);
    },
  });
}

export function useWorkflow(id: number | null) {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["agent-workflow", id],
    queryFn: () => api.getWorkflow(id as number, token as string),
    enabled: id !== null && !!token,
    // Keep polling while the agent is still working; stop once a human needs
    // to act (or already has) -- no point re-fetching a settled workflow.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ACTIVELY_PROCESSING.includes(status) ? 2000 : false;
    },
  });
}

export function useConfirmWorkflow(id: number) {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (overrides: ConfirmWorkflowOverrides) =>
      api.confirmWorkflow(id, overrides, token as string),
    onSuccess: (workflow) => {
      queryClient.setQueryData(["agent-workflow", id], workflow);
      queryClient.invalidateQueries({ queryKey: ["agent-workflows"] });
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
    },
  });
}

export function useRejectWorkflow(id: number) {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (note?: string) => api.rejectWorkflow(id, note, token as string),
    onSuccess: (workflow) => {
      queryClient.setQueryData(["agent-workflow", id], workflow);
      queryClient.invalidateQueries({ queryKey: ["agent-workflows"] });
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
    },
  });
}
