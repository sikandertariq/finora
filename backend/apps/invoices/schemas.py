from pydantic import BaseModel, Field


class InvoiceReminderDraft(BaseModel):
    """What an LLM must produce when drafting an overdue-invoice reminder.

    Deliberately no ``escalation_level``/``tone`` field: which tone to draft is decided
    by our own code from days-overdue and fed *into* the prompt, not asked of the LLM --
    that's a deterministic decision, not one to add hallucination surface for.
    """

    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
