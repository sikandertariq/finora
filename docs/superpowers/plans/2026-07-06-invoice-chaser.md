# Invoice Chaser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Invoice Chaser as the second full vertical-slice agent (model → service → LLM boundary → Celery → REST → frontend), generalizing `AgentWorkflow` by the minimum amount needed rather than a speculative redesign.

**Architecture:** A new `apps/invoices` app owns the `Invoice` model and `InvoiceService`, mirroring `apps/expenses`. `AgentWorkflow` gains a nullable `invoice` FK alongside the now-nullable `receipt` FK. A daily Celery **beat** task (`scan_overdue_invoices`) loops tenants and, per tenant, asks `InvoiceChaserScheduler` which overdue invoices just crossed an escalation threshold (`1/7/14/30` days); each gets its own `AgentWorkflow` + a dispatched `run_invoice_chaser` task that drafts a reminder via the existing `LLMProvider` boundary, validated through a new `InvoiceReminderDraft` Pydantic schema. `AgentWorkflowService.approve()`/`.reject()` are generalized to branch on `workflow_type`; approving a reminder is a **simulated send** — it writes an `AuditLog` row, no real email goes out. Frontend adds a plain invoice table and a reminder inbox/review UI, reusing the existing polling and Zustand `activeWorkflowId` patterns.

**Tech Stack:** Django 5.2 + DRF, Celery + Redis (beat + worker), Pydantic, pytest + pytest-django + factory_boy, Next.js 15 + TypeScript, React Query, react-hook-form + zod, shadcn/ui.

## Global Constraints

- **Dependency flow:** ViewSet (thin) → Serializer (validate/shape) → Service (logic) → Model. Services never touch `request`/`Response`.
- **Never** set `queryset = Model.objects.all()` as a viewset class attribute on a `TenantScopedModel` — override `get_queryset()` instead (it runs per-request, after tenant context is set).
- **Every LLM output** must be parsed into a Pydantic model before it touches the DB.
- **Any state-changing action a human takes on an agent's output writes an `AuditLog` row** as the last step of the service method that performs it.
- **When testing a Celery task, call `.delay()`/`.apply_async()` at least once, not only `.apply()`** — they exercise different Celery code paths (see `backend/tests/test_tasks.py` for why).
- **React Query owns all server state; Zustand owns only ephemeral UI state** (`activeWorkflowId`). Don't blur this.
- **No OpenAPI/codegen** — `frontend/src/lib/types.ts` is hand-written and must be kept in sync with DRF serializers by hand.
- **This frontend's Next.js may differ from training-data conventions** — `frontend/AGENTS.md` says to check `frontend/node_modules/next/dist/docs/` before writing anything unfamiliar. In practice: follow the exact patterns already in `frontend/src/components/` and `frontend/src/hooks/use-receipts.ts` (App Router, `"use client"`, React Query, `useSyncExternalStore` for the token) rather than introducing new APIs — every task below does this.
- **TDD:** write the failing test, watch it fail, implement, watch it pass, commit. Small commits.
- Backend tests run via: `cd backend && source .venv/bin/activate && python -m pytest -q`.

