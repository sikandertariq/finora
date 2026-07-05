import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.tenancy.models import Tenant, TenantMembership


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Acme", slug="acme")


@pytest.fixture
def authed_client(tenant):
    """An APIClient already logged in as a real member of `tenant`, via a real JWT."""
    user = User.objects.create_user("alice", password="pw12345!")
    TenantMembership.objects.create(user=user, tenant=tenant)

    client = APIClient()
    resp = client.post(
        "/api/token/", {"username": "alice", "password": "pw12345!"}, format="json"
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    client.user = user
    client.tenant = tenant
    return client


@pytest.fixture
def other_authed_client():
    """A second tenant's authenticated client, for cross-tenant isolation tests."""
    other_tenant = Tenant.objects.create(name="Globex", slug="globex")
    user = User.objects.create_user("bob", password="pw12345!")
    TenantMembership.objects.create(user=user, tenant=other_tenant)

    client = APIClient()
    resp = client.post(
        "/api/token/", {"username": "bob", "password": "pw12345!"}, format="json"
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    client.user = user
    client.tenant = other_tenant
    return client
