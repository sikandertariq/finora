import pytest

from apps.agents import tasks
from apps.agents.models import AgentWorkflow
from apps.agents.services import ExpenseApprovalService, AgentWorkflowService
from apps.expenses.approval_services import ExpenseApprovalPolicyService
from apps.expenses.models import Expense
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def _expense():
    return Expense.objects.create(
        vendor="Railway Co.",
        amount="650.00",
        currency="USD",
        category="travel",
        description="Client visit train fare",
        expense_date="2026-07-20",
        created_by=UserFactory(),
    )


def _policy():
    return ExpenseApprovalPolicyService.create(
        name="Travel review",
        priority=10,
        category="travel",
        minimum_amount="100.00",
        maximum_amount="500.00",
        approval_queue="Operations",
    )


def test_start_persists_selected_policy_marks_expense_pending_and_enqueues_task(
    tenant_context, monkeypatch
):
    expense = _expense()
    policy = _policy()
    calls = []
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: calls.append(kw))

    workflow = ExpenseApprovalService.start(expense)

    expense.refresh_from_db()
    assert workflow.workflow_type == "expense_approver"
    assert workflow.status == AgentWorkflow.Status.PENDING
    assert workflow.expense_id == expense.id
    assert workflow.extracted_data["policy"] == {
        "id": policy.id,
        "name": "Travel review",
        "priority": 10,
        "category": "travel",
        "minimum_amount": "100.00",
        "maximum_amount": "500.00",
        "approval_queue": "Operations",
    }
    assert expense.approval_status == Expense.ApprovalStatus.PENDING
    assert calls == [{"tenant_id": tenant_context.id, "workflow_id": workflow.id}]


def test_start_uses_the_default_finance_queue_when_no_policy_matches(monkeypatch):
    expense = _expense()
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: None)

    workflow = ExpenseApprovalService.start(expense)

    assert workflow.extracted_data == {"policy": {}, "approval_queue": "Finance"}


@pytest.mark.parametrize(
    "status",
    [
        AgentWorkflow.Status.PENDING,
        AgentWorkflow.Status.RUNNING,
        AgentWorkflow.Status.NEEDS_REVIEW,
    ],
)
def test_start_rejects_an_expense_with_an_active_approval_workflow(status, monkeypatch):
    expense = _expense()
    existing = AgentWorkflow.objects.create(
        workflow_type="expense_approver", expense=expense
    )
    if status != AgentWorkflow.Status.PENDING:
        existing.status = status
        existing.save(update_fields=["status", "updated_at"])
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: None)

    with pytest.raises(ValueError, match="active expense approval workflow"):
        ExpenseApprovalService.start(expense)

    assert AgentWorkflow.objects.filter(
        workflow_type="expense_approver", expense=expense
    ).count() == 1


def _reviewable_workflow():
    expense = _expense()
    expense.approval_status = Expense.ApprovalStatus.PENDING
    expense.save(update_fields=["approval_status", "updated_at"])
    workflow = AgentWorkflow.objects.create(
        workflow_type="expense_approver", expense=expense,
        extracted_data={"policy": {"approval_queue": "Operations"}},
    )
    workflow.mark_needs_review(extracted_data=workflow.extracted_data)
    return workflow


def test_approve_expense_approver_marks_the_expense_and_writes_specific_audit_event():
    workflow = _reviewable_workflow()
    reviewer = UserFactory()

    AgentWorkflowService.approve(workflow, reviewed_by=reviewer)

    workflow.refresh_from_db()
    workflow.expense.refresh_from_db()
    audit = workflow.audit_logs.get()
    assert workflow.status == AgentWorkflow.Status.APPROVED
    assert workflow.expense.approval_status == Expense.ApprovalStatus.APPROVED
    assert audit.action == "expense_approved"
    assert audit.actor_id == reviewer.id
    assert audit.metadata == {}


def test_reject_expense_approver_marks_the_expense_and_audits_the_human_note():
    workflow = _reviewable_workflow()
    reviewer = UserFactory()

    AgentWorkflowService.reject(
        workflow, reviewed_by=reviewer, note="Duplicate reimbursement request."
    )

    workflow.refresh_from_db()
    workflow.expense.refresh_from_db()
    audit = workflow.audit_logs.get()
    assert workflow.status == AgentWorkflow.Status.REJECTED
    assert workflow.expense.approval_status == Expense.ApprovalStatus.REJECTED
    assert audit.action == "expense_rejected"
    assert audit.actor_id == reviewer.id
    assert audit.metadata == {"note": "Duplicate reimbursement request."}
