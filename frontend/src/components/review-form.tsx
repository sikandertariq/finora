"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useConfirmWorkflow, useRejectWorkflow } from "@/hooks/use-receipts";
import type { AgentWorkflow } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const schema = z.object({
  vendor: z.string().min(1, "Enter who was paid."),
  amount: z
    .string()
    .min(1, "Enter an amount.")
    .regex(/^\d+(\.\d{1,2})?$/, "Use a plain number, like 42.50."),
  currency: z
    .string()
    .length(3, "Currencies are 3 letters, like USD.")
    .transform((v) => v.toUpperCase()),
  category: z.string(),
  expense_date: z.string().min(1, "Pick a date."),
});
type FormValues = z.infer<typeof schema>;

export function ReviewForm({ workflow }: { workflow: AgentWorkflow }) {
  const confirm = useConfirmWorkflow(workflow.id);
  const reject = useRejectWorkflow(workflow.id);
  const data = workflow.extracted_data;

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      vendor: data.vendor ?? "",
      amount: data.amount ?? "",
      currency: data.currency ?? "USD",
      category: data.category_suggestion ?? "",
      expense_date: data.expense_date ?? "",
    },
  });

  function onSubmit(values: FormValues) {
    confirm.mutate(values, {
      onSuccess: () => toast.success("Saved as an expense."),
      onError: () => toast.error("Couldn't save that expense."),
    });
  }

  function onReject() {
    reject.mutate(undefined, {
      onSuccess: () => toast("Rejected — no expense was created."),
      onError: () => toast.error("Couldn't reject that workflow."),
    });
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-3">
      {data.confidence !== undefined && data.confidence < 0.7 && (
        <p className="text-sm text-muted-foreground">
          The agent wasn&apos;t fully confident about this one — double-check
          before saving.
        </p>
      )}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="vendor">Vendor</Label>
        <Input id="vendor" {...register("vendor")} />
        {errors.vendor && (
          <p className="text-sm text-destructive">{errors.vendor.message}</p>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="amount">Amount</Label>
          <Input id="amount" inputMode="decimal" {...register("amount")} />
          {errors.amount && (
            <p className="text-sm text-destructive">{errors.amount.message}</p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="currency">Currency</Label>
          <Input id="currency" maxLength={3} {...register("currency")} />
          {errors.currency && (
            <p className="text-sm text-destructive">
              {errors.currency.message}
            </p>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="category">Category</Label>
        <Input id="category" {...register("category")} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="expense_date">Date</Label>
        <Input id="expense_date" type="date" {...register("expense_date")} />
        {errors.expense_date && (
          <p className="text-sm text-destructive">
            {errors.expense_date.message}
          </p>
        )}
      </div>
      <div className="mt-1 flex gap-2">
        <Button type="submit" disabled={confirm.isPending}>
          {confirm.isPending ? "Saving…" : "Confirm & save"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onReject}
          disabled={reject.isPending}
        >
          Reject
        </Button>
      </div>
    </form>
  );
}
