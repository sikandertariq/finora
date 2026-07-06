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
