"use client";

import { useWorkflow } from "@/hooks/use-receipts";
import { useWorkflowUiStore } from "@/store/workflow-ui-store";
import type { WorkflowStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ReviewForm } from "@/components/review-form";

const STATUS_LABEL: Record<WorkflowStatus, string> = {
  pending: "Waiting to be processed",
  running: "Reading the receipt…",
  needs_review: "Ready for your review",
  approved: "Approved",
  rejected: "Rejected",
};

const STATUS_VARIANT: Record<
  WorkflowStatus,
  "default" | "secondary" | "destructive"
> = {
  pending: "secondary",
  running: "secondary",
  needs_review: "default",
  approved: "default",
  rejected: "destructive",
};

export function WorkflowPanel() {
  const activeWorkflowId = useWorkflowUiStore((s) => s.activeWorkflowId);
  const { data: workflow, isLoading } = useWorkflow(activeWorkflowId);

  if (!activeWorkflowId) return null;
  if (isLoading || !workflow) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">
          Receipt #{workflow.receipt?.id ?? workflow.id}
        </CardTitle>
        <Badge variant={STATUS_VARIANT[workflow.status]}>
          {STATUS_LABEL[workflow.status]}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {(workflow.status === "pending" || workflow.status === "running") && (
          <p className="text-sm text-muted-foreground">
            This updates automatically — no need to refresh.
          </p>
        )}
        {workflow.status === "needs_review" && (
          <ReviewForm workflow={workflow} />
        )}
        {workflow.status === "approved" && (
          <p className="text-sm text-muted-foreground">
            Saved as expense #{workflow.resulting_expense}.
          </p>
        )}
        {workflow.status === "rejected" && (
          <p className="text-sm text-muted-foreground">
            This receipt was rejected — no expense was created.
          </p>
        )}
        {workflow.error_message && (
          <p className="text-sm text-destructive">{workflow.error_message}</p>
        )}
      </CardContent>
    </Card>
  );
}
