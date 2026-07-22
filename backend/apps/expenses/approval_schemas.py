from typing import Literal

from pydantic import BaseModel, Field


class ExpenseApprovalAssessment(BaseModel):
    """Validated LLM assessment shown to a human expense reviewer."""

    recommendation: Literal["approve", "reject", "needs_more_information"]
    rationale: str = Field(min_length=1)
    policy_flags: list[str] = Field(default_factory=list)
    anomaly_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
