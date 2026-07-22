import pytest

from apps.agents import tasks
from apps.agents.models import AgentWorkflow
from apps.expenses.models import Expense
from apps.tenancy import context

pytestmark = pytest.mark.django_db


def _expense(client, vendor="Railway Co."):
    response = client.post(
        "/api/expenses/",
        {
            "vendor": vendor,
            "amount": "650.00",
            "category": "travel",
            "expense_date": "2026-07-20",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


def test_request_approval_creates_a_pending_expense_approver_workflow(
    authed_client, monkeypatch, django_capture_on_commit_callbacks
):
    expense = _expense(authed_client)
    calls = []
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: calls.append(kw))

    with django_capture_on_commit_callbacks(execute=True):
        response = authed_client.post(
            f"/api/expenses/{expense['id']}/request-approval/", {}, format="json"
        )

    assert response.status_code == 201, response.data
    assert response.data["workflow_type"] == "expense_approver"
    assert response.data["status"] == "pending"
    assert response.data["expense"]["id"] == expense["id"]
    assert calls == [{"tenant_id": authed_client.tenant.id, "workflow_id": response.data["id"]}]
    assert authed_client.get(f"/api/expenses/{expense['id']}/").data["approval_status"] == "pending"


def test_request_approval_does_not_expose_another_tenants_expense(authed_client, other_authed_client):
    other_expense = _expense(other_authed_client, vendor="Globex travel")

    response = authed_client.post(
        f"/api/expenses/{other_expense['id']}/request-approval/", {}, format="json"
    )

    assert response.status_code == 404


def test_request_approval_rejects_a_second_active_workflow(
    authed_client, monkeypatch, django_capture_on_commit_callbacks
):
    expense = _expense(authed_client)
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: None)

    with django_capture_on_commit_callbacks(execute=True):
        first = authed_client.post(
            f"/api/expenses/{expense['id']}/request-approval/", {}, format="json"
        )
    second = authed_client.post(f"/api/expenses/{expense['id']}/request-approval/", {}, format="json")

    assert first.status_code == 201, first.data
    assert second.status_code == 400
    assert "active expense approval workflow" in str(second.data)


def _active_expense_approver_workflow(tenant, status):
    context.set_current_tenant(tenant.id)
    try:
        expense = Expense.objects.create(
            vendor="Railway Co.", amount="650.00", category="travel", expense_date="2026-07-20"
        )
        expense.approval_status = Expense.ApprovalStatus.PENDING
        expense.save(update_fields=["approval_status", "updated_at"])
        workflow = AgentWorkflow.objects.create(workflow_type="expense_approver", expense=expense)
        workflow.status = status
        workflow.save(update_fields=["status", "updated_at"])
        return workflow
    finally:
        context.clear_current_tenant()


@pytest.mark.parametrize("status", [AgentWorkflow.Status.PENDING, AgentWorkflow.Status.RUNNING])
@pytest.mark.parametrize("action", ["confirm", "reject"])
def test_active_expense_approver_workflows_cannot_be_confirmed_or_rejected(
    authed_client, status, action
):
    workflow = _active_expense_approver_workflow(authed_client.tenant, status)

    response = authed_client.post(f"/api/agent-workflows/{workflow.id}/{action}/", {}, format="json")

    assert response.status_code == 400
    context.set_current_tenant(authed_client.tenant.id)
    try:
        workflow.refresh_from_db()
        workflow.expense.refresh_from_db()
        assert workflow.status == status
        assert workflow.expense.approval_status == Expense.ApprovalStatus.PENDING
        assert not workflow.audit_logs.exists()
    finally:
        context.clear_current_tenant()
