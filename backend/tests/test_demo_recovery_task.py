import pytest

from apps.agents import tasks


pytestmark = pytest.mark.django_db


def test_recover_demo_resets_data_then_queues_invoice_scan(monkeypatch, settings):
    settings.DEMO_USER_PASSWORD = "configured-demo-password"
    calls = []

    monkeypatch.setattr(
        tasks.DemoDataService,
        "reset",
        lambda *, password: calls.append(("reset", password)),
    )
    monkeypatch.setattr(
        tasks.scan_overdue_invoices,
        "delay",
        lambda: calls.append(("scan",)),
    )

    tasks.recover_demo.run()

    assert calls == [("reset", "configured-demo-password"), ("scan",)]
