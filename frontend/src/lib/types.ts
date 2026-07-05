// Hand-written to mirror backend/apps/{expenses,agents}/serializers.py exactly.
// No OpenAPI codegen, per project convention — keep these in sync by hand.

export type WorkflowStatus =
  | "pending"
  | "running"
  | "needs_review"
  | "approved"
  | "rejected";

export interface Receipt {
  id: number;
  file: string;
  uploaded_by: number | null;
  uploaded_at: string;
}

export interface LineItem {
  description: string;
  amount: string;
}

// Partial: this is only ever populated by the LLM, so any field can be missing.
export interface ExtractedReceiptData {
  vendor?: string;
  amount?: string;
  currency?: string;
  expense_date?: string;
  category_suggestion?: string | null;
  line_items?: LineItem[];
  confidence?: number;
  missing_fields?: string[];
}

export interface AgentWorkflow {
  id: number;
  workflow_type: string;
  status: WorkflowStatus;
  receipt: Receipt;
  extracted_data: ExtractedReceiptData;
  error_message: string;
  resulting_expense: number | null;
  created_at: string;
  updated_at: string;
}

export interface Expense {
  id: number;
  vendor: string;
  amount: string;
  currency: string;
  category: string;
  description: string;
  expense_date: string;
  receipt: number | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

// What a human can override on the AI's extraction before it's saved.
// Every field optional — omit one to accept what the agent extracted.
export interface ConfirmWorkflowOverrides {
  vendor?: string;
  amount?: string;
  currency?: string;
  category?: string;
  expense_date?: string;
}
