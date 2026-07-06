import pytest
from pydantic import ValidationError

from apps.invoices.schemas import InvoiceReminderDraft


def test_valid_draft_parses():
    draft = InvoiceReminderDraft(subject="Invoice overdue", body="Please pay by Friday.")
    assert draft.subject == "Invoice overdue"


def test_empty_subject_is_rejected():
    with pytest.raises(ValidationError):
        InvoiceReminderDraft(subject="", body="Please pay by Friday.")


def test_empty_body_is_rejected():
    with pytest.raises(ValidationError):
        InvoiceReminderDraft(subject="Invoice overdue", body="")
