import pytest

from apps.agents import tasks

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


def test_request_approval_creates_a_pending_expense_approver_workflow(authed_client, monkeypatch):
    expense = _expense(authed_client)
    calls = []
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: calls.append(kw))

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


def test_request_approval_rejects_a_second_active_workflow(authed_client, monkeypatch):
    expense = _expense(authed_client)
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: None)

    first = authed_client.post(f"/api/expenses/{expense['id']}/request-approval/", {}, format="json")
    second = authed_client.post(f"/api/expenses/{expense['id']}/request-approval/", {}, format="json")

    assert first.status_code == 201, first.data
    assert second.status_code == 400
    assert "active expense approval workflow" in str(second.data)
