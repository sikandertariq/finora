"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ExpenseApprovalPolicyInput } from "@/lib/types";

export function useExpenses() {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["expenses"],
    queryFn: () => api.listExpenses(token as string),
    enabled: !!token,
  });
}

export function useRequestExpenseApproval() {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (expenseId: number) =>
      api.requestExpenseApproval(expenseId, token as string),
    onSuccess: (workflow) => {
      queryClient.setQueryData(["agent-workflow", workflow.id], workflow);
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
      queryClient.invalidateQueries({ queryKey: ["agent-workflows"] });
    },
  });
}

export function useExpenseApprovalPolicies() {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["expense-approval-policies"],
    queryFn: () => api.listExpenseApprovalPolicies(token as string),
    enabled: !!token,
  });
}

export function useCreateExpenseApprovalPolicy() {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ExpenseApprovalPolicyInput) =>
      api.createExpenseApprovalPolicy(data, token as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["expense-approval-policies"] });
    },
  });
}

export function useUpdateExpenseApprovalPolicy() {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: ExpenseApprovalPolicyInput }) =>
      api.updateExpenseApprovalPolicy(id, data, token as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["expense-approval-policies"] });
    },
  });
}

export function useDeleteExpenseApprovalPolicy() {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.deleteExpenseApprovalPolicy(id, token as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["expense-approval-policies"] });
    },
  });
}

// An inbox must poll its list: these workflows finish asynchronously and are
// not necessarily selected in the review panel yet.
export function usePendingExpenseApprovals() {
  const { token } = useAuth();

  return useQuery({
    queryKey: [
      "agent-workflows",
      { workflow_type: "expense_approver", status: "needs_review" },
    ],
    queryFn: () =>
      api.listWorkflows(
        { workflow_type: "expense_approver", status: "needs_review" },
        token as string
      ),
    enabled: !!token,
    refetchInterval: 10000,
  });
}
