"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  useCreateExpenseApprovalPolicy,
  useDeleteExpenseApprovalPolicy,
  useExpenseApprovalPolicies,
  useUpdateExpenseApprovalPolicy,
} from "@/hooks/use-expenses";
import type { ExpenseApprovalPolicy, ExpenseApprovalPolicyInput } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const amount = z.string().regex(/^\d+(\.\d{1,2})?$/, "Use an amount like 500.00.");
const schema = z.object({
  name: z.string().min(1, "Enter a policy name."),
  priority: z.number().int().min(0, "Priority cannot be negative."),
  category: z.string(),
  minimum_amount: amount,
  maximum_amount: z.union([amount, z.literal("")]),
  approval_queue: z.string().min(1, "Enter an approval queue."),
  is_active: z.boolean(),
});
type FormValues = z.infer<typeof schema>;

function policyValues(policy?: ExpenseApprovalPolicy): FormValues {
  return {
    name: policy?.name ?? "",
    priority: policy?.priority ?? 100,
    category: policy?.category ?? "",
    minimum_amount: policy?.minimum_amount ?? "0.00",
    maximum_amount: policy?.maximum_amount ?? "",
    approval_queue: policy?.approval_queue ?? "Finance",
    is_active: policy?.is_active ?? true,
  };
}

function PolicyForm({
  policy,
  onSaved,
  onCancel,
}: {
  policy?: ExpenseApprovalPolicy;
  onSaved: () => void;
  onCancel?: () => void;
}) {
  const create = useCreateExpenseApprovalPolicy();
  const update = useUpdateExpenseApprovalPolicy();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: policyValues(policy),
  });

  function submit(values: FormValues) {
    const data: ExpenseApprovalPolicyInput = {
      ...values,
      maximum_amount: values.maximum_amount || null,
    };
    const mutation = policy
      ? update.mutate({ id: policy.id, data }, {
          onSuccess: () => {
            toast.success("Approval policy updated.");
            onSaved();
          },
          onError: () => toast.error("Couldn't update that policy."),
        })
      : create.mutate(data, {
          onSuccess: () => {
            toast.success("Approval policy added.");
            reset(policyValues());
            onSaved();
          },
          onError: () => toast.error("Couldn't add that policy."),
        });
    return mutation;
  }

  const isPending = create.isPending || update.isPending;
  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-3 text-sm">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={policy ? `policy-name-${policy.id}` : "policy-name"}>Name</Label>
        <Input id={policy ? `policy-name-${policy.id}` : "policy-name"} {...register("name")} />
        {errors.name && <p className="text-destructive">{errors.name.message}</p>}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={policy ? `policy-priority-${policy.id}` : "policy-priority"}>Priority</Label>
          <Input
            id={policy ? `policy-priority-${policy.id}` : "policy-priority"}
            type="number"
            {...register("priority", { valueAsNumber: true })}
          />
          {errors.priority && <p className="text-destructive">{errors.priority.message}</p>}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={policy ? `policy-category-${policy.id}` : "policy-category"}>Category</Label>
          <Input id={policy ? `policy-category-${policy.id}` : "policy-category"} placeholder="Any category" {...register("category")} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={policy ? `policy-minimum-${policy.id}` : "policy-minimum"}>Minimum amount</Label>
          <Input id={policy ? `policy-minimum-${policy.id}` : "policy-minimum"} inputMode="decimal" {...register("minimum_amount")} />
          {errors.minimum_amount && <p className="text-destructive">{errors.minimum_amount.message}</p>}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={policy ? `policy-maximum-${policy.id}` : "policy-maximum"}>Maximum amount</Label>
          <Input id={policy ? `policy-maximum-${policy.id}` : "policy-maximum"} inputMode="decimal" placeholder="No ceiling" {...register("maximum_amount")} />
          {errors.maximum_amount && <p className="text-destructive">{errors.maximum_amount.message}</p>}
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={policy ? `policy-queue-${policy.id}` : "policy-queue"}>Approval queue</Label>
        <Input id={policy ? `policy-queue-${policy.id}` : "policy-queue"} {...register("approval_queue")} />
        {errors.approval_queue && <p className="text-destructive">{errors.approval_queue.message}</p>}
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" {...register("is_active")} />
        Active
      </label>
      <div className="flex gap-2">
        <Button type="submit" disabled={isPending}>
          {isPending ? "Saving…" : policy ? "Save policy" : "Add policy"}
        </Button>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel} disabled={isPending}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

export function ApprovalPolicyManager() {
  const { data: policies, isLoading } = useExpenseApprovalPolicies();
  const remove = useDeleteExpenseApprovalPolicy();
  const [editingId, setEditingId] = useState<number | null>(null);

  function deletePolicy(id: number) {
    remove.mutate(id, {
      onSuccess: () => toast.success("Approval policy deleted."),
      onError: () => toast.error("Couldn't delete that policy."),
    });
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="text-base">Approval policies</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <PolicyForm onSaved={() => undefined} />
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {!isLoading && policies?.length === 0 && (
          <p className="text-sm text-muted-foreground">No policies yet. Unmatched expenses route to Finance.</p>
        )}
        <ul className="flex flex-col gap-3">
          {policies?.map((policy) => (
            <li key={policy.id} className="border-t pt-3 text-sm">
              {editingId === policy.id ? (
                <PolicyForm policy={policy} onSaved={() => setEditingId(null)} onCancel={() => setEditingId(null)} />
              ) : (
                <div className="flex items-start justify-between gap-3">
                  <span>
                    <span className="font-medium">{policy.name}</span> — priority {policy.priority}, {policy.category || "any category"}, {policy.minimum_amount}+
                    {policy.maximum_amount ? ` to ${policy.maximum_amount}` : ""} → {policy.approval_queue}
                    {!policy.is_active && <span className="text-muted-foreground"> (inactive)</span>}
                  </span>
                  <span className="flex shrink-0 gap-2">
                    <Button type="button" size="sm" variant="outline" onClick={() => setEditingId(policy.id)}>Edit</Button>
                    <Button type="button" size="sm" variant="destructive" onClick={() => deletePolicy(policy.id)} disabled={remove.isPending}>Delete</Button>
                  </span>
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
