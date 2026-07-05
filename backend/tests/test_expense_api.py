import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_create_expense_via_api(authed_client):
    resp = authed_client.post(
        "/api/expenses/",
        {"vendor": "Staples", "amount": "42.50", "expense_date": "2026-07-01"},
        format="json",
    )

    assert resp.status_code == 201, resp.data
    assert resp.data["vendor"] == "Staples"
    assert resp.data["created_by"] == authed_client.user.id


def test_create_expense_with_non_positive_amount_is_a_400_not_a_500(authed_client):
    resp = authed_client.post(
        "/api/expenses/",
        {"vendor": "Staples", "amount": "0", "expense_date": "2026-07-01"},
        format="json",
    )

    assert resp.status_code == 400


def test_create_expense_requires_authentication():
    client = APIClient()

    resp = client.post(
        "/api/expenses/",
        {"vendor": "Staples", "amount": "42.50", "expense_date": "2026-07-01"},
        format="json",
    )

    assert resp.status_code == 401


def test_list_expenses_is_scoped_to_the_current_tenant(authed_client, other_authed_client):
    other_authed_client.post(
        "/api/expenses/",
        {"vendor": "Globex Corp", "amount": "10.00", "expense_date": "2026-07-01"},
        format="json",
    )
    authed_client.post(
        "/api/expenses/",
        {"vendor": "Staples", "amount": "42.50", "expense_date": "2026-07-01"},
        format="json",
    )

    resp = authed_client.get("/api/expenses/")

    vendors = {row["vendor"] for row in resp.data}
    assert vendors == {"Staples"}


def test_expense_from_another_tenant_is_not_found(authed_client, other_authed_client):
    create_resp = other_authed_client.post(
        "/api/expenses/",
        {"vendor": "Globex Corp", "amount": "10.00", "expense_date": "2026-07-01"},
        format="json",
    )

    resp = authed_client.get(f"/api/expenses/{create_resp.data['id']}/")

    assert resp.status_code == 404
