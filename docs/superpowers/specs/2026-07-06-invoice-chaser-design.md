# Invoice Chaser — Design Spec

Status: approved, ready for implementation plan.
Branch: `feat/tenant-foundation` (continues the same branch as the Receipt Processor slice).

## Context

The Receipt Processor vertical slice (build-order steps 1–7 in [`CLAUDE.md`](../../../CLAUDE.md)) is
done and green. Per `CLAUDE.md`, the next step is to generalize to one of the other three agents.
This spec covers building **Invoice Chaser** — the second agent — as a full vertical slice
(model → service → LLM boundary → Celery → REST → frontend), the same shape step 1–7 took for
receipts.

**Decision on generalizing `AgentWorkflow` first:** punted, deliberately. We are *not* redesigning
`AgentWorkflow` into a generic polymorphic link before this agent exists. Instead we make the
minimum change needed (see below) and let a *third* agent's real needs — not a guess — drive any
further generalization. This mirrors `CLAUDE.md`'s own build philosophy: "prefer the finishable,
well-understood choice over the buzzword-maximal one."

## Scope

In scope: `Invoice` model + full CRUD (mirroring `Expense`), `InvoiceChaserService` (the AI
drafting step), a scheduled Celery task that detects overdue invoices and starts new workflows,
escalating reminder tone at fixed day-thresholds, human approve/reject wired through the existing
`AgentWorkflow` review flow, `AuditLog` coverage for the approval, and a frontend to review/approve
drafted reminders.

Out of scope (explicitly, not oversights):
- **Real email delivery.** Approving a reminder is a *simulated* send — it writes an `AuditLog`
  row with the subject/body/recipient, but no SMTP/SendGrid call happens. Wiring a real email
  provider is its own integration with its own failure modes (bounces, deliverability, provider
  config) and isn't needed to prove the agent pattern works.
- **Per-tenant configurable escalation schedules.** Thresholds are a fixed constant
  (`[1, 7, 14, 30]` days overdue), not a per-tenant rules model with its own UI.
- **Generalizing `AgentWorkflow` beyond the minimum nullable-FK change below.**
- **"Reversible"** for invoice-chaser actions (e.g., un-sending a reminder) — same as `AuditLog`'s
  step 7 scope, this records that something happened; it doesn't add an undo button.

## Data model

### New app: `apps/invoices/`

Mirrors `apps/expenses/` in shape.

`Invoice(TenantScopedModel)`:
- `client_name: CharField`
- `client_email: EmailField`
- `amount: DecimalField`
- `currency: CharField` (default `"USD"`, same convention as `Expense`)
- `issue_date: DateField`
- `due_date: DateField`
- `status: CharField` with `TextChoices`: `DRAFT`, `SENT`, `PAID`, `OVERDUE`, `VOID`

No line items on `Invoice` — that's `Expense`'s concern, not this one.

`InvoiceService` (`apps/invoices/services.py`): `create`, `update`, `get`, `list`, `delete`.
Same validation posture as `ExpenseService` — rejects `amount <= 0`. HTTP-free, plain data in,
model instances out.

`apps/invoices/schemas.py`:
```python
class InvoiceReminderDraft(BaseModel):
    subject: str
    body: str
```
Deliberately no `escalation_level` or `tone` field — which tone to draft is decided by our code
from days-overdue and fed *into* the prompt, not asked of the LLM. Keeping it out of the schema
removes a hallucination surface for something that's actually deterministic.

### Changes to existing `AgentWorkflow` (`apps/agents/models.py`)

- `receipt` FK becomes nullable (`null=True, blank=True`). A workflow is now about *either* a
  receipt or an invoice, never both.
- New `invoice = ForeignKey(Invoice, null=True, blank=True, on_delete=CASCADE, related_name="agent_workflows")`.
- `mark_approved()`'s `resulting_expense` kwarg becomes optional, default `None` — an
  invoice-chaser approval doesn't create an `Expense`.
- `workflow_type` gains a second real value: `"invoice_chaser"` (existing `"receipt_processor"`
  value and default are unchanged).

### Escalation state lives on `AgentWorkflow`, not on `Invoice`

`Invoice` stays a pure financial record — it does not know it is being chased. Each escalation
step is its own `AgentWorkflow` row. "Has this invoice already gotten its 7-day reminder?" is
answered by querying existing workflows:

```python
AgentWorkflow.objects.filter(
    invoice=invoice, workflow_type="invoice_chaser",
    extracted_data__escalation_level="day_7",
).exists()
```

The escalation level is stashed into the existing `extracted_data` JSON field **at creation time**,
before the LLM runs (`extracted_data={"escalation_level": "day_7"}`), then merged (not overwritten)
with the drafted `subject`/`body` once the workflow lands in `needs_review`. This reuses a field
that already exists rather than adding a new column.

## Service layer

`apps/agents/services.py` additions:

- **`InvoiceChaserService.run(workflow)`** — same shape as `ReceiptProcessorService.run()`: builds
  a prompt from the invoice's details, the target escalation level, and the corresponding tone
  (polite / firm / final notice), calls the injected `LLMProvider`, parses the response through
  `InvoiceReminderDraft`, and lands the workflow in `needs_review` via
  `mark_needs_review(extracted_data={**workflow.extracted_data, "subject": ..., "body": ...})`.
  Same "no separate failed status" rule as the Receipt Processor: a bad LLM response still lands in
  `needs_review` with `error_message` set, not a new enum value.