**Two small corrections to the approved spec, made while getting precise about exact code (per the spec's own self-review step — noted here for transparency, not re-litigated):**
1. The spec's frontend section says a drafted reminder's subject/body are "editable" before sending, but its service-layer section didn't thread an `overrides` param through `invoice_chaser` approval. Fixed by reusing the existing `overrides` mechanism `ConfirmWorkflowSerializer`/`approve()` already have for receipts — see Task 9.
2. Nothing in this slice ever transitions an `Invoice` to `status="overdue"` — "overdue" is computed from `due_date` at scan time, not stored. The `OVERDUE` choice stays in the enum (per the approved data model) for a future status-sync job to use; it isn't dead code, just not wired to anything yet, same spirit as `AgentWorkflow`'s "no failed status" decision.

---

## Task 1: `Invoice` model

**Files:**
- Create: `backend/apps/invoices/__init__.py` (empty)
- Create: `backend/apps/invoices/apps.py`
- Create: `backend/apps/invoices/models.py`
- Test: `backend/tests/test_invoices_models.py`
- Modify: `backend/config/settings/base.py` (register the app)

**Interfaces:**
- Produces: `Invoice(TenantScopedModel)` with fields `client_name: str`, `client_email: str`, `amount: Decimal`, `currency: str`, `issue_date: date`, `due_date: date`, `status: str` (one of `Invoice.Status.DRAFT/SENT/PAID/OVERDUE/VOID`, default `DRAFT`).

- [ ] **Step 1: Register the app**

Edit `backend/config/settings/base.py`, in `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "apps.tenancy",
    "apps.expenses",
    "apps.agents",
    "apps.invoices",
]
```

- [ ] **Step 2: Create the app config**

Create `backend/apps/invoices/__init__.py` (empty file).

Create `backend/apps/invoices/apps.py`:

```python
from django.apps import AppConfig


class InvoicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.invoices"
    label = "invoices"
```

- [ ] **Step 3: Write the failing model test**

Create `backend/tests/test_invoices_models.py`:

```python
import pytest

from apps.invoices.models import Invoice
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def test_invoice_is_scoped_to_current_tenant():
    tenant_a, tenant_b = TenantFactory(), TenantFactory()
    Invoice.all_tenants.create(
        tenant=tenant_a, client_name="Acme", client_email="ap@acme.test",
        amount="100.00", issue_date="2026-06-01", due_date="2026-06-15",
    )
    Invoice.all_tenants.create(
        tenant=tenant_b, client_name="Globex", client_email="ap@globex.test",
        amount="200.00", issue_date="2026-06-01", due_date="2026-06-15",
    )

    context.set_current_tenant(tenant_a.id)
    names = set(Invoice.objects.values_list("client_name", flat=True))
    assert names == {"Acme"}


def test_invoice_without_tenant_context_raises():
    with pytest.raises(context.TenantContextRequired):
        list(Invoice.objects.all())


def test_invoice_defaults_to_draft_status():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)

    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    assert invoice.status == Invoice.Status.DRAFT
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_invoices_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.invoices.models'` (or similar import error).

- [ ] **Step 5: Write the model**

Create `backend/apps/invoices/models.py`:

```python
from django.db import models

from apps.tenancy.models import TenantScopedModel


class Invoice(TenantScopedModel):
    """A bill sent to a client, tracked so the Invoice Chaser agent knows what's overdue.

    No line items here (that's Expense's concern) -- this is one client, one amount,
    one due date. ``OVERDUE`` is a recognized status but nothing in this slice sets
    it automatically: the chaser computes overdue-ness from ``due_date`` directly at
    scan time, not from this field. It's here for a future status-sync job, not dead
    code.
    """

    class Status(models.TextChoices):
        DRAFT = "draft"
        SENT = "sent"
        PAID = "paid"
        OVERDUE = "overdue"
        VOID = "void"

    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    issue_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-due_date"]

    def __str__(self):
        return f"{self.client_name} — {self.amount} {self.currency} (due {self.due_date})"
```

- [ ] **Step 6: Make and run migrations**

Run:
```bash
cd backend && source .venv/bin/activate
python manage.py makemigrations invoices
```
Expected output: `Migrations for 'invoices': ... - Create model Invoice`

- [ ] **Step 7: Run the test to verify it passes**

Run: `python -m pytest tests/test_invoices_models.py -v`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/apps/invoices backend/config/settings/base.py backend/tests/test_invoices_models.py
git commit -m "feat(invoices): add Invoice model, tenant-scoped"
```

---

## Task 2: `InvoiceService`

**Files:**
- Create: `backend/apps/invoices/services.py`
- Test: `backend/tests/test_invoice_service.py`

**Interfaces:**
- Consumes: `Invoice` (Task 1).
- Produces: `InvoiceService.create(*, client_name, client_email, amount, issue_date, due_date, currency="USD", status=Invoice.Status.DRAFT) -> Invoice`, `.update(invoice, **fields) -> Invoice`, `.get(invoice_id) -> Invoice`, `.list(**filters) -> QuerySet`, `.delete(invoice) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_invoice_service.py`:

```python
import pytest

from apps.invoices.models import Invoice
from apps.invoices.services import InvoiceService
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def test_create_persists_an_invoice(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    assert invoice.id is not None
    assert invoice.tenant_id == tenant_context.id
    assert str(invoice.amount) == "100.00"
    assert invoice.currency == "USD"
    assert invoice.status == Invoice.Status.DRAFT


def test_create_rejects_non_positive_amount(tenant_context):
    with pytest.raises(ValueError):
        InvoiceService.create(
            client_name="Acme", client_email="ap@acme.test", amount="0",
            issue_date="2026-06-01", due_date="2026-06-15",
        )


def test_create_accepts_an_explicit_status(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )

    assert invoice.status == Invoice.Status.SENT


def test_update_mutates_allowed_fields(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    InvoiceService.update(invoice, client_name="Acme Corp", status=Invoice.Status.SENT)

    invoice.refresh_from_db()
    assert invoice.client_name == "Acme Corp"
    assert invoice.status == Invoice.Status.SENT


def test_update_rejects_unknown_field(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    with pytest.raises(ValueError):
        InvoiceService.update(invoice, tenant_id=999)


def test_update_rejects_non_positive_amount(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    with pytest.raises(ValueError):
        InvoiceService.update(invoice, amount="-5.00")


def test_list_returns_only_current_tenant_invoices(tenant_context):
    other_tenant = TenantFactory()
    InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    context.set_current_tenant(other_tenant.id)
    InvoiceService.create(
        client_name="Globex", client_email="ap@globex.test", amount="200.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    context.set_current_tenant(tenant_context.id)
    names = set(InvoiceService.list().values_list("client_name", flat=True))
    assert names == {"Acme"}


def test_get_fetches_by_id(tenant_context):
    created = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    fetched = InvoiceService.get(created.id)
    assert fetched.id == created.id


def test_delete_removes_the_invoice(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    InvoiceService.delete(invoice)

    assert InvoiceService.list().count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_invoice_service.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'apps.invoices.services'`).

- [ ] **Step 3: Write the service**

Create `backend/apps/invoices/services.py`:

```python
from decimal import Decimal

from .models import Invoice

_MUTABLE_FIELDS = {
    "client_name", "client_email", "amount", "currency", "issue_date", "due_date", "status",
}


class InvoiceService:
    """Business logic for invoices. HTTP-free, mirrors ExpenseService exactly so
    InvoiceViewSet and the (future) chaser-adjacent code share one code path."""

    @staticmethod
    def create(*, client_name, client_email, amount, issue_date, due_date,
               currency="USD", status=Invoice.Status.DRAFT):
        _validate_amount(amount)
        return Invoice.objects.create(
            client_name=client_name,
            client_email=client_email,
            amount=amount,
            currency=currency,
            issue_date=issue_date,
            due_date=due_date,
            status=status,
        )

    @staticmethod
    def update(invoice, **fields):
        unknown = set(fields) - _MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Cannot update unknown field(s): {', '.join(sorted(unknown))}")
        if "amount" in fields:
            _validate_amount(fields["amount"])
        for key, value in fields.items():
            setattr(invoice, key, value)
        invoice.save()
        return invoice

    @staticmethod
    def get(invoice_id):
        return Invoice.objects.get(id=invoice_id)

    @staticmethod
    def list(**filters):
        return Invoice.objects.filter(**filters)

    @staticmethod
    def delete(invoice):
        invoice.delete()


def _validate_amount(amount):
    if Decimal(str(amount)) <= 0:
        raise ValueError("Invoice amount must be greater than zero.")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_invoice_service.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/invoices/services.py backend/tests/test_invoice_service.py
git commit -m "feat(invoices): add InvoiceService"
```

---

## Task 3: `InvoiceReminderDraft` schema

**Files:**
- Create: `backend/apps/invoices/schemas.py`
- Test: `backend/tests/test_invoice_reminder_draft_schema.py`

**Interfaces:**
- Produces: `InvoiceReminderDraft(BaseModel)` with `subject: str` (min length 1), `body: str` (min length 1).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_invoice_reminder_draft_schema.py`:

```python
import pytest
from pydantic import ValidationError

from apps.invoices.schemas import InvoiceReminderDraft


def test_valid_draft_parses():
    draft = InvoiceReminderDraft(subject="Invoice overdue", body="Please pay by Friday.")
    assert draft.subject == "Invoice overdue"


def test_empty_subject_is_rejected():
    with pytest.raises(ValidationError):
        InvoiceReminderDraft(subject="", body="Please pay by Friday.")


def test_empty_body_is_rejected():
    with pytest.raises(ValidationError):
        InvoiceReminderDraft(subject="Invoice overdue", body="")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_invoice_reminder_draft_schema.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write the schema**

Create `backend/apps/invoices/schemas.py`:

```python
from pydantic import BaseModel, Field


class InvoiceReminderDraft(BaseModel):
    """What an LLM must produce when drafting an overdue-invoice reminder.

    Deliberately no ``escalation_level``/``tone`` field: which tone to draft is decided
    by our own code from days-overdue and fed *into* the prompt, not asked of the LLM --
    that's a deterministic decision, not one to add hallucination surface for.
    """

    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_invoice_reminder_draft_schema.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/invoices/schemas.py backend/tests/test_invoice_reminder_draft_schema.py
git commit -m "feat(invoices): add InvoiceReminderDraft schema"
```

---

## Task 4: Generalize `AgentWorkflow`

**Files:**
- Modify: `backend/apps/agents/models.py`
- Modify: `backend/tests/test_agent_workflow_model.py` (add new tests; existing ones must still pass unchanged)

**Interfaces:**
- Consumes: `Invoice` (Task 1).
- Produces: `AgentWorkflow.receipt` now nullable; new `AgentWorkflow.invoice` (nullable FK to `Invoice`, `related_name="agent_workflows"`); `AgentWorkflow.mark_approved(*, reviewed_by, resulting_expense=None)` (was required, now optional).

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `backend/tests/test_agent_workflow_model.py`:

```python
def test_workflow_can_be_created_for_an_invoice_instead_of_a_receipt():
    from apps.invoices.models import Invoice

    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    workflow = AgentWorkflow.objects.create(workflow_type="invoice_chaser", invoice=invoice)

    assert workflow.receipt_id is None
    assert workflow.invoice_id == invoice.id


def test_mark_approved_without_a_resulting_expense():
    user = UserFactory()
    from apps.invoices.models import Invoice

    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )
    workflow = AgentWorkflow.objects.create(workflow_type="invoice_chaser", invoice=invoice)

    workflow.mark_approved(reviewed_by=user)

    assert workflow.status == AgentWorkflow.Status.APPROVED
    assert workflow.resulting_expense is None
    assert workflow.reviewed_by_id == user.id
```

(No fixture changes needed — the file already has an `autouse=True` `tenant_context` fixture at the top that sets a tenant for every test in the module, so these two new tests get a tenant automatically, same as the existing ones. Just call `Invoice.objects.create(...)` directly, the same way `_workflow()` calls `Receipt.objects.create(...)`.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_agent_workflow_model.py -v`
Expected: FAIL — `test_workflow_can_be_created_for_an_invoice_instead_of_a_receipt` fails with `IntegrityError`/`TypeError` (no `invoice` field yet); `test_mark_approved_without_a_resulting_expense` fails with `TypeError: mark_approved() missing 1 required keyword-only argument: 'resulting_expense'`.

- [ ] **Step 3: Modify the model**

Edit `backend/apps/agents/models.py`. Change the `receipt` field and add `invoice`:

```python
from apps.expenses.models import Expense, Receipt
from apps.invoices.models import Invoice
from apps.tenancy.models import TenantScopedModel
```

```python
    workflow_type = models.CharField(max_length=50, default="receipt_processor")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    receipt = models.ForeignKey(
        Receipt, on_delete=models.CASCADE, null=True, blank=True, related_name="agent_workflows"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, null=True, blank=True, related_name="agent_workflows"
    )
    extracted_data = models.JSONField(default=dict, blank=True)
```

(Leave everything else in the class body unchanged — `extracted_data` through `updated_at`.)

Change `mark_approved`:

```python
    def mark_approved(self, *, reviewed_by, resulting_expense=None):
        self.reviewed_by = reviewed_by
        self.resulting_expense = resulting_expense
        self.status = self.Status.APPROVED
        self.save(
            update_fields=["reviewed_by", "resulting_expense", "status", "updated_at"]
        )
```

Also update the class docstring's first line, since it's no longer receipt-only:

```python
class AgentWorkflow(TenantScopedModel):
    """One run of an agent against one piece of input, reviewable and reversible.

    ``workflow_type`` identifies which agent produced this row: "receipt_processor" or
    "invoice_chaser" so far. Exactly one of ``receipt``/``invoice`` is set, depending on
    which. Not a generic polymorphic link on purpose -- see
    docs/superpowers/specs/2026-07-06-invoice-chaser-design.md for why this was punted
    rather than guessed at with only one agent's needs as evidence.
    """
```

- [ ] **Step 4: Make and run migrations**

Run:
```bash
python manage.py makemigrations agents
```
Expected output mentions altering `receipt` and adding `invoice` on `AgentWorkflow`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_workflow_model.py -v`
Expected: all passed (existing tests + the 2 new ones).

Also run the full suite once here to catch any other place that constructs `AgentWorkflow` and would break from the docstring/field reordering (it shouldn't — nothing changed for callers passing `receipt=`):

Run: `python -m pytest -q`
Expected: all passing (same count as before plus the 2 new tests).

- [ ] **Step 6: Commit**

```bash
git add backend/apps/agents/models.py backend/apps/agents/migrations backend/tests/test_agent_workflow_model.py
git commit -m "feat(agents): generalize AgentWorkflow for invoice_chaser (nullable receipt, new invoice FK)"
```

---

## Task 5: `InvoiceChaserService`

**Files:**
- Modify: `backend/apps/agents/services.py`
- Test: `backend/tests/test_invoice_chaser_service.py`

**Interfaces:**
- Consumes: `LLMProvider`, `LLMMessage` (`apps/agents/llm.py`), `AgentWorkflow` (Task 4), `InvoiceReminderDraft` (Task 3).
- Produces: `InvoiceChaserService(llm_provider).run(workflow) -> AgentWorkflow`; module-level `_ESCALATION_LEVELS` list of `(threshold_days: int, level_key: str, tone: str)` tuples, reused by Task 7.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_invoice_chaser_service.py`:

```python
import json

import pytest

from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.agents.services import InvoiceChaserService
from apps.invoices.models import Invoice
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def _workflow_for_invoice(escalation_level="day_7"):
    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )
    return AgentWorkflow.objects.create(
        workflow_type="invoice_chaser", invoice=invoice,
        extracted_data={"escalation_level": escalation_level},
    )


_VALID_DRAFT = {"subject": "Invoice overdue", "body": "Please settle this at your earliest convenience."}


def test_well_formed_response_lands_in_needs_review_with_subject_and_body():
    workflow = _workflow_for_invoice()
    provider = FakeLLMProvider(response=json.dumps(_VALID_DRAFT))

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["subject"] == "Invoice overdue"
    assert workflow.extracted_data["body"] == _VALID_DRAFT["body"]
    assert workflow.error_message == ""


def test_escalation_level_survives_alongside_the_draft():
    workflow = _workflow_for_invoice(escalation_level="day_14")
    provider = FakeLLMProvider(response=json.dumps(_VALID_DRAFT))

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.extracted_data["escalation_level"] == "day_14"


def test_response_wrapped_in_a_markdown_code_fence_still_parses():
    workflow = _workflow_for_invoice()
    fenced = "```json\n" + json.dumps(_VALID_DRAFT) + "\n```"
    provider = FakeLLMProvider(response=fenced)

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["subject"] == "Invoice overdue"


def test_malformed_json_lands_in_needs_review_with_an_error_and_keeps_escalation_level():
    workflow = _workflow_for_invoice(escalation_level="day_1")
    provider = FakeLLMProvider(response="not json at all")

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == {"escalation_level": "day_1"}
    assert "Could not draft a reminder" in workflow.error_message


def test_response_failing_schema_validation_lands_in_needs_review_with_an_error():
    workflow = _workflow_for_invoice()
    provider = FakeLLMProvider(response=json.dumps({"subject": "", "body": "x"}))

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.error_message != ""


def test_the_prompt_names_the_client_and_amount():
    workflow = _workflow_for_invoice()
    provider = FakeLLMProvider(response=json.dumps(_VALID_DRAFT))

    InvoiceChaserService(provider).run(workflow)

    user_message = provider.calls[0][1]
    assert "Acme" in user_message.content
    assert "100.00" in user_message.content
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_invoice_chaser_service.py -v`
Expected: FAIL (`ImportError: cannot import name 'InvoiceChaserService'`).

- [ ] **Step 3: Write the service**

Edit `backend/apps/agents/services.py`. Add imports at the top:

```python
from apps.invoices.schemas import InvoiceReminderDraft
```

Add near the top, after `_SYSTEM_PROMPT` (the receipt-processor one):

```python
_INVOICE_CHASER_SYSTEM_PROMPT = (
    "You are an accounts-receivable assistant drafting a reminder email about an "
    "overdue invoice. Respond with ONLY a JSON object (no markdown, no commentary) "
    'matching this shape: {"subject": str, "body": str}. Match the requested tone.'
)

# (threshold_days, level_key, tone) -- shared with InvoiceChaserScheduler (Task 7).
# Deliberately a flat constant, not a per-tenant rules model (see design spec).
_ESCALATION_LEVELS = [
    (1, "day_1", "a polite reminder"),
    (7, "day_7", "a polite reminder"),
    (14, "day_14", "a firmer follow-up"),
    (30, "day_30", "a final notice"),
]


def _tone_for_level(level_key):
    for _, key, tone in _ESCALATION_LEVELS:
        if key == level_key:
            return tone
    return "a reminder"
```

Add the service class, after `ReceiptProcessorService`:

```python
class InvoiceChaserService:
    """Runs the Invoice Chaser agent against one AgentWorkflow's invoice.

    Same shape as ReceiptProcessorService: inject an LLMProvider, call it, validate
    the result through a Pydantic schema before it touches the workflow row.
    """

    def __init__(self, llm_provider: LLMProvider):
        self._llm = llm_provider

    def run(self, workflow: AgentWorkflow) -> AgentWorkflow:
        workflow.mark_running()
        invoice = workflow.invoice
        tone = _tone_for_level(workflow.extracted_data.get("escalation_level"))
        try:
            response = self._llm.complete(self._build_messages(invoice, tone))
            draft = InvoiceReminderDraft(**json.loads(_strip_code_fence(response.content)))
        except (json.JSONDecodeError, ValidationError) as exc:
            workflow.mark_needs_review(
                extracted_data=workflow.extracted_data,
                error_message=f"Could not draft a reminder for this invoice: {exc}",
            )
            return workflow
        workflow.mark_needs_review(
            extracted_data={**workflow.extracted_data, **draft.model_dump(mode="json")}
        )
        return workflow

    @staticmethod
    def _build_messages(invoice, tone) -> list[LLMMessage]:
        return [
            LLMMessage(role="system", content=_INVOICE_CHASER_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    f"Draft {tone} to {invoice.client_name} <{invoice.client_email}> "
                    f"about their invoice for {invoice.amount} {invoice.currency}, "
                    f"which was due on {invoice.due_date}."
                ),
            ),
        ]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_invoice_chaser_service.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the full suite to check nothing broke**

Run: `python -m pytest -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/agents/services.py backend/tests/test_invoice_chaser_service.py
git commit -m "feat(agents): add InvoiceChaserService"
```

---

## Task 6: `run_invoice_chaser` Celery task

**Files:**
- Modify: `backend/apps/agents/tasks.py`
- Test: `backend/tests/test_invoice_chaser_task.py`

**Interfaces:**
- Consumes: `InvoiceChaserService` (Task 5), `GeminiProvider.from_settings` (existing), `TenantBoundTask` (existing).
- Produces: `run_invoice_chaser(workflow_id)` — a `TenantBoundTask`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_invoice_chaser_task.py`:

```python
import json

import pytest

from apps.agents import tasks
from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.invoices.models import Invoice
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def _workflow(tenant):
    context.set_current_tenant(tenant.id)
    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )
    workflow = AgentWorkflow.objects.create(
        workflow_type="invoice_chaser", invoice=invoice,
        extracted_data={"escalation_level": "day_7"},
    )
    context.clear_current_tenant()
    return workflow


def test_task_binds_tenant_context_and_runs_the_chaser(monkeypatch):
    tenant = TenantFactory()
    workflow = _workflow(tenant)

    fake = FakeLLMProvider(
        response=json.dumps({"subject": "Invoice overdue", "body": "Please pay soon."})
    )
    monkeypatch.setattr(
        tasks.GeminiProvider, "from_settings", staticmethod(lambda api_key, model: fake)
    )

    tasks.run_invoice_chaser.apply(
        kwargs={"tenant_id": tenant.id, "workflow_id": workflow.id}
    ).get()

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["subject"] == "Invoice overdue"
    assert context.get_current_tenant_id() is None


def test_run_invoice_chaser_can_be_dispatched_via_delay_not_just_apply(monkeypatch):
    """Same regression class as test_tasks.py -- .apply() never exercises Celery's
    apply_async pre-flight kwarg check. TenantBoundTask.typing = False already fixes
    this for every task built on it, but confirm it holds for this new one too."""
    tenant = TenantFactory()
    workflow = _workflow(tenant)

    fake = FakeLLMProvider(
        response=json.dumps({"subject": "Invoice overdue", "body": "Please pay soon."})
    )
    monkeypatch.setattr(
        tasks.GeminiProvider, "from_settings", staticmethod(lambda api_key, model: fake)
    )

    tasks.run_invoice_chaser.app.conf.task_always_eager = True
    try:
        result = tasks.run_invoice_chaser.delay(tenant_id=tenant.id, workflow_id=workflow.id)
        result.get()
    finally:
        tasks.run_invoice_chaser.app.conf.task_always_eager = False

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_invoice_chaser_task.py -v`
Expected: FAIL (`AttributeError: module 'apps.agents.tasks' has no attribute 'run_invoice_chaser'`).

- [ ] **Step 3: Write the task**

Edit `backend/apps/agents/tasks.py`. Change the import line and add the new task:

```python
from .services import InvoiceChaserService, ReceiptProcessorService
```

```python
@app.task(base=TenantBoundTask, bind=False)
def run_invoice_chaser(workflow_id):
    """Thin Celery entrypoint, same shape as run_receipt_processor."""
    workflow = AgentWorkflow.objects.get(id=workflow_id)
    provider = GeminiProvider.from_settings(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
    InvoiceChaserService(provider).run(workflow)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_invoice_chaser_task.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/agents/tasks.py backend/tests/test_invoice_chaser_task.py
git commit -m "feat(agents): add run_invoice_chaser Celery task"
```

---

## Task 7: `InvoiceChaserScheduler`

**Files:**
- Modify: `backend/apps/agents/services.py`
- Test: `backend/tests/test_invoice_chaser_scheduler.py`

**Interfaces:**
- Consumes: `Invoice` (Task 1), `_ESCALATION_LEVELS` (Task 5), `run_invoice_chaser` (Task 6, imported locally to avoid a circular import same as `start_receipt_processing` does for `run_receipt_processor`).
- Produces: `InvoiceChaserScheduler.scan_and_dispatch() -> list[AgentWorkflow]`. Runs within whatever tenant is already set in context — it does not set one itself (Task 8's task does that, once per tenant).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_invoice_chaser_scheduler.py`:

```python
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.agents import tasks
from apps.agents.models import AgentWorkflow
from apps.agents.services import InvoiceChaserScheduler
from apps.invoices.models import Invoice
from apps.invoices.services import InvoiceService
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def _invoice_overdue_by(days, status=Invoice.Status.SENT):
    today = timezone.localdate()
    due = today - timedelta(days=days)
    return InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date=due - timedelta(days=15), due_date=due, status=status,
    )


def test_invoice_at_first_threshold_starts_a_workflow(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: calls.append(kw))
    invoice = _invoice_overdue_by(1)

    started = InvoiceChaserScheduler.scan_and_dispatch()

    assert len(started) == 1
    workflow = started[0]
    assert workflow.workflow_type == "invoice_chaser"
    assert workflow.invoice_id == invoice.id
    assert workflow.extracted_data == {"escalation_level": "day_1"}
    assert calls == [{"tenant_id": invoice.tenant_id, "workflow_id": workflow.id}]


def test_invoice_overdue_by_20_days_gets_the_14_day_level_not_7(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    _invoice_overdue_by(20)

    started = InvoiceChaserScheduler.scan_and_dispatch()

    assert started[0].extracted_data["escalation_level"] == "day_14"


def test_invoice_not_yet_overdue_is_skipped(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    _invoice_overdue_by(0)

    assert InvoiceChaserScheduler.scan_and_dispatch() == []


@pytest.mark.parametrize("status", [Invoice.Status.PAID, Invoice.Status.VOID, Invoice.Status.DRAFT])
def test_invoices_in_excluded_statuses_are_skipped(monkeypatch, status):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    _invoice_overdue_by(10, status=status)

    assert InvoiceChaserScheduler.scan_and_dispatch() == []


def test_already_reminded_at_this_level_is_not_duplicated(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    invoice = _invoice_overdue_by(7)

    first_run = InvoiceChaserScheduler.scan_and_dispatch()
    second_run = InvoiceChaserScheduler.scan_and_dispatch()

    assert len(first_run) == 1
    assert second_run == []
    assert AgentWorkflow.objects.filter(invoice=invoice, workflow_type="invoice_chaser").count() == 1


def test_crossing_a_new_threshold_starts_a_second_workflow(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    invoice = _invoice_overdue_by(7)
    InvoiceChaserScheduler.scan_and_dispatch()  # day_7 workflow already exists now

    invoice.due_date = timezone.localdate() - timedelta(days=14)
    invoice.save()
    second_run = InvoiceChaserScheduler.scan_and_dispatch()

    assert len(second_run) == 1
    assert second_run[0].extracted_data["escalation_level"] == "day_14"
    assert AgentWorkflow.objects.filter(invoice=invoice, workflow_type="invoice_chaser").count() == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_invoice_chaser_scheduler.py -v`
Expected: FAIL (`ImportError: cannot import name 'InvoiceChaserScheduler'`).

- [ ] **Step 3: Write the scheduler**

Edit `backend/apps/agents/services.py`. Add imports at the top:

```python
from django.utils import timezone

from apps.invoices.models import Invoice
```

Add the class, after `InvoiceChaserService`:

```python
class InvoiceChaserScheduler:
    """Finds overdue invoices that just crossed a new escalation threshold and starts
    one AgentWorkflow per (invoice, threshold). Runs within the caller's tenant
    context -- it does not set one itself. apps.agents.tasks.scan_overdue_invoices
    (the Celery beat task) sets that context once per tenant and calls this."""

    _EXCLUDED_STATUSES = [Invoice.Status.PAID, Invoice.Status.VOID, Invoice.Status.DRAFT]

    @staticmethod
    def scan_and_dispatch() -> list[AgentWorkflow]:
        from .tasks import run_invoice_chaser  # local import, same reason as start_receipt_processing

        today = timezone.localdate()
        started = []
        chaseable = Invoice.objects.exclude(
            status__in=InvoiceChaserScheduler._EXCLUDED_STATUSES
        ).filter(due_date__lt=today)

        for invoice in chaseable:
            days_overdue = (today - invoice.due_date).days
            level = _reached_level(days_overdue)
            if level is None:
                continue
            _, level_key, _tone = level
            already_reminded = AgentWorkflow.objects.filter(
                invoice=invoice, workflow_type="invoice_chaser",
                extracted_data__escalation_level=level_key,
            ).exists()
            if already_reminded:
                continue
            workflow = AgentWorkflow.objects.create(
                workflow_type="invoice_chaser", invoice=invoice,
                extracted_data={"escalation_level": level_key},
            )
            run_invoice_chaser.delay(tenant_id=invoice.tenant_id, workflow_id=workflow.id)
            started.append(workflow)
        return started


def _reached_level(days_overdue):
    reached = None
    for threshold_days, level_key, tone in _ESCALATION_LEVELS:
        if days_overdue >= threshold_days:
            reached = (threshold_days, level_key, tone)
    return reached
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_invoice_chaser_scheduler.py -v`
Expected: 8 passed (6 tests, one parametrized 3 ways = 8 total).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/agents/services.py backend/tests/test_invoice_chaser_scheduler.py
git commit -m "feat(agents): add InvoiceChaserScheduler (escalation threshold + dedup logic)"
```

---

## Task 8: `scan_overdue_invoices` beat task

**Files:**
- Modify: `backend/apps/agents/tasks.py`
- Modify: `backend/config/settings/base.py` (register `CELERY_BEAT_SCHEDULE`)
- Test: `backend/tests/test_scan_overdue_invoices_task.py`

**Interfaces:**
- Consumes: `InvoiceChaserScheduler.scan_and_dispatch` (Task 7), `Tenant` (existing).
- Produces: `scan_overdue_invoices()` — a plain Celery task (not `TenantBoundTask`: it manages *multiple* tenants itself, one at a time, rather than being bound to a single one from a dispatch kwarg).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scan_overdue_invoices_task.py`:

```python
import pytest

from apps.agents import services, tasks
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def test_scan_overdue_invoices_runs_the_scheduler_once_per_tenant_and_clears_context(monkeypatch):
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    seen_tenants = []

    def fake_scan():
        seen_tenants.append(context.get_current_tenant_id())
        return []

    monkeypatch.setattr(services.InvoiceChaserScheduler, "scan_and_dispatch", staticmethod(fake_scan))

    tasks.scan_overdue_invoices.apply().get()

    assert set(seen_tenants) == {tenant_a.id, tenant_b.id}
    assert context.get_current_tenant_id() is None


def test_scan_overdue_invoices_clears_context_even_if_one_tenant_errors(monkeypatch):
    tenant_a = TenantFactory()
    TenantFactory()

    def flaky_scan():
        if context.get_current_tenant_id() == tenant_a.id:
            raise RuntimeError("boom")
        return []

    monkeypatch.setattr(services.InvoiceChaserScheduler, "scan_and_dispatch", staticmethod(flaky_scan))

    with pytest.raises(RuntimeError):
        tasks.scan_overdue_invoices.apply().get()

    assert context.get_current_tenant_id() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_scan_overdue_invoices_task.py -v`
Expected: FAIL (`AttributeError: module 'apps.agents.tasks' has no attribute 'scan_overdue_invoices'`).

- [ ] **Step 3: Write the task**

Edit `backend/apps/agents/tasks.py`. Add imports:

```python
from apps.tenancy import context
from apps.tenancy.models import Tenant

from .services import InvoiceChaserScheduler
```

Add the task:

```python
@app.task(bind=False)
def scan_overdue_invoices():
    """Celery-beat-scheduled (daily). Not a TenantBoundTask: nothing dispatches this
    with a single tenant_id kwarg -- it owns iterating every tenant itself, setting
    and clearing context around each one so InvoiceChaserScheduler's tenant-scoped
    queries are safe."""
    for tenant in Tenant.objects.all():
        context.set_current_tenant(tenant.id)
        try:
            InvoiceChaserScheduler.scan_and_dispatch()
        finally:
            context.clear_current_tenant()
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_scan_overdue_invoices_task.py -v`
Expected: 2 passed.

- [ ] **Step 5: Wire it into Celery beat**

Edit `backend/config/settings/base.py`. Add near the existing `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` lines:

```python
from celery.schedules import crontab

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BEAT_SCHEDULE = {
    "scan-overdue-invoices-daily": {
        "task": "apps.agents.tasks.scan_overdue_invoices",
        "schedule": crontab(hour=6, minute=0),
    },
}
```

(Add the `from celery.schedules import crontab` import at the top of the file with the other imports, not inline.)

- [ ] **Step 6: Verify settings load cleanly**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add backend/apps/agents/tasks.py backend/config/settings/base.py backend/tests/test_scan_overdue_invoices_task.py
git commit -m "feat(agents): add scan_overdue_invoices beat task, scheduled daily"
```

---

## Task 9: Generalize `AgentWorkflowService.approve()`/`.reject()`

**Files:**
- Modify: `backend/apps/agents/services.py`
- Modify: `backend/apps/agents/serializers.py` (`ConfirmWorkflowSerializer`)
- Test: `backend/tests/test_agent_workflow_service.py` (add new tests; existing ones must keep passing unchanged)

**Interfaces:**
- Consumes: `Invoice` (Task 1), `AgentWorkflow` (Task 4).
- Produces: `AgentWorkflowService.approve(workflow, *, reviewed_by, overrides=None)` now branches on `workflow.workflow_type`; for `"invoice_chaser"` it does not create an `Expense` and writes `AuditLog(action="reminder_sent")` instead. `ConfirmWorkflowSerializer` gains optional `subject`/`body` fields.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_workflow_service.py` (add this import at the top alongside the existing ones):

```python
from apps.invoices.models import Invoice
```

Add these test functions at the bottom of the file:

```python
def _invoice_workflow(escalation_level="day_7"):
    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )
    workflow = AgentWorkflow.objects.create(
        workflow_type="invoice_chaser", invoice=invoice,
        extracted_data={"escalation_level": escalation_level},
    )
    workflow.mark_needs_review(
        extracted_data={
            "escalation_level": escalation_level,
            "subject": "Invoice overdue",
            "body": "Please pay by Friday.",
        }
    )
    return workflow


def test_approve_an_invoice_chaser_workflow_creates_no_expense():
    user = UserFactory()
    workflow = _invoice_workflow()

    AgentWorkflowService.approve(workflow, reviewed_by=user)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.APPROVED
    assert workflow.resulting_expense is None
    assert workflow.reviewed_by_id == user.id


def test_approve_an_invoice_chaser_workflow_writes_a_reminder_sent_audit_log():
    user = UserFactory()
    workflow = _invoice_workflow()

    AgentWorkflowService.approve(workflow, reviewed_by=user)

    log = AuditLog.objects.get(workflow=workflow)
    assert log.actor_id == user.id
    assert log.action == "reminder_sent"
    assert log.metadata["subject"] == "Invoice overdue"
    assert log.metadata["body"] == "Please pay by Friday."
    assert log.metadata["to"] == "ap@acme.test"


def test_approve_an_invoice_chaser_workflow_lets_a_human_edit_the_draft_first():
    user = UserFactory()
    workflow = _invoice_workflow()

    AgentWorkflowService.approve(
        workflow, reviewed_by=user, overrides={"subject": "URGENT: invoice overdue"}
    )

    log = AuditLog.objects.get(workflow=workflow)
    assert log.metadata["subject"] == "URGENT: invoice overdue"
    assert log.metadata["body"] == "Please pay by Friday."  # untouched override stays as drafted


def test_reject_an_invoice_chaser_workflow_needs_no_special_handling():
    user = UserFactory()
    workflow = _invoice_workflow()

    AgentWorkflowService.reject(workflow, reviewed_by=user)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.REJECTED
    log = AuditLog.objects.get(workflow=workflow)
    assert log.action == "rejected"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_agent_workflow_service.py -v`
Expected: the 4 new tests FAIL — `approve()`'s current body reads `workflow.receipt` unconditionally and will raise/misbehave for an invoice-backed workflow (e.g. `AttributeError` or creating a garbage `Expense` from missing `vendor`/`amount` keys).

- [ ] **Step 3: Generalize the service**

Edit `backend/apps/agents/services.py`. Replace the `approve` method on `AgentWorkflowService`:

```python
    @staticmethod
    def approve(workflow: AgentWorkflow, *, reviewed_by, overrides: dict | None = None) -> AgentWorkflow:
        if workflow.workflow_type == "invoice_chaser":
            return AgentWorkflowService._approve_invoice_chaser(
                workflow, reviewed_by=reviewed_by, overrides=overrides
            )
        return AgentWorkflowService._approve_receipt_processor(
            workflow, reviewed_by=reviewed_by, overrides=overrides
        )

    @staticmethod
    def _approve_receipt_processor(workflow: AgentWorkflow, *, reviewed_by, overrides) -> AgentWorkflow:
        data = workflow.extracted_data
        fields = {
            "vendor": data.get("vendor"),
            "amount": data.get("amount"),
            "currency": data.get("currency", "USD"),
            "category": data.get("category_suggestion") or "",
            "expense_date": data.get("expense_date"),
        }
        for key, value in (overrides or {}).items():
            if value is not None:
                fields[key] = value
        expense = ExpenseService.create(
            created_by=reviewed_by, receipt=workflow.receipt, **fields
        )
        workflow.mark_approved(reviewed_by=reviewed_by, resulting_expense=expense)
        AuditLog.objects.create(
            workflow=workflow,
            actor=reviewed_by,
            action="approved",
            metadata={"resulting_expense_id": expense.id, "overrides": overrides or {}},
        )
        return workflow

    @staticmethod
    def _approve_invoice_chaser(workflow: AgentWorkflow, *, reviewed_by, overrides) -> AgentWorkflow:
        """Simulated send: writes what would have been emailed to AuditLog. No real
        SMTP/SendGrid call -- see the design spec's explicit non-goal on this."""
        data = workflow.extracted_data
        overrides = overrides or {}
        subject = overrides.get("subject") or data.get("subject")
        body = overrides.get("body") or data.get("body")
        workflow.mark_approved(reviewed_by=reviewed_by)
        AuditLog.objects.create(
            workflow=workflow,
            actor=reviewed_by,
            action="reminder_sent",
            metadata={"subject": subject, "body": body, "to": workflow.invoice.client_email},
        )
        return workflow
```

(`reject()` is unchanged — it already has no type-specific behavior.)

Edit `backend/apps/agents/serializers.py`. Add two optional fields to `ConfirmWorkflowSerializer`:

```python
class ConfirmWorkflowSerializer(serializers.Serializer):
    """Lets a human correct the AI's output before it's acted on.

    Every field is optional -- omit a field to accept what the agent produced for it.
    vendor/amount/currency/category/expense_date apply to receipt_processor workflows;
    subject/body apply to invoice_chaser ones. A given workflow only ever uses one set.
    """

    vendor = serializers.CharField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    currency = serializers.CharField(required=False, max_length=3)
    category = serializers.CharField(required=False, allow_blank=True)
    expense_date = serializers.DateField(required=False)
    subject = serializers.CharField(required=False)
    body = serializers.CharField(required=False)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_agent_workflow_service.py -v`
Expected: all passed (existing receipt-processor tests + 4 new ones).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/agents/services.py backend/apps/agents/serializers.py backend/tests/test_agent_workflow_service.py
git commit -m "feat(agents): generalize AgentWorkflowService.approve() for invoice_chaser (simulated send)"
```

---

## Task 10: `InvoiceViewSet`

**Files:**
- Create: `backend/apps/invoices/serializers.py`
- Create: `backend/apps/invoices/views.py`
- Create: `backend/apps/invoices/urls.py`
- Modify: `backend/config/urls.py`
- Test: `backend/tests/test_invoice_api.py`

**Interfaces:**
- Consumes: `Invoice`, `InvoiceService` (Task 1, 2).
- Produces: `InvoiceSerializer` (ModelSerializer, used both standalone here and nested read-only from `AgentWorkflowSerializer` in Task 11), `InvoiceViewSet` (full CRUD at `/api/invoices/`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_invoice_api.py`:

```python
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_create_invoice_via_api(authed_client):
    resp = authed_client.post(
        "/api/invoices/",
        {
            "client_name": "Staples", "client_email": "ap@staples.test", "amount": "500.00",
            "issue_date": "2026-06-01", "due_date": "2026-06-15",
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    assert resp.data["client_name"] == "Staples"
    assert resp.data["status"] == "draft"


def test_create_invoice_with_non_positive_amount_is_a_400_not_a_500(authed_client):
    resp = authed_client.post(
        "/api/invoices/",
        {
            "client_name": "Staples", "client_email": "ap@staples.test", "amount": "0",
            "issue_date": "2026-06-01", "due_date": "2026-06-15",
        },
        format="json",
    )

    assert resp.status_code == 400


def test_create_invoice_requires_authentication():
    client = APIClient()

    resp = client.post(
        "/api/invoices/",
        {
            "client_name": "Staples", "client_email": "ap@staples.test", "amount": "500.00",
            "issue_date": "2026-06-01", "due_date": "2026-06-15",
        },
        format="json",
    )

    assert resp.status_code == 401


def test_list_invoices_is_scoped_to_the_current_tenant(authed_client, other_authed_client):
    other_authed_client.post(
        "/api/invoices/",
        {
            "client_name": "Globex", "client_email": "ap@globex.test", "amount": "10.00",
            "issue_date": "2026-06-01", "due_date": "2026-06-15",
        },
        format="json",
    )
    authed_client.post(
        "/api/invoices/",
        {
            "client_name": "Staples", "client_email": "ap@staples.test", "amount": "500.00",
            "issue_date": "2026-06-01", "due_date": "2026-06-15",
        },
        format="json",
    )

    resp = authed_client.get("/api/invoices/")

    names = {row["client_name"] for row in resp.data}
    assert names == {"Staples"}


def test_invoice_from_another_tenant_is_not_found(authed_client, other_authed_client):
    create_resp = other_authed_client.post(
        "/api/invoices/",
        {
            "client_name": "Globex", "client_email": "ap@globex.test", "amount": "10.00",
            "issue_date": "2026-06-01", "due_date": "2026-06-15",
        },
        format="json",
    )

    resp = authed_client.get(f"/api/invoices/{create_resp.data['id']}/")

    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_invoice_api.py -v`
Expected: FAIL (404s — no `/api/invoices/` route yet).

- [ ] **Step 3: Write the serializer**

Create `backend/apps/invoices/serializers.py`:

```python
from rest_framework import serializers

from .models import Invoice
from .services import InvoiceService


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            "id",
            "client_name",
            "client_email",
            "amount",
            "currency",
            "issue_date",
            "due_date",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        return self._via_service(InvoiceService.create, **validated_data)

    def update(self, instance, validated_data):
        return self._via_service(InvoiceService.update, instance, **validated_data)

    @staticmethod
    def _via_service(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
```

- [ ] **Step 4: Write the view**

Create `backend/apps/invoices/views.py`:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.tenancy.permissions import IsTenantMember

from .models import Invoice
from .serializers import InvoiceSerializer


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        # Not a `queryset =` class attribute -- see ExpenseViewSet.get_queryset.
        return Invoice.objects.all()
```

- [ ] **Step 5: Wire up URLs**

Create `backend/apps/invoices/urls.py`:

```python
from rest_framework.routers import SimpleRouter

from .views import InvoiceViewSet

router = SimpleRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = router.urls
```

Edit `backend/config/urls.py`:

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.tenancy.urls")),
    path("api/", include("apps.expenses.urls")),
    path("api/", include("apps.invoices.urls")),
    path("api/", include("apps.agents.urls")),
]
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_invoice_api.py -v`
Expected: 5 passed.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all passing.

- [ ] **Step 8: Commit**

```bash
git add backend/apps/invoices/serializers.py backend/apps/invoices/views.py backend/apps/invoices/urls.py backend/config/urls.py backend/tests/test_invoice_api.py
git commit -m "feat(invoices): add InvoiceViewSet, full CRUD at /api/invoices/"
```

---

## Task 11: Nest `invoice` in `AgentWorkflowSerializer`, add query filters

**Files:**
- Modify: `backend/apps/agents/serializers.py`
- Modify: `backend/apps/agents/views.py`
- Modify: `backend/tests/test_agent_workflow_api.py` (add new tests; existing ones must keep passing)

**Interfaces:**
- Consumes: `InvoiceSerializer` (Task 10).
- Produces: `AgentWorkflowSerializer` now includes a read-only nested `invoice` field; `AgentWorkflowViewSet.get_queryset()` supports `?workflow_type=` and `?status=` filters.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_workflow_api.py` (add this import at the top):

```python
from apps.invoices.models import Invoice
```

Add at the bottom:

```python
def _needs_review_invoice_workflow(tenant):
    context.set_current_tenant(tenant.id)
    try:
        invoice = Invoice.objects.create(
            client_name="Acme", client_email="ap@acme.test", amount="100.00",
            issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
        )
        workflow = AgentWorkflow.objects.create(
            workflow_type="invoice_chaser", invoice=invoice,
            extracted_data={"escalation_level": "day_7"},
        )
        workflow.mark_needs_review(
            extracted_data={
                "escalation_level": "day_7", "subject": "Invoice overdue", "body": "Please pay.",
            }
        )
        return workflow
    finally:
        context.clear_current_tenant()


def test_workflow_detail_nests_the_invoice_when_present(authed_client):
    workflow = _needs_review_invoice_workflow(authed_client.tenant)

    resp = authed_client.get(f"/api/agent-workflows/{workflow.id}/")

    assert resp.data["invoice"]["client_name"] == "Acme"
    assert resp.data["receipt"] is None


def test_workflow_detail_nests_null_invoice_for_a_receipt_workflow(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)

    resp = authed_client.get(f"/api/agent-workflows/{workflow.id}/")

    assert resp.data["invoice"] is None


def test_confirm_an_invoice_chaser_workflow_writes_a_reminder_sent_audit_log(authed_client):
    workflow = _needs_review_invoice_workflow(authed_client.tenant)

    resp = authed_client.post(f"/api/agent-workflows/{workflow.id}/confirm/", {}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["status"] == "approved"
    assert resp.data["resulting_expense"] is None
    logs = authed_client.get(f"/api/audit-logs/?workflow={workflow.id}").data
    assert logs[0]["action"] == "reminder_sent"


def test_filter_workflows_by_workflow_type(authed_client):
    receipt_workflow = _needs_review_workflow(authed_client.tenant)
    invoice_workflow = _needs_review_invoice_workflow(authed_client.tenant)

    resp = authed_client.get("/api/agent-workflows/?workflow_type=invoice_chaser")

    ids = [w["id"] for w in resp.data]
    assert ids == [invoice_workflow.id]
    assert receipt_workflow.id not in ids


def test_filter_workflows_by_status(authed_client):
    needs_review = _needs_review_workflow(authed_client.tenant)

    resp = authed_client.get("/api/agent-workflows/?status=needs_review")

    assert [w["id"] for w in resp.data] == [needs_review.id]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_agent_workflow_api.py -v`
Expected: FAIL — `resp.data["invoice"]` raises `KeyError` (field doesn't exist yet); the filter tests return unfiltered lists.

- [ ] **Step 3: Update the serializer**

Edit `backend/apps/agents/serializers.py`:

```python
from apps.expenses.serializers import ReceiptSerializer
from apps.invoices.serializers import InvoiceSerializer

from .models import AgentWorkflow, AuditLog


class AgentWorkflowSerializer(serializers.ModelSerializer):
    receipt = ReceiptSerializer(read_only=True)
    invoice = InvoiceSerializer(read_only=True)

    class Meta:
        model = AgentWorkflow
        fields = [
            "id",
            "workflow_type",
            "status",
            "receipt",
            "invoice",
            "extracted_data",
            "error_message",
            "resulting_expense",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
```

- [ ] **Step 4: Update the viewset**

Edit `backend/apps/agents/views.py`, replace `AgentWorkflowViewSet.get_queryset`:

```python
    def get_queryset(self):
        # See ExpenseViewSet.get_queryset for why this isn't a `queryset =` class attribute.
        qs = AgentWorkflow.objects.all()
        workflow_type = self.request.query_params.get("workflow_type")
        if workflow_type:
            qs = qs.filter(workflow_type=workflow_type)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_agent_workflow_api.py -v`
Expected: all passed (existing + 5 new).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: all passing. This is the last backend task — note the new total passing count for the manual-verification writeup later.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/agents/serializers.py backend/apps/agents/views.py backend/tests/test_agent_workflow_api.py
git commit -m "feat(agents): nest invoice in AgentWorkflowSerializer, filter workflows by type/status"
```

---

## Task 12: Frontend types + API client

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: `Invoice` interface; `AgentWorkflow.invoice: Invoice | null`; `ExtractedData` merged to cover both agents; `api.listInvoices(token)`, `api.listWorkflows(params, token)`.

No test file for this task — it's pure type/fetch-wrapper additions with no runtime logic of its own; Task 13's hooks and Task 14/15's components exercise them, and this project has no separate frontend unit-test setup for `lib/` (consistent with `api.ts` having none today).

- [ ] **Step 1: Edit `frontend/src/lib/types.ts`**

Replace the `ExtractedReceiptData` interface and everything after it with:

```typescript
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
  created_at: string;
  updated_at: string;
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
```

(Leave `WorkflowStatus`, `Receipt`, and `LineItem` at the top of the file exactly as they are — only `ExtractedReceiptData` is renamed/extended to `ExtractedWorkflowData`, and `AgentWorkflow`/`ConfirmWorkflowOverrides` gain the fields shown.)

- [ ] **Step 2: Edit `frontend/src/lib/api.ts`**

Add the `Invoice` import and two new functions:

```typescript
import type {
  AgentWorkflow,
  ConfirmWorkflowOverrides,
  Invoice,
} from "@/lib/types";
```

Add at the end of the file:

```typescript
export function listInvoices(token: string) {
  return request<Invoice[]>("/invoices/", {}, token);
}

export function listWorkflows(
  params: { workflow_type?: string; status?: string },
  token: string
) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v) as [string, string][]
  ).toString();
  return request<AgentWorkflow[]>(
    `/agent-workflows/${query ? `?${query}` : ""}`,
    {},
    token
  );
}
```

- [ ] **Step 3: Verify the frontend still builds**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors (this catches any mismatched field name from Steps 1–2 immediately, before any component consumes them).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): add Invoice type and workflow-list/invoice-list API calls"
```

---

## Task 13: `useInvoices()` and `usePendingReminders()` hooks

**Files:**
- Create: `frontend/src/hooks/use-invoices.ts`

**Interfaces:**
- Consumes: `api.listInvoices`, `api.listWorkflows` (Task 12), `useAuth` (existing).
- Produces: `useInvoices()`, `usePendingReminders()` — both React Query `useQuery` hooks.

- [ ] **Step 1: Create the hooks file**

Create `frontend/src/hooks/use-invoices.ts`:

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";

import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function useInvoices() {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["invoices"],
    queryFn: () => api.listInvoices(token as string),
    enabled: !!token,
  });
}

// The reminder inbox: needs_review invoice_chaser workflows a human hasn't acted on
// yet. Unlike receipts (one upload -> one known workflow id, tracked in Zustand),
// these appear on their own from the daily scheduler -- so this polls a *list*
// instead of a single id. 10s is slower than the 2s single-workflow poll in
// use-receipts.ts since nothing here is "actively processing" moment-to-moment.
export function usePendingReminders() {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["agent-workflows", { workflow_type: "invoice_chaser", status: "needs_review" }],
    queryFn: () =>
      api.listWorkflows(
        { workflow_type: "invoice_chaser", status: "needs_review" },
        token as string
      ),
    enabled: !!token,
    refetchInterval: 10000,
  });
}
```

- [ ] **Step 2: Verify the frontend still builds**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-invoices.ts
git commit -m "feat(frontend): add useInvoices and usePendingReminders hooks"
```

---

## Task 14: `invoice-list.tsx`

**Files:**
- Create: `frontend/src/components/invoice-list.tsx`

**Interfaces:**
- Consumes: `useInvoices` (Task 13), `Card`/`Badge` (existing shadcn components).
- Produces: `InvoiceList` component. Not wired into `page.tsx` yet — Task 15 does the
  one page.tsx edit that wires in both `InvoiceList` and `ReminderInbox` together, so
  each task here stays independently buildable (`next build` type-checks the whole
  project regardless of what's imported from a page, so this is fully verifiable on
  its own).

- [ ] **Step 1: Create the component**

Create `frontend/src/components/invoice-list.tsx`:

```tsx
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
```

- [ ] **Step 2: Verify the frontend builds**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/invoice-list.tsx
git commit -m "feat(frontend): add invoice-list component"
```

---

## Task 15: Reminder review UI, final page wiring

**Files:**
- Create: `frontend/src/components/reminder-review.tsx`
- Create: `frontend/src/components/reminder-inbox.tsx`
- Modify: `frontend/src/components/workflow-panel.tsx`
- Modify: `frontend/src/app/page.tsx`

**Interfaces:**
- Consumes: `useConfirmWorkflow`, `useRejectWorkflow` (existing, from `use-receipts.ts` — generic enough already, work for any workflow id), `usePendingReminders` (Task 13), `useWorkflowUiStore` (existing), `InvoiceList` (Task 14).

- [ ] **Step 1: Create the reminder review form**

Create `frontend/src/components/reminder-review.tsx`:

```tsx
"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useConfirmWorkflow, useRejectWorkflow } from "@/hooks/use-receipts";
import type { AgentWorkflow } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const schema = z.object({
  subject: z.string().min(1, "Enter a subject."),
  body: z.string().min(1, "Enter a message."),
});
type FormValues = z.infer<typeof schema>;

export function ReminderReview({ workflow }: { workflow: AgentWorkflow }) {
  const confirm = useConfirmWorkflow(workflow.id);
  const reject = useRejectWorkflow(workflow.id);
  const data = workflow.extracted_data;

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      subject: data.subject ?? "",
      body: data.body ?? "",
    },
  });

  function onSubmit(values: FormValues) {
    confirm.mutate(values, {
      onSuccess: () => toast.success("Reminder sent."),
      onError: () => toast.error("Couldn't send that reminder."),
    });
  }

  function onReject() {
    reject.mutate(undefined, {
      onSuccess: () => toast("Dismissed — no reminder was sent."),
      onError: () => toast.error("Couldn't dismiss that reminder."),
    });
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-3">
      {workflow.invoice && (
        <p className="text-sm text-muted-foreground">
          To {workflow.invoice.client_name} ({workflow.invoice.client_email}) —{" "}
          {workflow.invoice.amount} {workflow.invoice.currency}, due{" "}
          {workflow.invoice.due_date}
        </p>
      )}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="subject">Subject</Label>
        <Input id="subject" {...register("subject")} />
        {errors.subject && (
          <p className="text-sm text-destructive">{errors.subject.message}</p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="body">Message</Label>
        <textarea
          id="body"
          rows={5}
          className="rounded-md border border-border bg-transparent px-3 py-2 text-sm"
          {...register("body")}
        />
        {errors.body && (
          <p className="text-sm text-destructive">{errors.body.message}</p>
        )}
      </div>
      <div className="mt-1 flex gap-2">
        <Button type="submit" disabled={confirm.isPending}>
          {confirm.isPending ? "Sending…" : "Send"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onReject}
          disabled={reject.isPending}
        >
          Dismiss
        </Button>
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Create the reminder inbox**

Create `frontend/src/components/reminder-inbox.tsx`:

```tsx
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
```

- [ ] **Step 3: Generalize `workflow-panel.tsx` to branch on `workflow_type`**

Edit `frontend/src/components/workflow-panel.tsx`:

```tsx
"use client";

import { useWorkflow } from "@/hooks/use-receipts";
import { useWorkflowUiStore } from "@/store/workflow-ui-store";
import type { WorkflowStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ReviewForm } from "@/components/review-form";
import { ReminderReview } from "@/components/reminder-review";

const STATUS_LABEL: Record<WorkflowStatus, string> = {
  pending: "Waiting to be processed",
  running: "Working on it…",
  needs_review: "Ready for your review",
  approved: "Approved",
  rejected: "Rejected",
};

const STATUS_VARIANT: Record<
  WorkflowStatus,
  "default" | "secondary" | "destructive"
> = {
  pending: "secondary",
  running: "secondary",
  needs_review: "default",
  approved: "default",
  rejected: "destructive",
};

export function WorkflowPanel() {
  const activeWorkflowId = useWorkflowUiStore((s) => s.activeWorkflowId);
  const { data: workflow, isLoading } = useWorkflow(activeWorkflowId);

  if (!activeWorkflowId) return null;
  if (isLoading || !workflow) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const isInvoiceChaser = workflow.workflow_type === "invoice_chaser";
  const title = isInvoiceChaser
    ? `Invoice reminder #${workflow.invoice?.id ?? workflow.id}`
    : `Receipt #${workflow.receipt?.id ?? workflow.id}`;

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">{title}</CardTitle>
        <Badge variant={STATUS_VARIANT[workflow.status]}>
          {STATUS_LABEL[workflow.status]}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {(workflow.status === "pending" || workflow.status === "running") && (
          <p className="text-sm text-muted-foreground">
            This updates automatically — no need to refresh.
          </p>
        )}
        {workflow.status === "needs_review" &&
          (isInvoiceChaser ? (
            <ReminderReview workflow={workflow} />
          ) : (
            <ReviewForm workflow={workflow} />
          ))}
        {workflow.status === "approved" && isInvoiceChaser && (
          <p className="text-sm text-muted-foreground">Reminder sent.</p>
        )}
        {workflow.status === "approved" && !isInvoiceChaser && (
          <p className="text-sm text-muted-foreground">
            Saved as expense #{workflow.resulting_expense}.
          </p>
        )}
        {workflow.status === "rejected" && isInvoiceChaser && (
          <p className="text-sm text-muted-foreground">
            Dismissed — no reminder was sent.
          </p>
        )}
        {workflow.status === "rejected" && !isInvoiceChaser && (
          <p className="text-sm text-muted-foreground">
            This receipt was rejected — no expense was created.
          </p>
        )}
        {workflow.error_message && (
          <p className="text-sm text-destructive">{workflow.error_message}</p>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: Wire `InvoiceList` and `ReminderInbox` into the page**

Edit `frontend/src/app/page.tsx`:

```tsx
"use client";

import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";
import { UploadZone } from "@/components/upload-zone";
import { WorkflowPanel } from "@/components/workflow-panel";
import { InvoiceList } from "@/components/invoice-list";
import { ReminderInbox } from "@/components/reminder-inbox";
import { Button } from "@/components/ui/button";

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
```

- [ ] **Step 5: Verify the frontend builds**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/reminder-review.tsx frontend/src/components/reminder-inbox.tsx frontend/src/components/workflow-panel.tsx frontend/src/app/page.tsx
git commit -m "feat(frontend): add reminder review/inbox UI, generalize workflow-panel by workflow_type, wire into page"
```

---

## Task 16: Manual end-to-end verification

Not TDD — this is the "a green pytest run is not proof it works" discipline from step 6 of the Receipt Processor slice, applied here. No code changes; this task is a checklist to run and record results for, updating `HANDOFF.md` afterward (out of scope for this plan file itself, but do it once verification passes).

**Prerequisites:** the real dev stack running — see `HANDOFF.md`'s "Running the full stack without Docker" section (backend on :8000 via `scripts/dev-server.sh`, frontend on :3000 via `npm run dev`, Redis + a Celery worker consuming the queue). A real `GEMINI_API_KEY` is already set per `HANDOFF.md`.

- [ ] **Step 1:** Sign in, seed a tenant/user the same way as the existing auth smoke test (see `README.md`).
- [ ] **Step 2:** Create a real overdue invoice via the API (not the UI — creation wasn't part of this slice's frontend):
  ```bash
  curl -X POST http://localhost:8000/api/invoices/ \
    -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
    -d '{"client_name":"Acme Test Co","client_email":"you@yourinbox.test","amount":"250.00","issue_date":"2026-06-01","due_date":"2026-06-20","status":"sent"}'
  ```
  Pick a `due_date` far enough in the past to be at least 1 day overdue relative to today.
- [ ] **Step 3:** Trigger the scan manually (don't wait for the daily beat schedule):
  ```bash
  cd backend && source .venv/bin/activate
  python manage.py shell -c "from apps.agents.tasks import scan_overdue_invoices; scan_overdue_invoices()"
  ```
- [ ] **Step 4:** Confirm a new `AgentWorkflow` was created and the Celery worker picked it up and moved it to `needs_review`:
  ```bash
  curl -s http://localhost:8000/api/agent-workflows/?workflow_type=invoice_chaser -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
  ```
  Expect one entry with `"status": "needs_review"` and a non-empty `extracted_data.subject`/`.body`.
- [ ] **Step 5:** Open `localhost:3000`, confirm the "Reminders to review" inbox shows the new reminder, click it, confirm `ReminderReview` renders the drafted subject/body, click "Send".
- [ ] **Step 6:** Fetch `/api/audit-logs/?workflow=<id>` and confirm one `reminder_sent` row with the expected `subject`/`body`/`to`.
- [ ] **Step 7:** Run the full backend suite one more time and record the new total:
  ```bash
  cd backend && python -m pytest -q
  ```
- [ ] **Step 8:** Update `HANDOFF.md`'s TL;DR and "What's NOT done yet" sections to reflect Invoice Chaser being done, following the same writeup style as steps 1–7 (what was built, the real bugs found if any, the new passing test count). This is documentation, not code — do it as its own commit.
