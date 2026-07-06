from datetime import timedelta

import pytest
from django.utils import timezone

from apps.agents import tasks
from apps.agents.models import AgentWorkflow
from apps.agents.services import InvoiceChaserScheduler
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


def _invoice_overdue_by(days, status=Invoice.Status.SENT):
    today = timezone.localdate()
    due = today - timedelta(days=days)
    return InvoiceService.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date=due - timedelta(days=15), due_date=due, status=status,
    )


def test_invoice_at_first_threshold_starts_a_workflow(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: calls.append(kw))
    invoice = _invoice_overdue_by(1)

    started = InvoiceChaserScheduler.scan_and_dispatch()

    assert len(started) == 1
    workflow = started[0]
    assert workflow.workflow_type == "invoice_chaser"
    assert workflow.invoice_id == invoice.id
    assert workflow.extracted_data == {"escalation_level": "day_1"}
    assert calls == [{"tenant_id": invoice.tenant_id, "workflow_id": workflow.id}]


def test_invoice_overdue_by_20_days_gets_the_14_day_level_not_7(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    _invoice_overdue_by(20)

    started = InvoiceChaserScheduler.scan_and_dispatch()

    assert started[0].extracted_data["escalation_level"] == "day_14"


def test_invoice_not_yet_overdue_is_skipped(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    _invoice_overdue_by(0)

    assert InvoiceChaserScheduler.scan_and_dispatch() == []


@pytest.mark.parametrize("status", [Invoice.Status.PAID, Invoice.Status.VOID, Invoice.Status.DRAFT])
def test_invoices_in_excluded_statuses_are_skipped(monkeypatch, status):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    _invoice_overdue_by(10, status=status)

    assert InvoiceChaserScheduler.scan_and_dispatch() == []


def test_already_reminded_at_this_level_is_not_duplicated(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    invoice = _invoice_overdue_by(7)

    first_run = InvoiceChaserScheduler.scan_and_dispatch()
    second_run = InvoiceChaserScheduler.scan_and_dispatch()

    assert len(first_run) == 1
    assert second_run == []
    assert AgentWorkflow.objects.filter(invoice=invoice, workflow_type="invoice_chaser").count() == 1


def test_crossing_a_new_threshold_starts_a_second_workflow(monkeypatch):
    monkeypatch.setattr(tasks.run_invoice_chaser, "delay", lambda **kw: None)
    invoice = _invoice_overdue_by(7)
    InvoiceChaserScheduler.scan_and_dispatch()  # day_7 workflow already exists now

    invoice.due_date = timezone.localdate() - timedelta(days=14)
    invoice.save()
    second_run = InvoiceChaserScheduler.scan_and_dispatch()

    assert len(second_run) == 1
    assert second_run[0].extracted_data["escalation_level"] == "day_14"
    assert AgentWorkflow.objects.filter(invoice=invoice, workflow_type="invoice_chaser").count() == 2
