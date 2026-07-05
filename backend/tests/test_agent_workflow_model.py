import pytest

from apps.agents.models import AgentWorkflow
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


def _workflow(user):
    from apps.expenses.models import Receipt

    receipt = Receipt.objects.create(uploaded_by=user)
    return AgentWorkflow.objects.create(receipt=receipt)


def test_new_workflow_starts_pending():
    user = UserFactory()
    workflow = _workflow(user)

    assert workflow.status == AgentWorkflow.Status.PENDING
    assert workflow.workflow_type == "receipt_processor"


def test_mark_running_transitions_status():
    user = UserFactory()
    workflow = _workflow(user)

    workflow.mark_running()

    assert workflow.status == AgentWorkflow.Status.RUNNING


def test_mark_needs_review_stores_extracted_data():
    user = UserFactory()
    workflow = _workflow(user)

    workflow.mark_needs_review(extracted_data={"vendor": "Staples", "amount": "42.50"})

    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == {"vendor": "Staples", "amount": "42.50"}
    assert workflow.error_message == ""


def test_mark_needs_review_can_record_an_error_instead():
    user = UserFactory()
    workflow = _workflow(user)

    workflow.mark_needs_review(error_message="Could not read the amount.")

    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == {}
    assert workflow.error_message == "Could not read the amount."


def test_mark_approved_links_the_resulting_expense():
    user = UserFactory()
    workflow = _workflow(user)
    expense = ExpenseService.create(
        vendor="Staples", amount="42.50", expense_date="2026-07-01", created_by=user
    )

    workflow.mark_approved(reviewed_by=user, resulting_expense=expense)

    assert workflow.status == AgentWorkflow.Status.APPROVED
    assert workflow.resulting_expense_id == expense.id
    assert workflow.reviewed_by_id == user.id


def test_mark_rejected_records_who_rejected_it():
    user = UserFactory()
    workflow = _workflow(user)

    workflow.mark_rejected(reviewed_by=user)

    assert workflow.status == AgentWorkflow.Status.REJECTED
    assert workflow.reviewed_by_id == user.id
