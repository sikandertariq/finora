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
    tenant_context, monkeypatch, django_capture_on_commit_callbacks
):
    expense = _expense()
    policy = _policy()
    calls = []
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: calls.append(kw))

    with django_capture_on_commit_callbacks(execute=True):
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


def test_start_defers_task_dispatch_until_its_transaction_commits(
    monkeypatch, django_capture_on_commit_callbacks
):
    expense = _expense()
    calls = []
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: calls.append(kw))

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        workflow = ExpenseApprovalService.start(expense)
        assert calls == []

    assert len(callbacks) == 1
    callbacks[0]()
    assert calls == [{"tenant_id": expense.tenant_id, "workflow_id": workflow.id}]


def test_start_locks_and_refetches_the_tenant_scoped_expense_before_creating_workflow(
    monkeypatch, django_capture_on_commit_callbacks
):
    expense = _expense()
    locked = []
    original = Expense.objects.select_for_update

    def select_for_update(*args, **kwargs):
        locked.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(Expense.objects, "select_for_update", select_for_update)
    monkeypatch.setattr(tasks.run_expense_approver, "delay", lambda **kw: None)

    with django_capture_on_commit_callbacks(execute=True):
        workflow = ExpenseApprovalService.start(expense)

    assert locked == [((), {})]
    assert workflow.expense_id == expense.id


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


def _active_workflow(status):
    workflow = _reviewable_workflow()
    workflow.status = status
    workflow.save(update_fields=["status", "updated_at"])
    return workflow


@pytest.mark.parametrize("status", [AgentWorkflow.Status.PENDING, AgentWorkflow.Status.RUNNING])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_expense_approver_decisions_require_needs_review_and_leave_active_rows_unchanged(
    status, decision
):
    workflow = _active_workflow(status)
    reviewer = UserFactory()

    with pytest.raises(ValueError, match="needs_review"):
        getattr(AgentWorkflowService, decision)(workflow, reviewed_by=reviewer)

    workflow.refresh_from_db()
    workflow.expense.refresh_from_db()
    assert workflow.status == status
    assert workflow.expense.approval_status == Expense.ApprovalStatus.PENDING
    assert not workflow.audit_logs.exists()


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


@pytest.mark.parametrize("second_decision", ["approve", "reject"])
def test_expense_decision_refetches_locked_state_and_never_overrides_a_prior_decision(
    second_decision,
):
    workflow = _reviewable_workflow()
    stale_workflow = AgentWorkflow.objects.get(pk=workflow.pk)
    first_reviewer = UserFactory()
    second_reviewer = UserFactory()

    AgentWorkflowService.approve(workflow, reviewed_by=first_reviewer)

    with pytest.raises(ValueError, match="needs_review"):
        getattr(AgentWorkflowService, second_decision)(
            stale_workflow, reviewed_by=second_reviewer
        )

    workflow.refresh_from_db()
    workflow.expense.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.APPROVED
    assert workflow.expense.approval_status == Expense.ApprovalStatus.APPROVED
    assert workflow.audit_logs.count() == 1


def test_expense_decision_locks_and_refetches_the_workflow_and_expense(monkeypatch):
    workflow = _reviewable_workflow()
    locks = []
    original_workflow_lock = AgentWorkflow.objects.select_for_update
    original_expense_lock = Expense.objects.select_for_update

    def lock_workflow(*args, **kwargs):
        locks.append("workflow")
        return original_workflow_lock(*args, **kwargs)

    def lock_expense(*args, **kwargs):
        locks.append("expense")
        return original_expense_lock(*args, **kwargs)

    monkeypatch.setattr(AgentWorkflow.objects, "select_for_update", lock_workflow)
    monkeypatch.setattr(Expense.objects, "select_for_update", lock_expense)

    AgentWorkflowService.approve(workflow, reviewed_by=UserFactory())

    assert locks == ["workflow", "expense"]
