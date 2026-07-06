"use client";

import { useInvoices } from "@/hooks/use-invoices";
import type { Invoice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const STATUS_VARIANT: Record<
  Invoice["status"],
  "default" | "secondary" | "destructive"
> = {
  draft: "secondary",
  sent: "secondary",
  paid: "default",
  overdue: "destructive",
  void: "destructive",
};

export function InvoiceList() {
  const { data: invoices, isLoading } = useInvoices();

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="text-base">Invoices</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {invoices?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No invoices yet — create one via the API to try the chaser.
          </p>
        )}
        <ul className="flex flex-col gap-2">
          {invoices?.map((invoice) => (
            <li
              key={invoice.id}
              className="flex items-center justify-between text-sm"
            >
              <span>
                {invoice.client_name} — {invoice.amount} {invoice.currency}
                <span className="text-muted-foreground"> (due {invoice.due_date})</span>
              </span>
              <Badge variant={STATUS_VARIANT[invoice.status]}>
                {invoice.status}
              </Badge>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
