"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useConfirmWorkflow, useRejectWorkflow } from "@/hooks/use-receipts";
import type { AgentWorkflow } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

const schema = z.object({ note: z.string().max(2000).optional() });
type FormValues = z.infer<typeof schema>;

function FlagList({ title, flags }: { title: string; flags?: string[] }) {
  if (!flags?.length) return null;
  return (
    <div className="flex flex-col gap-1">
      <p className="font-medium">{title}</p>
      <ul className="list-disc pl-5 text-muted-foreground">
        {flags.map((flag) => (
          <li key={flag}>{flag}</li>
        ))}
      </ul>
    </div>
  );
}

export function ExpenseApprovalReview({ workflow }: { workflow: AgentWorkflow }) {
  const confirm = useConfirmWorkflow(workflow.id);
  const reject = useRejectWorkflow(workflow.id);
  const data = workflow.extracted_data;
  const policy = data.policy;
  const { register, handleSubmit } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { note: "" },
  });

  function approve() {
    confirm.mutate({}, {
      onSuccess: () => toast.success("Expense approved."),
      onError: () => toast.error("Couldn't approve that expense."),
    });
  }

  function rejectExpense(values: FormValues) {
    reject.mutate(values.note?.trim() || undefined, {
      onSuccess: () => toast("Expense rejected."),
      onError: () => toast.error("Couldn't reject that expense."),
    });
  }

  return (
    <form onSubmit={handleSubmit(rejectExpense)} className="flex flex-col gap-3 text-sm">
      {workflow.expense && (
        <p className="text-muted-foreground">
          {workflow.expense.vendor} — {workflow.expense.amount} {workflow.expense.currency}
          {workflow.expense.category && ` (${workflow.expense.category})`}
        </p>
      )}
      <div className="flex flex-col gap-1">
        <p className="font-medium">Routing</p>
        <p className="text-muted-foreground">
          {policy?.name ?? "Default policy"} → {data.approval_queue ?? policy?.approval_queue ?? "Finance"}
        </p>
      </div>
      {data.recommendation && (
        <p>
          <span className="font-medium">Recommendation: </span>
          {data.recommendation.replaceAll("_", " ")}
          {data.confidence !== undefined && ` (${Math.round(data.confidence * 100)}% confidence)`}
        </p>
      )}
      {data.rationale && (
        <div className="flex flex-col gap-1">
          <p className="font-medium">Rationale</p>
          <p className="text-muted-foreground">{data.rationale}</p>
        </div>
      )}
      <FlagList title="Policy flags" flags={data.policy_flags} />
      <FlagList title="Anomaly flags" flags={data.anomaly_flags} />
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="approval-note">Rejection note (optional)</Label>
        <textarea
          id="approval-note"
          rows={3}
          className="rounded-md border border-border bg-transparent px-3 py-2 text-sm"
          {...register("note")}
        />
      </div>
      <div className="mt-1 flex gap-2">
        <Button type="button" onClick={approve} disabled={confirm.isPending || reject.isPending}>
          {confirm.isPending ? "Approving…" : "Approve"}
        </Button>
        <Button type="submit" variant="outline" disabled={confirm.isPending || reject.isPending}>
          {reject.isPending ? "Rejecting…" : "Reject"}
        </Button>
      </div>
    </form>
  );
}
