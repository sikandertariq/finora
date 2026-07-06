import pytest

from apps.invoices.models import Invoice
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def test_invoice_is_scoped_to_current_tenant():
    tenant_a, tenant_b = TenantFactory(), TenantFactory()
    Invoice.all_tenants.create(
        tenant=tenant_a, client_name="Acme", client_email="ap@acme.test",
        amount="100.00", issue_date="2026-06-01", due_date="2026-06-15",
    )
    Invoice.all_tenants.create(
        tenant=tenant_b, client_name="Globex", client_email="ap@globex.test",
        amount="200.00", issue_date="2026-06-01", due_date="2026-06-15",
    )

    context.set_current_tenant(tenant_a.id)
    names = set(Invoice.objects.values_list("client_name", flat=True))
    assert names == {"Acme"}


def test_invoice_without_tenant_context_raises():
    with pytest.raises(context.TenantContextRequired):
        list(Invoice.objects.all())


def test_invoice_defaults_to_draft_status():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)

    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    assert invoice.status == Invoice.Status.DRAFT
