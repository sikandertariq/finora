import json

import pytest

from apps.agents.llm import FakeLLMProvider
from apps.agents.models import AgentWorkflow
from apps.agents.services import ExpenseApproverService
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


_VALID_ASSESSMENT = {
    "recommendation": "approve",
    "rationale": "The travel expense matches this tenant's normal policy.",
    "policy_flags": ["Category is covered by the selected policy."],
    "anomaly_flags": [],
    "confidence": 0.92,
}


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


def _policy_metadata(policy):
    return {
        "policy": {
            "id": policy.id,
            "name": policy.name,
            "approval_queue": policy.approval_queue,
            "minimum_amount": str(policy.minimum_amount),
            "maximum_amount": str(policy.maximum_amount),
        }
    }


def _workflow(policy=None):
    policy = policy or _policy()
    return AgentWorkflow.objects.create(
        workflow_type="expense_approver",
        expense=_expense(),
        extracted_data=_policy_metadata(policy),
    )


def test_valid_json_lands_in_needs_review_and_merges_assessment_with_policy_metadata():
    workflow = _workflow()
    provider = FakeLLMProvider(response=json.dumps(_VALID_ASSESSMENT))

    ExpenseApproverService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["policy"]["approval_queue"] == "Operations"
    assert workflow.extracted_data["recommendation"] == "approve"
    assert workflow.extracted_data["rationale"] == _VALID_ASSESSMENT["rationale"]
    assert workflow.extracted_data["policy_flags"] == [
        "Amount exceeds the selected policy ceiling of 500.00.",
        "Category is covered by the selected policy.",
    ]
    assert workflow.error_message == ""


def test_fenced_json_lands_in_needs_review_with_validated_assessment():
    workflow = _workflow()
    provider = FakeLLMProvider(response=f"```json\n{json.dumps(_VALID_ASSESSMENT)}\n```")

    ExpenseApproverService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data["recommendation"] == "approve"


def test_malformed_json_keeps_deterministic_policy_metadata_and_records_an_error():
    workflow = _workflow()
    expected_metadata = {
        **workflow.extracted_data,
        "policy_flags": ["Amount exceeds the selected policy ceiling of 500.00."],
    }
    provider = FakeLLMProvider(response="not valid json")

    ExpenseApproverService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == expected_metadata
    assert "Could not assess this expense" in workflow.error_message


def test_schema_failure_keeps_deterministic_policy_metadata_and_records_an_error():
    workflow = _workflow()
    expected_metadata = {
        **workflow.extracted_data,
        "policy_flags": ["Amount exceeds the selected policy ceiling of 500.00."],
    }
    provider = FakeLLMProvider(response=json.dumps({**_VALID_ASSESSMENT, "confidence": 2}))

    ExpenseApproverService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == expected_metadata
    assert "Could not assess this expense" in workflow.error_message


def test_json_that_is_not_an_assessment_object_keeps_policy_metadata_and_records_an_error():
    workflow = _workflow()
    expected_metadata = {
        **workflow.extracted_data,
        "policy_flags": ["Amount exceeds the selected policy ceiling of 500.00."],
    }
    provider = FakeLLMProvider(response=json.dumps(["not", "an", "assessment"]))

    ExpenseApproverService(provider).run(workflow)

    workflow.refresh_from_db()
    assert workflow.status == AgentWorkflow.Status.NEEDS_REVIEW
    assert workflow.extracted_data == expected_metadata
    assert "Could not assess this expense" in workflow.error_message


def test_prompt_includes_expense_and_selected_policy_context():
    workflow = _workflow()
    provider = FakeLLMProvider(response=json.dumps(_VALID_ASSESSMENT))

    ExpenseApproverService(provider).run(workflow)

    prompt = provider.calls[0][1].content
    assert "Railway Co." in prompt
    assert "650.00" in prompt
    assert "Travel review" in prompt
    assert "Operations" in prompt
    assert "500.00" in prompt


def test_prompt_includes_recent_approved_and_rejected_tenant_outcomes_only():
    workflow = _workflow()
    approved = AgentWorkflow.objects.create(
        workflow_type="expense_approver",
        expense=_expense(),
        extracted_data={"recommendation": "approve", "rationale": "Established supplier."},
    )
    approved.mark_approved(reviewed_by=UserFactory())
    rejected = AgentWorkflow.objects.create(
        workflow_type="expense_approver",
        expense=_expense(),
        extracted_data={"recommendation": "reject", "rationale": "Duplicate receipt."},
    )
    rejected.mark_rejected(reviewed_by=UserFactory())
    provider = FakeLLMProvider(response=json.dumps(_VALID_ASSESSMENT))

    ExpenseApproverService(provider).run(workflow)

    prompt = provider.calls[0][1].content
    assert "Established supplier." in prompt
    assert "Duplicate receipt." in prompt
    assert "approved" in prompt
    assert "rejected" in prompt
