import pytest

from apps.invoices.models import Invoice
from apps.invoices.services import InvoiceService
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def test_create_persists_an_invoice(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    assert invoice.id is not None
    assert invoice.tenant_id == tenant_context.id
    assert str(invoice.amount) == "100.00"
    assert invoice.currency == "USD"
    assert invoice.status == Invoice.Status.DRAFT


def test_create_rejects_non_positive_amount(tenant_context):
    with pytest.raises(ValueError):
        InvoiceService.create(
            client_name="Acme", client_email="ap@acme.test", amount="0",
            issue_date="2026-06-01", due_date="2026-06-15",
        )


def test_create_accepts_an_explicit_status(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )

    assert invoice.status == Invoice.Status.SENT


def test_update_mutates_allowed_fields(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    InvoiceService.update(invoice, client_name="Acme Corp", status=Invoice.Status.SENT)

    invoice.refresh_from_db()
    assert invoice.client_name == "Acme Corp"
    assert invoice.status == Invoice.Status.SENT


def test_update_rejects_unknown_field(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    with pytest.raises(ValueError):
        InvoiceService.update(invoice, tenant_id=999)


def test_update_rejects_non_positive_amount(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    with pytest.raises(ValueError):
        InvoiceService.update(invoice, amount="-5.00")


def test_list_returns_only_current_tenant_invoices(tenant_context):
    other_tenant = TenantFactory()
    InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    context.set_current_tenant(other_tenant.id)
    InvoiceService.create(
        client_name="Globex", client_email="ap@globex.test", amount="200.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    context.set_current_tenant(tenant_context.id)
    names = set(InvoiceService.list().values_list("client_name", flat=True))
    assert names == {"Acme"}


def test_get_fetches_by_id(tenant_context):
    created = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    fetched = InvoiceService.get(created.id)
    assert fetched.id == created.id


def test_delete_removes_the_invoice(tenant_context):
    invoice = InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15",
    )

    InvoiceService.delete(invoice)

    assert InvoiceService.list().count() == 0
