import json
import mimetypes

from pydantic import ValidationError

from apps.expenses.schemas import ReceiptExtraction
from apps.expenses.services import ExpenseService

from .llm import LLMMessage, LLMProvider
from .models import AgentWorkflow

_SYSTEM_PROMPT = (
    "You are a receipt-extraction assistant. Given a photo or scan of a receipt, respond "
    "with ONLY a JSON object (no markdown, no commentary) matching this shape:\n"
    '{"vendor": str, "amount": str, "currency": "USD", "expense_date": "YYYY-MM-DD", '
    '"category_suggestion": str or null, "line_items": [{"description": str, "amount": str}], '
    '"confidence": float between 0 and 1, "missing_fields": [str]}\n'
    "If you cannot confidently read a field, add its name to missing_fields instead of "
    "guessing."
)


class ReceiptProcessorService:
    """Runs the Receipt Processor agent against one AgentWorkflow's receipt.

    Takes an LLMProvider, not a vendor SDK, so this is exactly as testable with a fake as
    ExpenseService is — and exactly as reusable from a Celery task as it is from anywhere else.
    """

    def __init__(self, llm_provider: LLMProvider):
        self._llm = llm_provider

    def run(self, workflow: AgentWorkflow) -> AgentWorkflow:
        workflow.mark_running()
        try:
            response = self._llm.complete(self._build_messages(workflow.receipt))
            extraction = ReceiptExtraction(**json.loads(_strip_code_fence(response.content)))
        except (json.JSONDecodeError, ValidationError) as exc:
            workflow.mark_needs_review(
                error_message=f"Could not extract data from this receipt: {exc}"
            )
            return workflow
        workflow.mark_needs_review(extracted_data=extraction.model_dump(mode="json"))
        return workflow

    @staticmethod
    def _build_messages(receipt) -> list[LLMMessage]:
        with receipt.file.open("rb") as f:
            image_bytes = f.read()
        mime_type = mimetypes.guess_type(receipt.file.name)[0] or "application/octet-stream"
        return [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content="Extract this receipt's data as instructed.",
                image=image_bytes,
                image_mime_type=mime_type,
            ),
        ]


class AgentWorkflowService:
    """Everything a human (via an endpoint) does to a workflow once it needs review.

    Kept separate from ReceiptProcessorService: that one runs the AI, this one runs what
    happens to its output — starting a run and approving/rejecting are both things a
    caller outside the AI step needs, not part of the extraction pipeline itself.
    """

    @staticmethod
    def start_receipt_processing(receipt) -> AgentWorkflow:
        workflow = AgentWorkflow.objects.create(receipt=receipt)
        from .tasks import run_receipt_processor  # local import: tasks.py imports this module

        run_receipt_processor.delay(tenant_id=receipt.tenant_id, workflow_id=workflow.id)
        return workflow

    @staticmethod
    def approve(workflow: AgentWorkflow, *, reviewed_by, overrides: dict | None = None) -> AgentWorkflow:
        data = workflow.extracted_data
        fields = {
            "vendor": data.get("vendor"),
            "amount": data.get("amount"),
            "currency": data.get("currency", "USD"),
            "category": data.get("category_suggestion") or "",
            "expense_date": data.get("expense_date"),
        }
        for key, value in (overrides or {}).items():
            if value is not None:
                fields[key] = value
        expense = ExpenseService.create(
            created_by=reviewed_by, receipt=workflow.receipt, **fields
        )
        workflow.mark_approved(reviewed_by=reviewed_by, resulting_expense=expense)
        return workflow

    @staticmethod
    def reject(workflow: AgentWorkflow, *, reviewed_by) -> AgentWorkflow:
        workflow.mark_rejected(reviewed_by=reviewed_by)
        return workflow


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = stripped.strip("`")
    if stripped.startswith("json"):
        stripped = stripped[len("json") :]
    return stripped.strip()
