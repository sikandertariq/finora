"use client";

import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";
import { UploadZone } from "@/components/upload-zone";
import { WorkflowPanel } from "@/components/workflow-panel";
import { InvoiceList } from "@/components/invoice-list";
import { ReminderInbox } from "@/components/reminder-inbox";
import { Button } from "@/components/ui/button";
import { BackendStatus } from "@/components/backend-status";

export default function Home() {
  const { token, signOut } = useAuth();

  return (
    <main className="flex min-h-screen flex-col items-center gap-8 p-10">
      <div className="flex w-full max-w-md items-center justify-between">
        <h1 className="text-2xl font-semibold">Finora</h1>
        {token && (
          <Button variant="ghost" size="sm" onClick={signOut}>
            Sign out
          </Button>
        )}
      </div>

      <BackendStatus />

      {!token ? (
        <LoginForm />
      ) : (
        <>
          <UploadZone />
          <WorkflowPanel />
          <InvoiceList />
          <ReminderInbox />
        </>
      )}
    </main>
  );
}
