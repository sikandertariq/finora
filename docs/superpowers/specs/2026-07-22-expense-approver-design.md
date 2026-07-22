# Expense Approver — Design Spec

Status: approved for implementation by user direction.
Branch: `codex/expense-approver`.

## Context

Receipt Processor and Invoice Chaser are complete. Expense Approver is the third agent
vertical slice. It must preserve the product's finance safety boundary: the agent assesses;
a tenant member makes the state-changing approval or rejection; the action is auditable.

## Considered approaches

1. Hard-code one amount threshold and auto-approve below it. This is quick, but does not
   deliver configurable routing and violates the human-in-the-loop principle.
2. Build a general rules engine and polymorphic workflow target first. This would broaden
   the model considerably before three concrete workflows demonstrate the necessary common
   abstraction.
3. **Chosen: policy-backed approval queues.** Tenant-scoped policy rows match an expense by
   category and amount, select a named queue, and optionally flag an amount over the policy
   ceiling. The existing direct-FK workflow pattern gains one nullable `expense` FK. The
   LLM receives deterministic policy context plus recent, audited decisions, and returns a
   Pydantic-validated assessment for a person to review.

## Scope

### Policy and expense state

`ExpenseApprovalPolicy(TenantScopedModel)` owns a tenant's routing rules:

- `name`, `priority` (smaller number wins), `category` (blank means any category)
- `minimum_amount`, optional `maximum_amount`
- `approval_queue` (for example, `Finance` or `Operations`)
- `is_active`

The highest-priority matching active rule routes an expense. No match routes to the
default `Finance` queue. An amount over a matched rule's `maximum_amount` becomes a
deterministic policy flag; it is still presented for human review, never silently rejected.

`Expense` gains `approval_status` (`not_requested`, `pending`, `approved`, `rejected`),
defaulting to `not_requested`. Existing receipt confirmation continues to create an expense;
it does not automatically create a redundant approval run. A user explicitly requests
approval for an existing expense.

### Workflow and AI assessment

`AgentWorkflow` gains a nullable `expense` FK and uses `workflow_type="expense_approver"`.
This is intentionally a third direct reference rather than a speculative generic relation:
the receipt, invoice, and expense serializers/query patterns remain simple and tenant-safe.

`ExpenseApprovalService.start(expense)` is the single entry point for a request. It rejects
an expense with an existing pending/running/reviewable Expense Approver workflow, selects the
policy, saves a pending workflow with deterministic routing metadata, sets the expense to
`pending`, and enqueues a tenant-bound task.

`ExpenseApproverService.run(workflow)` builds the LLM prompt from the expense, selected policy,
and up to five recent approved/rejected Expense Approver workflow outcomes from the current
tenant. The provider response must validate as `ExpenseApprovalAssessment`:

```python
recommendation: Literal["approve", "reject", "needs_more_information"]
rationale: str
policy_flags: list[str]
anomaly_flags: list[str]
confidence: float  # 0..1
```

The workflow always lands in `needs_review`; malformed output records an error and still
lands there. The workflow metadata retains deterministic policy data and is merged with the
validated assessment.

### Human actions and audit

`AgentWorkflowService` dispatches by workflow type:

- `expense_approver` approve sets the linked expense to `approved`, marks the workflow
  approved, and appends `AuditLog(action="expense_approved")`.
- `expense_approver` reject sets the linked expense to `rejected`, marks the workflow
  rejected, and appends `AuditLog(action="expense_rejected")`.

Existing receipt and invoice behaviour remains unchanged. The generic reject action accepts
an optional human note; it is recorded in the audit metadata for every workflow type.

### REST API

The new thin resources are:

- `/api/expense-approval-policies/` — tenant-scoped CRUD; serializers validate and services
  perform all policy business logic.
- `POST /api/expenses/{id}/request-approval/` — delegates only to
  `ExpenseApprovalService.start()` and returns the new workflow.

The existing workflow list/retrieve/confirm/reject endpoints support the new type. They nest
the expense and can be filtered with `?workflow_type=expense_approver`.

### Frontend

Add server-state hooks for expense listing, approval requests, policies, and the approver
inbox. The dashboard shows an expense list with `Request approval`, an approval-policy manager,
and an inbox for ready assessments. `WorkflowPanel` routes `expense_approver` workflows to a
review form showing policy, rationale, flags, and editable human note; it reuses existing
React Query polling and the ephemeral `activeWorkflowId` Zustand state.

## Error handling and tests

- Policy matching, duplicate-workflow prevention, and service validation are unit-tested.
- Agent assessment tests inject `FakeLLMProvider`; valid output, malformed JSON, schema errors,
  deterministic policy context, and historical examples are covered.
- API tests cover tenant isolation, policy CRUD, request endpoint, workflow filtering, and
  approval/rejection effects plus audit logs.
- A `.delay()` task-dispatch test covers the real Celery dispatch path.
- Frontend TypeScript build and a browser smoke test verify the complete path.

## Explicit non-goals

- No automatic approval/rejection, real payments, or ledger writes.
- No generic polymorphic `AgentWorkflow` relation.
- No real model training; recent audited decisions are prompt context, not a training pipeline.
- No email/slack notification integration or reviewer-role system in this slice.
