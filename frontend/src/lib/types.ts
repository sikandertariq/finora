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

// Partial: this is only ever populated by an agent, so any field can be missing.
// Receipt fields (vendor..missing_fields) and reminder fields (escalation_level,
// subject, body) share one type rather than a union, since a given AgentWorkflow's
// workflow_type already tells you which subset is populated -- same "every field
// optional, hand-written, no codegen" posture as the rest of this file.
export interface ExtractedWorkflowData {
  vendor?: string;
  amount?: string;
  currency?: string;
  expense_date?: string;
  category_suggestion?: string | null;
  line_items?: LineItem[];
  confidence?: number;
  missing_fields?: string[];
  escalation_level?: string;
  subject?: string;
  body?: string;
  policy?: ExpenseApprovalPolicySnapshot;
  approval_queue?: string;
  recommendation?: "approve" | "reject" | "needs_more_information";
  rationale?: string;
  policy_flags?: string[];
  anomaly_flags?: string[];
}

export interface Invoice {
  id: number;
  client_name: string;
  client_email: string;
  amount: string;
  currency: string;
  issue_date: string;
  due_date: string;
  status: "draft" | "sent" | "paid" | "overdue" | "void";
  created_at: string;
  updated_at: string;
}

export interface AgentWorkflow {
  id: number;
  workflow_type: string;
  status: WorkflowStatus;
  receipt: Receipt | null;
  invoice: Invoice | null;
  expense: Expense | null;
  extracted_data: ExtractedWorkflowData;
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
  approval_status: "not_requested" | "pending" | "approved" | "rejected";
  created_at: string;
  updated_at: string;
}

export interface ExpenseApprovalPolicy {
  id: number;
  name: string;
  priority: number;
  category: string;
  minimum_amount: string;
  maximum_amount: string | null;
  approval_queue: string;
  is_active: boolean;
}

export interface ExpenseApprovalPolicySnapshot {
  id?: number;
  name?: string;
  priority?: number;
  category?: string;
  minimum_amount?: string;
  maximum_amount?: string | null;
  approval_queue?: string;
}

export interface ExpenseApprovalPolicyInput {
  name: string;
  priority: number;
  category: string;
  minimum_amount: string;
  maximum_amount: string | null;
  approval_queue: string;
  is_active: boolean;
}

// What a human can override on the AI's output before it's acted on.
// vendor..expense_date apply to receipt_processor workflows; subject/body apply to
// invoice_chaser ones. Every field optional -- omit one to accept the agent's version.
export interface ConfirmWorkflowOverrides {
  vendor?: string;
  amount?: string;
  currency?: string;
  category?: string;
  expense_date?: string;
  subject?: string;
  body?: string;
}
