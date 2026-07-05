import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agents import tasks
from apps.agents.models import AgentWorkflow, AuditLog
from apps.agents.services import AgentWorkflowService
from apps.expenses.models import Receipt
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
