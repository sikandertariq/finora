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
  subject: z.string().min(1, "Enter a subject."),
  body: z.string().min(1, "Enter a message."),
});
type FormValues = z.infer<typeof schema>;

export function ReminderReview({ workflow }: { workflow: AgentWorkflow }) {
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
      subject: data.subject ?? "",
      body: data.body ?? "",
    },
  });

  function onSubmit(values: FormValues) {
    confirm.mutate(values, {
      onSuccess: () => toast.success("Reminder sent."),
      onError: () => toast.error("Couldn't send that reminder."),
    });
  }

  function onReject() {
    reject.mutate(undefined, {
      onSuccess: () => toast("Dismissed — no reminder was sent."),
      onError: () => toast.error("Couldn't dismiss that reminder."),
    });
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-3">
      {workflow.invoice && (
        <p className="text-sm text-muted-foreground">
          To {workflow.invoice.client_name} ({workflow.invoice.client_email}) —{" "}
          {workflow.invoice.amount} {workflow.invoice.currency}, due{" "}
          {workflow.invoice.due_date}
        </p>
      )}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="subject">Subject</Label>
        <Input id="subject" {...register("subject")} />
        {errors.subject && (
          <p className="text-sm text-destructive">{errors.subject.message}</p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="body">Message</Label>
        <textarea
          id="body"
          rows={5}
          className="rounded-md border border-border bg-transparent px-3 py-2 text-sm"
          {...register("body")}
        />
        {errors.body && (
          <p className="text-sm text-destructive">{errors.body.message}</p>
        )}
      </div>
      <div className="mt-1 flex gap-2">
        <Button type="submit" disabled={confirm.isPending}>
          {confirm.isPending ? "Sending…" : "Send"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onReject}
          disabled={reject.isPending}
        >
          Dismiss
        </Button>
      </div>
    </form>
  );
}
