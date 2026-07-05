import json

import pytest
from pydantic import ValidationError

from apps.agents.llm import FakeLLMProvider, LLMMessage
from apps.expenses.schemas import ReceiptExtraction


def _run_extraction(provider):
    response = provider.complete([LLMMessage(role="user", content="extract this receipt")])
    return ReceiptExtraction(**json.loads(response.content))


def test_well_formed_llm_output_becomes_a_receipt_extraction():
    provider = FakeLLMProvider(
        response=json.dumps(
            {
                "vendor": "Staples",
                "amount": "42.50",
                "currency": "usd",
                "expense_date": "2026-07-01",
                "category_suggestion": "office supplies",
                "line_items": [{"description": "Paper", "amount": "12.50"}],
                "confidence": 0.9,
            }
        )
    )

    extraction = _run_extraction(provider)

    assert extraction.vendor == "Staples"
    assert extraction.currency == "USD"


def test_malformed_llm_output_never_becomes_an_extraction():
    provider = FakeLLMProvider(response=json.dumps({"vendor": "Staples", "amount": "-5.00"}))

    with pytest.raises(ValidationError):
        _run_extraction(provider)
