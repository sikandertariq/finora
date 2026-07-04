import pytest

from apps.expenses.models import Expense, Receipt
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def test_expense_is_scoped_to_current_tenant():
    tenant_a, tenant_b = TenantFactory(), TenantFactory()
    user = UserFactory()
    Expense.all_tenants.create(
        tenant=tenant_a, vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user
    )
    Expense.all_tenants.create(
        tenant=tenant_b, vendor="Globex", amount="20.00", expense_date="2026-07-01", created_by=user
    )

    context.set_current_tenant(tenant_a.id)
    vendors = set(Expense.objects.values_list("vendor", flat=True))
    assert vendors == {"Acme"}


def test_expense_without_tenant_context_raises():
    with pytest.raises(context.TenantContextRequired):
        list(Expense.objects.all())


def test_expense_can_link_to_a_receipt():
    tenant = TenantFactory()
    user = UserFactory()
    context.set_current_tenant(tenant.id)

    receipt = Receipt.objects.create(uploaded_by=user)
    expense = Expense.objects.create(
        vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user, receipt=receipt
    )

    assert expense.receipt_id == receipt.id
    assert receipt.expense == expense
