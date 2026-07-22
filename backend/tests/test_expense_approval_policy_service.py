import pytest

from apps.expenses.approval_services import ExpenseApprovalPolicyService
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


def test_matching_policy_uses_the_highest_priority_active_category_and_minimum_match(
    tenant_context,
):
    user = UserFactory()
    expense = ExpenseService.create(
        vendor="Acme",
        amount="250.00",
        expense_date="2026-07-22",
        created_by=user,
        category="software",
    )
    ExpenseApprovalPolicyService.create(
        name="Inactive software",
        priority=1,
        category="software",
        minimum_amount="0.00",
        approval_queue="Operations",
        is_active=False,
    )
    expected = ExpenseApprovalPolicyService.create(
        name="Small software",
        priority=5,
        category="software",
        minimum_amount="0.00",
        maximum_amount="100.00",
        approval_queue="Operations",
    )
    ExpenseApprovalPolicyService.create(
        name="Finance software",
        priority=10,
        category="software",
        minimum_amount="100.00",
        maximum_amount="500.00",
        approval_queue="Finance",
    )
    ExpenseApprovalPolicyService.create(
        name="Any category",
        priority=20,
        minimum_amount="0.00",
        approval_queue="Finance",
    )

    policy = ExpenseApprovalPolicyService.matching_policy(expense)

    assert policy == expected


def test_matching_policy_returns_none_when_no_active_policy_matches(tenant_context):
    user = UserFactory()
    expense = ExpenseService.create(
        vendor="Acme",
        amount="50.00",
        expense_date="2026-07-22",
        created_by=user,
        category="travel",
    )
    ExpenseApprovalPolicyService.create(
        name="Software only",
        priority=10,
        category="software",
        minimum_amount="0.00",
        approval_queue="Finance",
    )

    assert ExpenseApprovalPolicyService.matching_policy(expense) is None


def test_matching_policy_retains_the_selected_policy_above_its_ceiling(tenant_context):
    user = UserFactory()
    expense = ExpenseService.create(
        vendor="Acme",
        amount="600.00",
        expense_date="2026-07-22",
        created_by=user,
        category="software",
    )
    expected = ExpenseApprovalPolicyService.create(
        name="Software finance",
        priority=10,
        category="software",
        minimum_amount="100.00",
        maximum_amount="500.00",
        approval_queue="Finance",
    )
    ExpenseApprovalPolicyService.create(
        name="Fallback queue",
        priority=20,
        minimum_amount="0.00",
        approval_queue="Operations",
    )

    policy = ExpenseApprovalPolicyService.matching_policy(expense)

    assert policy == expected


@pytest.mark.parametrize(
    ("minimum_amount", "maximum_amount"),
    [("100.00", "99.99"), ("0.00", "-0.01")],
)
def test_create_rejects_an_invalid_amount_range(
    tenant_context, minimum_amount, maximum_amount
):
    with pytest.raises(ValueError, match="Maximum amount cannot be less than minimum amount"):
        ExpenseApprovalPolicyService.create(
            name="Invalid range",
            priority=10,
            minimum_amount=minimum_amount,
            maximum_amount=maximum_amount,
            approval_queue="Finance",
        )


@pytest.mark.parametrize(
    ("minimum_amount", "maximum_amount"),
    [("NaN", None), ("Infinity", None), ("0.00", "NaN")],
)
def test_create_rejects_non_finite_policy_amounts(
    tenant_context, minimum_amount, maximum_amount
):
    with pytest.raises(ValueError, match="Policy amounts must be finite decimal values"):
        ExpenseApprovalPolicyService.create(
            name="Invalid amount",
            priority=10,
            minimum_amount=minimum_amount,
            maximum_amount=maximum_amount,
            approval_queue="Finance",
        )


def test_update_rejects_an_invalid_amount_range(tenant_context):
    policy = ExpenseApprovalPolicyService.create(
        name="Valid range",
        priority=10,
        minimum_amount="100.00",
        maximum_amount="500.00",
        approval_queue="Finance",
    )

    with pytest.raises(ValueError, match="Maximum amount cannot be less than minimum amount"):
        ExpenseApprovalPolicyService.update(policy, maximum_amount="99.99")


def test_update_persists_policy_fields(tenant_context):
    policy = ExpenseApprovalPolicyService.create(
        name="Finance",
        priority=10,
        minimum_amount="0.00",
        approval_queue="Finance",
    )

    updated = ExpenseApprovalPolicyService.update(
        policy, name="Operations", approval_queue="Operations"
    )

    assert updated.name == "Operations"
    assert updated.approval_queue == "Operations"


def test_get_returns_the_current_tenant_policy(tenant_context):
    policy = ExpenseApprovalPolicyService.create(
        name="Finance",
        priority=10,
        minimum_amount="0.00",
        approval_queue="Finance",
    )

    assert ExpenseApprovalPolicyService.get(policy.id) == policy


def test_list_returns_the_current_tenant_policies(tenant_context):
    policy = ExpenseApprovalPolicyService.create(
        name="Finance",
        priority=10,
        minimum_amount="0.00",
        approval_queue="Finance",
    )

    assert list(ExpenseApprovalPolicyService.list()) == [policy]


def test_delete_removes_a_policy(tenant_context):
    policy = ExpenseApprovalPolicyService.create(
        name="Finance",
        priority=10,
        minimum_amount="0.00",
        approval_queue="Finance",
    )

    ExpenseApprovalPolicyService.delete(policy)

    assert ExpenseApprovalPolicyService.list().count() == 0
