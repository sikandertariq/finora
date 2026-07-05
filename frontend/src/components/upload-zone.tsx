"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";

import { useUploadReceipt } from "@/hooks/use-receipts";
import { useWorkflowUiStore } from "@/store/workflow-ui-store";
import { Button } from "@/components/ui/button";

export function UploadZone() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const upload = useUploadReceipt();
  const setActiveWorkflowId = useWorkflowUiStore((s) => s.setActiveWorkflowId);

  function handleFile(file: File) {
    upload.mutate(file, {
      onSuccess: (workflow) => {
        setActiveWorkflowId(workflow.id);
        toast.success("Receipt uploaded — the agent is reading it.");
      },
      onError: () => {
        toast.error("Couldn't upload that receipt. Try again.");
      },
    });
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file) handleFile(file);
      }}
      className={`flex w-full max-w-md flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 text-center transition-colors ${
        isDragging ? "border-primary bg-accent" : "border-border"
      }`}
    >
      <p className="text-sm text-muted-foreground">
        Drag a receipt here, or
      </p>
      <Button
        type="button"
        variant="outline"
        onClick={() => inputRef.current?.click()}
        disabled={upload.isPending}
      >
        {upload.isPending ? "Uploading…" : "Choose a file"}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*,application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
