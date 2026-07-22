import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agents import tasks
from apps.agents.models import AgentWorkflow, AuditLog
from apps.agents.services import AgentWorkflowService
from apps.expenses.models import Receipt
from apps.invoices.models import Invoice
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def _receipt(user):
    return Receipt.objects.create(
        uploaded_by=user,
        file=SimpleUploadedFile("r.jpg", b"bytes", content_type="image/jpeg"),
    )


def test_start_receipt_processing_creates_a_pending_workflow_and_enqueues_the_task(
    tenant_context, monkeypatch
):
    user = UserFactory()
    receipt = _receipt(user)
    calls = []
    monkeypatch.setattr(tasks.run_receipt_processor, "delay", lambda **kw: calls.append(kw))

    workflow = AgentWorkflowService.start_receipt_processing(receipt)

    assert workflow.status == AgentWorkflow.Status.PENDING
    assert workflow.receipt_id == receipt.id
    assert calls == [{"tenant_id": tenant_context.id, "workflow_id": workflow.id}]


def test_approve_creates_an_expense_from_extracted_data():
    user = UserFactory()
    receipt = _receipt(user)
    workflow = AgentWorkflow.objects.create(receipt=receipt)
    workflow.mark_needs_review(
        extracted_data={
            "vendor": "Staples",
            "amount": "42.50",
            "currency": "USD",
            "category_suggestion": "office supplies",
            "expense_date": "2026-07-01",
        }
    )

    AgentWorkflowService.approve(workflow, reviewed_by=user)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.APPROVED
    assert workflow.resulting_expense is not None
    assert workflow.resulting_expense.vendor == "Staples"
    assert workflow.resulting_expense.category == "office supplies"
    assert workflow.resulting_expense.receipt_id == receipt.id
    assert workflow.reviewed_by_id == user.id


def test_pending_receipt_processor_workflow_keeps_its_existing_direct_approve_behavior():
    user = UserFactory()
    receipt = _receipt(user)
    workflow = AgentWorkflow.objects.create(
        receipt=receipt,
        extracted_data={
            "vendor": "Staples",
            "amount": "42.50",
            "currency": "USD",
            "expense_date": "2026-07-01",
        },
    )

    AgentWorkflowService.approve(workflow, reviewed_by=user)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.APPROVED
    assert workflow.resulting_expense.vendor == "Staples"


def test_approve_writes_an_audit_log_entry():
    user = UserFactory()
    receipt = _receipt(user)
    workflow = AgentWorkflow.objects.create(receipt=receipt)
    workflow.mark_needs_review(
        extracted_data={"vendor": "Staples", "amount": "42.50", "expense_date": "2026-07-01"}
    )

    AgentWorkflowService.approve(workflow, reviewed_by=user, overrides={"vendor": "Staples Inc."})

    log = AuditLog.objects.get(workflow=workflow)
    assert log.actor_id == user.id
    assert log.action == "approved"
    assert log.metadata["resulting_expense_id"] == workflow.resulting_expense_id
    assert log.metadata["overrides"] == {"vendor": "Staples Inc."}


def test_approve_lets_a_human_override_the_extracted_data_before_saving():
    user = UserFactory()
    receipt = _receipt(user)
    workflow = AgentWorkflow.objects.create(receipt=receipt)
    workflow.mark_needs_review(
        extracted_data={
            "vendor": "Staples",
            "amount": "42.50",
            "currency": "USD",
            "expense_date": "2026-07-01",
        }
    )

    AgentWorkflowService.approve(workflow, reviewed_by=user, overrides={"vendor": "Staples Inc."})

    assert workflow.resulting_expense.vendor == "Staples Inc."


def test_reject_marks_rejected_without_creating_an_expense():
    user = UserFactory()
    receipt = _receipt(user)
    workflow = AgentWorkflow.objects.create(receipt=receipt)
    workflow.mark_needs_review(extracted_data={"vendor": "Staples"})

    AgentWorkflowService.reject(workflow, reviewed_by=user)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.REJECTED
    assert workflow.resulting_expense is None
    assert workflow.reviewed_by_id == user.id


def test_reject_writes_an_audit_log_entry():
    user = UserFactory()
    receipt = _receipt(user)
    workflow = AgentWorkflow.objects.create(receipt=receipt)
    workflow.mark_needs_review(extracted_data={"vendor": "Staples"})

    AgentWorkflowService.reject(workflow, reviewed_by=user)

    log = AuditLog.objects.get(workflow=workflow)
    assert log.actor_id == user.id
    assert log.action == "rejected"


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


def test_pending_invoice_chaser_workflow_keeps_its_existing_direct_reject_behavior():
    user = UserFactory()
    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )
    workflow = AgentWorkflow.objects.create(workflow_type="invoice_chaser", invoice=invoice)

    AgentWorkflowService.reject(workflow, reviewed_by=user)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.REJECTED
    assert AuditLog.objects.get(workflow=workflow).action == "rejected"
