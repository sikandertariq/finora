# Expense Approver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a policy-routed, human-reviewed Expense Approver vertical slice across Django, Celery, REST, and the Next.js dashboard.

**Architecture:** `apps.expenses` owns expense approval state and tenant-scoped policy rules. `apps.agents` owns one reviewable workflow per requested approval, runs an injected-provider assessment through a Pydantic schema, and records a human decision in `AuditLog`. The dashboard starts approval runs, polls ready workflows, and displays policy/anomaly context without storing server data in Zustand.

**Tech Stack:** Django 5.2 + DRF, Celery + Redis, Pydantic, pytest + pytest-django + factory_boy, Next.js 16 + TypeScript, React Query, react-hook-form + zod, shadcn/ui.

## Global Constraints

- ViewSet → Serializer → Service → Model; services never receive `request` or return `Response`.
- Tenant-owned models inherit `TenantScopedModel`; tenant filtering is never duplicated in views.
- Every LLM response validates through Pydantic before database state is updated.
- A human-confirmed state change appends an `AuditLog` row in the service.
- Celery coverage includes a `.delay()` dispatch path.
- React Query owns server state and Zustand remains limited to `activeWorkflowId`.
- Keep hand-written frontend interfaces synchronized with serializers; do not add code generation.
- Follow red → green → refactor for every production behaviour.

---

### Task 1: Approval domain model and policy service

**Files:**

- Modify: `backend/apps/expenses/models.py`, `backend/apps/expenses/services.py`, `backend/apps/expenses/serializers.py`, `backend/apps/expenses/views.py`, `backend/apps/expenses/urls.py`
- Create: `backend/apps/expenses/approval_services.py`, `backend/apps/expenses/migrations/0002_expenseapprovalpolicy_expense_approval_status.py`
- Test: `backend/tests/test_expense_approval_models.py`, `backend/tests/test_expense_approval_policy_service.py`

**Interfaces:**

- `Expense.ApprovalStatus = NOT_REQUESTED/PENDING/APPROVED/REJECTED`.
- `ExpenseApprovalPolicy(TenantScopedModel)` includes routing fields documented in the spec.
- `ExpenseApprovalPolicyService.create/update/get/list/delete` and `.matching_policy(expense)` return plain models or `None`.

- [ ] Write tests proving new expenses default to `not_requested`, policies tenant-scope, amount/category matching honours active priority, and invalid amount ranges are rejected.
- [ ] Run `python -m pytest tests/test_expense_approval_models.py tests/test_expense_approval_policy_service.py -v`; verify the imports/fields fail before implementation.
- [ ] Add model fields, policy model, service validation, serializers, thin CRUD viewset/router, and migration.
- [ ] Re-run the focused tests until green; commit `feat(expenses): add approval policies and state`.

### Task 2: Workflow target, Pydantic assessment, and assessment service

**Files:**

- Modify: `backend/apps/agents/models.py`, `backend/apps/agents/services.py`, `backend/apps/agents/serializers.py`
- Create: `backend/apps/agents/migrations/0004_agentworkflow_expense.py`, `backend/apps/expenses/approval_schemas.py`
- Test: `backend/tests/test_expense_approver_service.py`, `backend/tests/test_expense_approval_schema.py`

**Interfaces:**

- `ExpenseApprovalAssessment` has recommendation, rationale, policy flags, anomaly flags, confidence.
- `ExpenseApproverService(llm_provider).run(workflow)` changes pending → running → needs_review and merges deterministic metadata with validated output.

- [ ] Write focused tests for valid JSON, fenced JSON, malformed JSON, schema failure, retained policy metadata, prompt policy context, and prior approved/rejected context.
- [ ] Run the tests and verify they fail because the schema/service/workflow expense link does not exist.
- [ ] Add the nullable workflow expense FK, serializer nesting, Pydantic schema, system prompt, service, and migration. Query historical outcomes only through tenant-scoped `AgentWorkflow.objects`.
- [ ] Re-run focused tests and commit `feat(agents): assess expenses for approval`.

### Task 3: Request, human decision, audit, and Celery integration

**Files:**

- Modify: `backend/apps/agents/services.py`, `backend/apps/agents/tasks.py`, `backend/apps/agents/views.py`, `backend/apps/agents/serializers.py`, `backend/apps/expenses/views.py`
- Test: `backend/tests/test_expense_approval_workflow_service.py`, `backend/tests/test_expense_approver_task.py`, `backend/tests/test_expense_approval_api.py`, `backend/tests/test_agent_workflow_api.py`

**Interfaces:**

- `ExpenseApprovalService.start(expense) -> AgentWorkflow` prevents active duplicates, persists routing data, sets approval state pending, and enqueues `run_expense_approver.delay(tenant_id=..., workflow_id=...)`.
- `AgentWorkflowService.approve/reject` route `expense_approver` decisions to update the expense and append `expense_approved` / `expense_rejected` audit events.
- `POST /api/expenses/{id}/request-approval/` returns 201 with workflow data.

- [ ] Write tests for duplicate prevention, tenant-safe request endpoint, `.delay()` args, valid workflow filtering, approve/reject state transitions, optional rejection note, and audit metadata.
- [ ] Run tests and verify the requested endpoint/task/service branches are absent.
- [ ] Implement the HTTP-free coordinator service, tenant-bound task, thin endpoint, workflow dispatch branches, and rejection-note serializer without changing receipt or invoice behaviour.
- [ ] Run task/service/API tests and commit `feat(agents): add expense approval workflow`.

### Task 4: Dashboard integration

**Files:**

- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/hooks/use-receipts.ts`, `frontend/src/components/workflow-panel.tsx`, `frontend/src/app/page.tsx`
- Create: `frontend/src/hooks/use-expenses.ts`, `frontend/src/components/expense-list.tsx`, `frontend/src/components/approval-inbox.tsx`, `frontend/src/components/expense-approval-review.tsx`, `frontend/src/components/approval-policy-manager.tsx`

**Interfaces:**

- Fetch/mutation helpers cover expenses, policy CRUD, and `requestExpenseApproval`.
- `usePendingExpenseApprovals` polls `expense_approver` reviewable workflows.
- `ExpenseApprovalReview` confirms or rejects a workflow with an optional note.

- [ ] Extend hand-written types and API functions before components consume them.
- [ ] Add React Query hooks with stable query keys and invalidate expense/policy/workflow data after mutations.
- [ ] Add the expense list, policy manager, inbox, and review form; branch `WorkflowPanel` on `expense_approver`; keep `activeWorkflowId` as the sole Zustand state.
- [ ] Run `npm run build --prefix /Users/sikandert/Projects/finora/frontend`; commit `feat(frontend): add expense approval review UI`.

### Task 5: End-to-end verification and documentation

**Files:**

- Modify: `HANDOFF.md`
- Test: complete backend suite and frontend build

- [ ] Run `cd backend && source .venv/bin/activate && python -m pytest -q` and resolve any regressions.
- [ ] Run the frontend production build.
- [ ] Apply migrations to the local development database; start the stack when available and exercise create expense → request approval → assessment → human decision.
- [ ] Update `HANDOFF.md` with the completed slice, model decision, tests, and manual-verification result.
- [ ] Commit verification/docs changes as `docs: record expense approver handoff`.
