import pytest
from pydantic import ValidationError

from apps.expenses.approval_schemas import ExpenseApprovalAssessment


def test_valid_assessment_parses():
    assessment = ExpenseApprovalAssessment(
        recommendation="approve",
        rationale="The amount and category match the policy.",
        policy_flags=["Within normal travel spend."],
        anomaly_flags=[],
        confidence=0.92,
    )

    assert assessment.recommendation == "approve"
    assert assessment.confidence == 0.92


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_assessment_rejects_confidence_outside_zero_to_one(confidence):
    with pytest.raises(ValidationError):
        ExpenseApprovalAssessment(
            recommendation="reject",
            rationale="The amount needs review.",
            policy_flags=[],
            anomaly_flags=[],
            confidence=confidence,
        )


def test_assessment_rejects_unknown_recommendation():
    with pytest.raises(ValidationError):
        ExpenseApprovalAssessment(
            recommendation="auto_approve",
            rationale="The amount is low.",
            policy_flags=[],
            anomaly_flags=[],
            confidence=0.8,
        )
