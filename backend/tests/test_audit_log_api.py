import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agents.models import AgentWorkflow
from apps.expenses.models import Receipt
from apps.tenancy import context

pytestmark = pytest.mark.django_db


def _needs_review_workflow(tenant):
    context.set_current_tenant(tenant.id)
    try:
        receipt = Receipt.objects.create(
            file=SimpleUploadedFile("r.jpg", b"bytes", content_type="image/jpeg")
        )
        workflow = AgentWorkflow.objects.create(receipt=receipt)
        workflow.mark_needs_review(
            extracted_data={"vendor": "Staples", "amount": "42.50", "expense_date": "2026-07-01"}
        )
        return workflow
    finally:
        context.clear_current_tenant()


def test_confirming_a_workflow_creates_a_visible_audit_log_entry(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)
    authed_client.post(f"/api/agent-workflows/{workflow.id}/confirm/", {}, format="json")

    resp = authed_client.get(f"/api/audit-logs/?workflow={workflow.id}")

    assert resp.status_code == 200
    assert len(resp.data) == 1
    assert resp.data[0]["action"] == "approved"
    assert resp.data[0]["actor"] == authed_client.user.id
    assert resp.data[0]["metadata"]["resulting_expense_id"] is not None


def test_rejecting_a_workflow_creates_a_visible_audit_log_entry(authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)
    authed_client.post(f"/api/agent-workflows/{workflow.id}/reject/", {}, format="json")

    resp = authed_client.get(f"/api/audit-logs/?workflow={workflow.id}")

    assert resp.data[0]["action"] == "rejected"


def test_audit_logs_are_scoped_to_the_current_tenant(authed_client, other_authed_client):
    workflow = _needs_review_workflow(authed_client.tenant)
    authed_client.post(f"/api/agent-workflows/{workflow.id}/reject/", {}, format="json")

    resp = other_authed_client.get("/api/audit-logs/")

    assert resp.data == []


def test_audit_logs_require_authentication():
    from rest_framework.test import APIClient

    resp = APIClient().get("/api/audit-logs/")

    assert resp.status_code == 401
