import pytest
from pydantic import ValidationError

from apps.expenses.schemas import ReceiptExtraction


def _valid_payload(**overrides):
    payload = dict(
        vendor="Staples",
        amount="42.50",
        currency="usd",
        expense_date="2026-07-01",
        category_suggestion="office supplies",
        line_items=[
            {"description": "Paper", "amount": "12.50"},
            {"description": "Pens", "amount": "30.00"},
        ],
        confidence=0.92,
    )
    payload.update(overrides)
    return payload


def test_valid_extraction_parses_and_normalizes_currency():
    extraction = ReceiptExtraction(**_valid_payload())

    assert extraction.vendor == "Staples"
    assert extraction.currency == "USD"
    assert len(extraction.line_items) == 2


def test_missing_vendor_is_rejected():
    payload = _valid_payload()
    del payload["vendor"]

    with pytest.raises(ValidationError):
        ReceiptExtraction(**payload)


def test_non_positive_amount_is_rejected():
    with pytest.raises(ValidationError):
        ReceiptExtraction(**_valid_payload(amount="0"))


def test_confidence_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        ReceiptExtraction(**_valid_payload(confidence=1.5))


def test_line_item_with_non_positive_amount_is_rejected():
    with pytest.raises(ValidationError):
        ReceiptExtraction(**_valid_payload(line_items=[{"description": "bad", "amount": "-1"}]))


def test_extraction_can_flag_fields_it_could_not_read_confidently():
    extraction = ReceiptExtraction(
        **_valid_payload(category_suggestion=None, missing_fields=["category_suggestion"])
    )

    assert extraction.missing_fields == ["category_suggestion"]
