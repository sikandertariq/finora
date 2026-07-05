import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agents import tasks
from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.expenses.models import Receipt
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def test_task_binds_tenant_context_and_runs_the_processor(monkeypatch):
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    user = UserFactory()
    receipt = Receipt.objects.create(
        uploaded_by=user,
        file=SimpleUploadedFile("r.jpg", b"bytes", content_type="image/jpeg"),
    )
    workflow = AgentWorkflow.objects.create(receipt=receipt)
    context.clear_current_tenant()  # prove the task binds it, this isn't just test leakage

    fake = FakeLLMProvider(
        response=json.dumps(
            {
                "vendor": "Staples",
                "amount": "10.00",
                "currency": "USD",
                "expense_date": "2026-07-01",
                "line_items": [],
                "confidence": 0.9,
            }
        )
    )
    monkeypatch.setattr(
        tasks.GeminiProvider, "from_settings", staticmethod(lambda api_key, model: fake)
    )

    tasks.run_receipt_processor.apply(
        kwargs={"tenant_id": tenant.id, "workflow_id": workflow.id}
    ).get()

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["vendor"] == "Staples"
    assert context.get_current_tenant_id() is None
