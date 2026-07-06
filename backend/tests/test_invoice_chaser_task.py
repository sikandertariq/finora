import json

import pytest

from apps.agents import tasks
from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.invoices.models import Invoice
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def _workflow(tenant):
    context.set_current_tenant(tenant.id)
    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )
    workflow = AgentWorkflow.objects.create(
        workflow_type="invoice_chaser", invoice=invoice,
        extracted_data={"escalation_level": "day_7"},
    )
    context.clear_current_tenant()
    return workflow


def test_task_binds_tenant_context_and_runs_the_chaser(monkeypatch):
    tenant = TenantFactory()
    workflow = _workflow(tenant)

    fake = FakeLLMProvider(
        response=json.dumps({"subject": "Invoice overdue", "body": "Please pay soon."})
    )
    monkeypatch.setattr(
        tasks.GeminiProvider, "from_settings", staticmethod(lambda api_key, model: fake)
    )

    tasks.run_invoice_chaser.apply(
        kwargs={"tenant_id": tenant.id, "workflow_id": workflow.id}
    ).get()

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["subject"] == "Invoice overdue"
    assert context.get_current_tenant_id() is None


def test_run_invoice_chaser_can_be_dispatched_via_delay_not_just_apply(monkeypatch):
    """Same regression class as test_tasks.py -- .apply() never exercises Celery's
    apply_async pre-flight kwarg check. TenantBoundTask.typing = False already fixes
    this for every task built on it, but confirm it holds for this new one too."""
    tenant = TenantFactory()
    workflow = _workflow(tenant)

    fake = FakeLLMProvider(
        response=json.dumps({"subject": "Invoice overdue", "body": "Please pay soon."})
    )
    monkeypatch.setattr(
        tasks.GeminiProvider, "from_settings", staticmethod(lambda api_key, model: fake)
    )

    tasks.run_invoice_chaser.app.conf.task_always_eager = True
    try:
        result = tasks.run_invoice_chaser.delay(tenant_id=tenant.id, workflow_id=workflow.id)
        result.get()
    finally:
        tasks.run_invoice_chaser.app.conf.task_always_eager = False

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
