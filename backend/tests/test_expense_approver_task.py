import json

import pytest

from apps.agents import tasks
from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.expenses.models import Expense
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def _workflow(tenant):
    context.set_current_tenant(tenant.id)
    expense = Expense.objects.create(
        vendor="Railway Co.", amount="650.00", category="travel",
        expense_date="2026-07-20", created_by=UserFactory(),
    )
    workflow = AgentWorkflow.objects.create(
        workflow_type="expense_approver", expense=expense,
        extracted_data={"policy": {"approval_queue": "Operations"}},
    )
    context.clear_current_tenant()
    return workflow


def _provider_response():
    return json.dumps(
        {
            "recommendation": "approve",
            "rationale": "Matches the selected travel policy.",
            "policy_flags": [],
            "anomaly_flags": [],
            "confidence": 0.93,
        }
    )


def test_task_binds_tenant_context_and_runs_the_expense_approver(monkeypatch):
    tenant = TenantFactory()
    workflow = _workflow(tenant)
    fake = FakeLLMProvider(response=_provider_response())
    monkeypatch.setattr(
        tasks.GeminiProvider, "from_settings", staticmethod(lambda api_key, model: fake)
    )

    tasks.run_expense_approver.apply(
        kwargs={"tenant_id": tenant.id, "workflow_id": workflow.id}
    ).get()

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["recommendation"] == "approve"
    assert context.get_current_tenant_id() is None


def test_run_expense_approver_can_be_dispatched_via_delay(monkeypatch):
    tenant = TenantFactory()
    workflow = _workflow(tenant)
    fake = FakeLLMProvider(response=_provider_response())
    monkeypatch.setattr(
        tasks.GeminiProvider, "from_settings", staticmethod(lambda api_key, model: fake)
    )

    tasks.run_expense_approver.app.conf.task_always_eager = True
    try:
        tasks.run_expense_approver.delay(tenant_id=tenant.id, workflow_id=workflow.id).get()
    finally:
        tasks.run_expense_approver.app.conf.task_always_eager = False

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
