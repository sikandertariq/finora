import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agents.models import AgentWorkflow
from apps.expenses.models import Expense, Receipt
from apps.invoices.models import Invoice
from apps.tenancy import context

pytestmark = pytest.mark.django_db


def _needs_review_workflow(tenant, extracted_data=None):
    context.set_current_tenant(tenant.id)
    try:
        receipt = Receipt.objects.create(
            file=SimpleUploadedFile("r.jpg", b"bytes", content_type="image/jpeg")
        )
        workflow = AgentWorkflow.objects.create(receipt=receipt)
        workflow.mark_needs_review(
            extracted_data=extracted_data
            or {
                "vendor": "Staples",
                "amount": "42.50",
                "currency": "USD",
                "category_suggestion": "office supplies",
                "expense_date": "2026-07-01",
            }
        )
        return workflow
    finally:
        context.clear_current_tenant()


def test_list_and_retrieve_workflow(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)

    list_resp = authed_client.get("/api/agent-workflows/")
    detail_resp = authed_client.get(f"/api/agent-workflows/{workflow.id}/")

    assert [w["id"] for w in list_resp.data] == [workflow.id]
    assert detail_resp.data["status"] == AgentWorkflow.Status.NEEDS_REVIEW
    assert detail_resp.data["extracted_data"]["vendor"] == "Staples"


def test_confirm_creates_an_expense_and_marks_approved(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)

    resp = authed_client.post(f"/api/agent-workflows/{workflow.id}/confirm/", {}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["status"] == AgentWorkflow.Status.APPROVED
    expense = authed_client.get(f"/api/expenses/{resp.data['resulting_expense']}/").data
    assert expense["vendor"] == "Staples"
    assert expense["created_by"] == authed_client.user.id


def test_confirm_lets_a_human_override_a_field(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)

    resp = authed_client.post(
        f"/api/agent-workflows/{workflow.id}/confirm/",
        {"vendor": "Staples Inc."},
        format="json",
    )

    expense = authed_client.get(f"/api/expenses/{resp.data['resulting_expense']}/").data
    assert expense["vendor"] == "Staples Inc."


def test_reject_marks_rejected_and_creates_no_expense(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)

    resp = authed_client.post(f"/api/agent-workflows/{workflow.id}/reject/", {}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["status"] == AgentWorkflow.Status.REJECTED
    assert resp.data["resulting_expense"] is None


def test_workflow_from_another_tenant_is_not_found(authed_client, other_authed_client):
    other_workflow = _needs_review_workflow(other_authed_client.tenant)

    resp = authed_client.get(f"/api/agent-workflows/{other_workflow.id}/")

    assert resp.status_code == 404


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


def _needs_review_expense_workflow(tenant):
    context.set_current_tenant(tenant.id)
    try:
        expense = Expense.objects.create(
            vendor="Railway Co.", amount="650.00", category="travel",
            expense_date="2026-07-20",
        )
        expense.approval_status = Expense.ApprovalStatus.PENDING
        expense.save(update_fields=["approval_status", "updated_at"])
        workflow = AgentWorkflow.objects.create(
            workflow_type="expense_approver", expense=expense,
            extracted_data={"policy": {"approval_queue": "Operations"}},
        )
        workflow.mark_needs_review(extracted_data=workflow.extracted_data)
        return workflow
    finally:
        context.clear_current_tenant()


def test_filter_workflows_by_expense_approver_type(authed_client):
    expense_workflow = _needs_review_expense_workflow(authed_client.tenant)
    _needs_review_workflow(authed_client.tenant)

    response = authed_client.get("/api/agent-workflows/?workflow_type=expense_approver")

    assert [workflow["id"] for workflow in response.data] == [expense_workflow.id]
    assert response.data[0]["expense"]["vendor"] == "Railway Co."


def test_confirm_expense_approver_marks_the_linked_expense_approved_and_audits(authed_client):
    workflow = _needs_review_expense_workflow(authed_client.tenant)

    response = authed_client.post(f"/api/agent-workflows/{workflow.id}/confirm/", {}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["status"] == "approved"
    expense = authed_client.get(f"/api/expenses/{workflow.expense_id}/").data
    assert expense["approval_status"] == "approved"
    audit = authed_client.get(f"/api/audit-logs/?workflow={workflow.id}").data[0]
    assert audit["action"] == "expense_approved"


def test_reject_expense_approver_marks_the_linked_expense_rejected_and_audits_note(authed_client):
    workflow = _needs_review_expense_workflow(authed_client.tenant)

    response = authed_client.post(
        f"/api/agent-workflows/{workflow.id}/reject/",
        {"note": "Duplicate reimbursement request."},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["status"] == "rejected"
    expense = authed_client.get(f"/api/expenses/{workflow.expense_id}/").data
    assert expense["approval_status"] == "rejected"
    audit = authed_client.get(f"/api/audit-logs/?workflow={workflow.id}").data[0]
    assert audit["action"] == "expense_rejected"
    assert audit["metadata"] == {"note": "Duplicate reimbursement request."}


def test_reject_receipt_workflow_records_an_optional_note(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)

    response = authed_client.post(
        f"/api/agent-workflows/{workflow.id}/reject/", {"note": "Unreadable receipt."}, format="json"
    )

    assert response.status_code == 200, response.data
    audit = authed_client.get(f"/api/audit-logs/?workflow={workflow.id}").data[0]
    assert audit["action"] == "rejected"
    assert audit["metadata"] == {"note": "Unreadable receipt."}
