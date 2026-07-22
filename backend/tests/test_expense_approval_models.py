import pytest

from apps.expenses.models import Expense, ExpenseApprovalPolicy
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def test_new_expense_defaults_to_not_requested_approval_status():
    tenant = TenantFactory()
    user = UserFactory()
    context.set_current_tenant(tenant.id)

    expense = Expense.objects.create(
        vendor="Acme",
        amount="42.50",
        expense_date="2026-07-22",
        created_by=user,
    )

    assert expense.approval_status == Expense.ApprovalStatus.NOT_REQUESTED


def test_approval_policies_are_scoped_to_the_current_tenant():
    tenant_a, tenant_b = TenantFactory(), TenantFactory()

    ExpenseApprovalPolicy.all_tenants.create(
        tenant=tenant_a,
        name="Tenant A finance",
        priority=10,
        minimum_amount="0.00",
        approval_queue="Finance",
    )
    ExpenseApprovalPolicy.all_tenants.create(
        tenant=tenant_b,
        name="Tenant B operations",
        priority=10,
        minimum_amount="0.00",
        approval_queue="Operations",
    )

    context.set_current_tenant(tenant_a.id)

    assert list(ExpenseApprovalPolicy.objects.values_list("name", flat=True)) == [
        "Tenant A finance"
    ]
