"use client";

import { usePendingExpenseApprovals } from "@/hooks/use-expenses";
import { useWorkflowUiStore } from "@/store/workflow-ui-store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ApprovalInbox() {
  const { data: workflows, isLoading } = usePendingExpenseApprovals();
  const setActiveWorkflowId = useWorkflowUiStore((s) => s.setActiveWorkflowId);

  if (isLoading || !workflows?.length) return null;

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="text-base">Expense approvals to review</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {workflows.map((workflow) => (
            <li key={workflow.id}>
              <button
                type="button"
                onClick={() => setActiveWorkflowId(workflow.id)}
                className="text-left text-sm underline underline-offset-2"
              >
                {workflow.expense?.vendor ?? `Expense workflow #${workflow.id}`}
                {" — "}
                {workflow.extracted_data.recommendation ?? "assessment ready"}
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
