"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Toaster } from "@/components/ui/sonner";
import { subscribeToAuthSession } from "@/lib/auth-session";
import { useWorkflowUiStore } from "@/store/workflow-ui-store";

function AuthSessionCacheBoundary({ queryClient }: { queryClient: QueryClient }) {
  useEffect(
    () =>
      subscribeToAuthSession(() => {
        // Queries are tenant-scoped on the server but their client keys are not.
        // Clear them synchronously whenever the authenticated session changes so a
        // logout/login cannot briefly display the previous tenant's cached data.
        queryClient.clear();
        useWorkflowUiStore.getState().setActiveWorkflowId(null);
      }),
    [queryClient]
  );

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <AuthSessionCacheBoundary queryClient={queryClient} />
      {children}
      <Toaster />
    </QueryClientProvider>
  );
}
