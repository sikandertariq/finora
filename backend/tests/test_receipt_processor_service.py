import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.agents.services import ReceiptProcessorService
from apps.expenses.models import Receipt
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def _workflow_with_receipt(user, file_bytes=b"fake-receipt-bytes", filename="receipt.jpg"):
    receipt = Receipt.objects.create(
        uploaded_by=user, file=SimpleUploadedFile(filename, file_bytes, content_type="image/jpeg")
    )
    return AgentWorkflow.objects.create(receipt=receipt)


_VALID_EXTRACTION = {
    "vendor": "Staples",
    "amount": "42.50",
    "currency": "usd",
    "expense_date": "2026-07-01",
    "category_suggestion": "office supplies",
    "line_items": [{"description": "Paper", "amount": "12.50"}],
    "confidence": 0.9,
    "missing_fields": [],
}


def test_well_formed_response_lands_in_needs_review_with_extracted_data():
    user = UserFactory()
    workflow = _workflow_with_receipt(user)
    provider = FakeLLMProvider(response=json.dumps(_VALID_EXTRACTION))

    ReceiptProcessorService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["vendor"] == "Staples"
    assert workflow.extracted_data["currency"] == "USD"
    assert workflow.error_message == ""


def test_response_wrapped_in_a_markdown_code_fence_still_parses():
    user = UserFactory()
    workflow = _workflow_with_receipt(user)
    fenced = "```json\n" + json.dumps(_VALID_EXTRACTION) + "\n```"
    provider = FakeLLMProvider(response=fenced)

    ReceiptProcessorService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["vendor"] == "Staples"


def test_malformed_json_lands_in_needs_review_with_an_error_not_a_crash():
    user = UserFactory()
    workflow = _workflow_with_receipt(user)
    provider = FakeLLMProvider(response="not json at all")

    ReceiptProcessorService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == {}
    assert "Could not extract data" in workflow.error_message


def test_json_that_fails_schema_validation_lands_in_needs_review_with_an_error():
    user = UserFactory()
    workflow = _workflow_with_receipt(user)
    bad_payload = dict(_VALID_EXTRACTION, amount="-5.00")
    provider = FakeLLMProvider(response=json.dumps(bad_payload))

    ReceiptProcessorService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == {}
    assert workflow.error_message != ""


def test_the_receipts_actual_file_bytes_are_sent_to_the_llm():
    user = UserFactory()
    workflow = _workflow_with_receipt(user, file_bytes=b"specific-bytes")
    provider = FakeLLMProvider(response=json.dumps(_VALID_EXTRACTION))

    ReceiptProcessorService(provider).run(workflow)

    user_message = provider.calls[0][1]
    assert user_message.image == b"specific-bytes"
    assert user_message.image_mime_type == "image/jpeg"