- **`InvoiceChaserScheduler.scan_and_dispatch()`** — no equivalent in the Receipt Processor, since
  receipts are triggered by an upload, not a schedule. Runs *within* a tenant's context (caller sets
  it). Logic:
  1. Fetch invoices where `status not in (paid, void, draft)` and `due_date < today`.
  2. For each, compute `days_overdue` and map to the highest threshold reached in `[1, 7, 14, 30]`.
  3. Skip if an `AgentWorkflow` already exists for `(invoice, workflow_type="invoice_chaser",
     escalation_level=<level>)`.
  4. Otherwise create a `pending` `AgentWorkflow(workflow_type="invoice_chaser", invoice=...,
     extracted_data={"escalation_level": level})` and `.delay()` the per-workflow Celery task —
     the same "create row, then hand off to Celery" shape `ReceiptUploadView` already uses.

- **`AgentWorkflowService.approve()` / `.reject()` generalized** — both branch on
  `workflow.workflow_type`:
  - `"receipt_processor"`: unchanged, calls `ExpenseService.create()`.
  - `"invoice_chaser"`: `approve()` calls `mark_approved(reviewed_by=..., resulting_expense=None)`
    and writes an `AuditLog` row with `action="reminder_sent"`,
    `metadata={"subject": ..., "body": ..., "to": invoice.client_email}` — the simulated send.
    `reject()` needs no branching; it already just marks `rejected` and logs.
  - This if/elif dispatch is the plain, honest thing for two agents. If a third agent needs the
    same branching shape, that's the signal to extract a per-type strategy — not before.

## Celery

`apps/agents/tasks.py` additions:

- **`run_invoice_chaser(workflow_id)`** — a `TenantBoundTask`, same shape as
  `run_receipt_processor`: fetch the row, build `GeminiProvider.from_settings()`, hand off to
  `InvoiceChaserService.run()`.
- **`scan_overdue_invoices()`** — the Celery **beat**-scheduled task (daily). Unlike every other
  task in this codebase, it receives no tenant context at dispatch (nothing triggered it from a
  request). It loops `Tenant.objects.all()`, sets tenant context itself per iteration
  (`tenancy.context.set(...)` / `unscoped()` as appropriate), and calls
  `InvoiceChaserScheduler.scan_and_dispatch()` per tenant. Registered in `config/celery.py`'s beat
  schedule (e.g. `crontab(hour=6, minute=0)`). For dev/manual testing it can also be invoked
  directly (`scan_overdue_invoices.apply()` or a management command) without waiting on beat.

## REST API

- **`InvoiceViewSet`** (`apps/invoices/views.py`) — full CRUD, thin, mirrors `ExpenseViewSet`
  exactly, including overriding `get_queryset()` rather than a class-attribute queryset (the
  step-5 bug: a bare `Model.objects.all()` class attribute evaluates at import time, before any
  tenant context exists).
- **No new endpoints for the chaser itself.** `AgentWorkflowViewSet`'s existing
  `list` / `retrieve` / `confirm` / `reject` already work for any `workflow_type` — they were never
  receipt-specific at the HTTP layer.
- **Small addition:** `GET /api/agent-workflows/?workflow_type=invoice_chaser` — a query-param
  filter so the frontend can ask for just reminders.

## Frontend

- `lib/types.ts` — add `Invoice`; extend the workflow type so `extracted_data` covers both agents'
  shapes (receipt's extraction fields vs. `subject`/`body`).
- `hooks/use-invoices.ts` — React Query CRUD hooks, mirrors the expense-adjacent parts of
  `use-receipts.ts`.
- `components/invoice-list.tsx` — plain table: client, amount, due date, status.
- `components/reminder-review.tsx` — shows the drafted subject/body (editable via
  react-hook-form), with "Send" (→ `confirm`) / "Dismiss" (→ `reject`) buttons. Reuses
  `workflow-panel.tsx`'s polling pattern, filtered to `workflow_type=invoice_chaser`.
- No new Zustand state — the existing `activeWorkflowId` store already covers "which workflow is
  open," regardless of type.

## Testing

- `InvoiceService` unit tests, mirroring `ExpenseService`'s (create/update/get/list/delete,
  non-positive amount rejected).
- `InvoiceChaserService.run()` with `FakeLLMProvider` — well-formed draft parses into
  `InvoiceReminderDraft`; malformed output still lands in `needs_review` with `error_message`.
- `InvoiceChaserScheduler` dedup/threshold logic — the trickiest part. Needs explicit tests for:
  "invoice crossed a new threshold → workflow created", "invoice already has a workflow at this
  threshold → skipped, no duplicate", "invoice not yet overdue / paid / void / draft → skipped
  entirely".
- `AgentWorkflowService.approve()` / `.reject()` branching for `workflow_type="invoice_chaser"` —
  confirms no `Expense` is created, `AuditLog` gets `action="reminder_sent"` with the right
  metadata.
- At least one `.delay()`-based test for `run_invoice_chaser` (not just `.apply()`) — per the
  step-5 lesson that these exercise different Celery code paths and can diverge.
- Manual verification against the real running stack: create a real overdue invoice via the API,
  trigger the scan task, confirm a drafted reminder appears and can be approved in the browser —
  same "a green `pytest` run is not proof it works" discipline as step 6.

## Open questions / deferred decisions

None outstanding — all resolved during brainstorming (send is simulated, escalation is fixed
thresholds, Invoice gets full CRUD, frontend is in scope this round, `AgentWorkflow` generalization
is punted).
