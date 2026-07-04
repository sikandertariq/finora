import pytest

from apps.expenses.services import ExpenseService
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def test_create_persists_an_expense(tenant_context):
    user = UserFactory()
    expense = ExpenseService.create(
        vendor="Acme", amount="42.50", expense_date="2026-07-01", created_by=user, category="software"
    )

    assert expense.id is not None
    assert expense.tenant_id == tenant_context.id
    assert str(expense.amount) == "42.50"
    assert expense.currency == "USD"


def test_create_rejects_non_positive_amount(tenant_context):
    user = UserFactory()
    with pytest.raises(ValueError):
        ExpenseService.create(vendor="Acme", amount="0", expense_date="2026-07-01", created_by=user)


def test_update_mutates_allowed_fields(tenant_context):
    user = UserFactory()
    expense = ExpenseService.create(vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user)

    ExpenseService.update(expense, vendor="Acme Corp", amount="15.00")

    expense.refresh_from_db()
    assert expense.vendor == "Acme Corp"
    assert str(expense.amount) == "15.00"


def test_update_rejects_unknown_field(tenant_context):
    user = UserFactory()
    expense = ExpenseService.create(vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user)

    with pytest.raises(ValueError):
        ExpenseService.update(expense, tenant_id=999)


def test_update_rejects_non_positive_amount(tenant_context):
    user = UserFactory()
    expense = ExpenseService.create(vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user)

    with pytest.raises(ValueError):
        ExpenseService.update(expense, amount="-5.00")


def test_list_returns_only_current_tenant_expenses(tenant_context):
    other_tenant = TenantFactory()
    user = UserFactory()
    ExpenseService.create(vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user)

    context.set_current_tenant(other_tenant.id)
    ExpenseService.create(vendor="Globex", amount="20.00", expense_date="2026-07-01", created_by=user)

    context.set_current_tenant(tenant_context.id)
    vendors = set(ExpenseService.list().values_list("vendor", flat=True))
    assert vendors == {"Acme"}


def test_get_fetches_by_id(tenant_context):
    user = UserFactory()
    created = ExpenseService.create(vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user)

    fetched = ExpenseService.get(created.id)
    assert fetched.id == created.id


def test_delete_removes_the_expense(tenant_context):
    user = UserFactory()
    expense = ExpenseService.create(vendor="Acme", amount="10.00", expense_date="2026-07-01", created_by=user)

    ExpenseService.delete(expense)

    assert ExpenseService.list().count() == 0
