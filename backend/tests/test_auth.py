import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.tenancy.models import Tenant, TenantMembership

pytestmark = pytest.mark.django_db


def _user_with_tenant():
    tenant = Tenant.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user("alice", password="pw12345!")
    TenantMembership.objects.create(user=user, tenant=tenant)
    return user, tenant


def test_token_carries_tenant_and_whoami_resolves_it():
    _, tenant = _user_with_tenant()
    client = APIClient()

    resp = client.post(
        "/api/token/",
        {"username": "alice", "password": "pw12345!"},
        format="json",
    )
    assert resp.status_code == 200
    access = resp.data["access"]

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    who = client.get("/api/whoami/")
    assert who.status_code == 200
    assert who.data == {"user": "alice", "tenant_id": tenant.id}


def test_whoami_without_token_is_401():
    client = APIClient()
    assert client.get("/api/whoami/").status_code == 401
