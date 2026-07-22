"use client";

import { toast } from "sonner";

import { useExpenses, useRequestExpenseApproval } from "@/hooks/use-expenses";
import type { Expense } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const APPROVAL_VARIANT: Record<
  Expense["approval_status"],
  "default" | "secondary" | "destructive"
> = {
  not_requested: "secondary",
  pending: "secondary",
  approved: "default",
  rejected: "destructive",
};

export function ExpenseList() {
  const { data: expenses, isLoading } = useExpenses();
  const requestApproval = useRequestExpenseApproval();

  function requestReview(expense: Expense) {
    requestApproval.mutate(expense.id, {
      onSuccess: () => toast.success("Expense sent for approval."),
      onError: () => toast.error("Couldn't request approval for that expense."),
    });
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="text-base">Expenses</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {expenses?.length === 0 && (
          <p className="text-sm text-muted-foreground">No expenses yet.</p>
        )}
        <ul className="flex flex-col gap-3">
          {expenses?.map((expense) => (
            <li key={expense.id} className="flex items-center justify-between gap-3 text-sm">
              <span>
                {expense.vendor} — {expense.amount} {expense.currency}
                {expense.category && (
                  <span className="text-muted-foreground"> ({expense.category})</span>
                )}
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <Badge variant={APPROVAL_VARIANT[expense.approval_status]}>
                  {expense.approval_status.replace("_", " ")}
                </Badge>
                {expense.approval_status !== "pending" && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => requestReview(expense)}
                    disabled={requestApproval.isPending}
                  >
                    {requestApproval.isPending ? "Requesting…" : "Request approval"}
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
