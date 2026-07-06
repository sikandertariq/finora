import pytest

from apps.agents import services, tasks
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def test_scan_overdue_invoices_runs_the_scheduler_once_per_tenant_and_clears_context(monkeypatch):
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    seen_tenants = []

    def fake_scan():
        seen_tenants.append(context.get_current_tenant_id())
        return []

    monkeypatch.setattr(services.InvoiceChaserScheduler, "scan_and_dispatch", staticmethod(fake_scan))

    tasks.scan_overdue_invoices.apply().get()

    assert set(seen_tenants) == {tenant_a.id, tenant_b.id}
    assert context.get_current_tenant_id() is None


def test_scan_overdue_invoices_clears_context_even_if_one_tenant_errors(monkeypatch):
    tenant_a = TenantFactory()
    TenantFactory()

    def flaky_scan():
        if context.get_current_tenant_id() == tenant_a.id:
            raise RuntimeError("boom")
        return []

    monkeypatch.setattr(services.InvoiceChaserScheduler, "scan_and_dispatch", staticmethod(flaky_scan))

    with pytest.raises(RuntimeError):
        tasks.scan_overdue_invoices.apply().get()

    assert context.get_current_tenant_id() is None
