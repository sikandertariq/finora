import json

import pytest

from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.agents.services import InvoiceChaserService
from apps.invoices.models import Invoice
from apps.tenancy import context
from tests.factories import TenantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def _workflow_for_invoice(escalation_level="day_7"):
    invoice = Invoice.objects.create(
        client_name="Acme", client_email="ap@acme.test", amount="100.00",
        issue_date="2026-06-01", due_date="2026-06-15", status=Invoice.Status.SENT,
    )
    return AgentWorkflow.objects.create(
        workflow_type="invoice_chaser", invoice=invoice,
        extracted_data={"escalation_level": escalation_level},
    )


_VALID_DRAFT = {"subject": "Invoice overdue", "body": "Please settle this at your earliest convenience."}


def test_well_formed_response_lands_in_needs_review_with_subject_and_body():
    workflow = _workflow_for_invoice()
    provider = FakeLLMProvider(response=json.dumps(_VALID_DRAFT))

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["subject"] == "Invoice overdue"
    assert workflow.extracted_data["body"] == _VALID_DRAFT["body"]
    assert workflow.error_message == ""


def test_escalation_level_survives_alongside_the_draft():
    workflow = _workflow_for_invoice(escalation_level="day_14")
    provider = FakeLLMProvider(response=json.dumps(_VALID_DRAFT))

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.extracted_data["escalation_level"] == "day_14"


def test_response_wrapped_in_a_markdown_code_fence_still_parses():
    workflow = _workflow_for_invoice()
    fenced = "```json\n" + json.dumps(_VALID_DRAFT) + "\n```"
    provider = FakeLLMProvider(response=fenced)

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["subject"] == "Invoice overdue"


def test_malformed_json_lands_in_needs_review_with_an_error_and_keeps_escalation_level():
    workflow = _workflow_for_invoice(escalation_level="day_1")
    provider = FakeLLMProvider(response="not json at all")

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == {"escalation_level": "day_1"}
    assert "Could not draft a reminder" in workflow.error_message


def test_response_failing_schema_validation_lands_in_needs_review_with_an_error():
    workflow = _workflow_for_invoice()
    provider = FakeLLMProvider(response=json.dumps({"subject": "", "body": "x"}))

    InvoiceChaserService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.error_message != ""


def test_the_prompt_names_the_client_and_amount():
    workflow = _workflow_for_invoice()
    provider = FakeLLMProvider(response=json.dumps(_VALID_DRAFT))

    InvoiceChaserService(provider).run(workflow)

    user_message = provider.calls[0][1]
    assert "Acme" in user_message.content
    assert "100.00" in user_message.content
