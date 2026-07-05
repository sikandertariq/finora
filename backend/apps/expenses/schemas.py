from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class LineItem(BaseModel):
    description: str
    amount: Decimal = Field(gt=0)


class ReceiptExtraction(BaseModel):
    """What an LLM must produce from a receipt before it's allowed near the database.

    Parsing into this model IS the safety boundary: if the LLM's output doesn't fit this
    shape, it never reaches ExpenseService. ``missing_fields`` lets the agent say "I
    couldn't read this confidently" instead of guessing.
    """

    vendor: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    expense_date: date
    category_suggestion: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=1.0)
    missing_fields: list[str] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def _uppercase_currency(cls, value: str) -> str:
        return value.upper()
