"use client";

import { usePendingReminders } from "@/hooks/use-invoices";
import { useWorkflowUiStore } from "@/store/workflow-ui-store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ReminderInbox() {
  const { data: reminders, isLoading } = usePendingReminders();
  const setActiveWorkflowId = useWorkflowUiStore((s) => s.setActiveWorkflowId);

  if (isLoading || !reminders?.length) return null;

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="text-base">Reminders to review</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {reminders.map((workflow) => (
            <li key={workflow.id}>
              <button
                type="button"
                onClick={() => setActiveWorkflowId(workflow.id)}
                className="text-sm underline underline-offset-2"
              >
                {workflow.invoice?.client_name ?? `Invoice workflow #${workflow.id}`}
                {" — "}
                {workflow.extracted_data.subject ?? "reminder ready"}
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
