import json
import mimetypes
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.expenses.approval_schemas import ExpenseApprovalAssessment
from apps.expenses.approval_services import ExpenseApprovalPolicyService
from apps.expenses.models import Expense
from apps.expenses.schemas import ReceiptExtraction
from apps.expenses.services import ExpenseService
from apps.invoices.models import Invoice
from apps.invoices.schemas import InvoiceReminderDraft

from .llm import LLMMessage, LLMProvider
from .models import AgentWorkflow, AuditLog

_SYSTEM_PROMPT = (
    "You are a receipt-extraction assistant. Given a photo or scan of a receipt, respond "
    "with ONLY a JSON object (no markdown, no commentary) matching this shape:\n"
    '{"vendor": str, "amount": str, "currency": "USD", "expense_date": "YYYY-MM-DD", '
    '"category_suggestion": str or null, "line_items": [{"description": str, "amount": str}], '
    '"confidence": float between 0 and 1, "missing_fields": [str]}\n'
    "If you cannot confidently read a field, add its name to missing_fields instead of "
    "guessing."
)

_INVOICE_CHASER_SYSTEM_PROMPT = (
    "You are an accounts-receivable assistant drafting a reminder email about an "
    "overdue invoice. Respond with ONLY a JSON object (no markdown, no commentary) "
    'matching this shape: {"subject": str, "body": str}. Match the requested tone.'
)

_EXPENSE_APPROVER_SYSTEM_PROMPT = (
    "You are a finance assistant assessing an expense for a human reviewer. Respond with ONLY "
    "a JSON object (no markdown, no commentary) matching this shape: "
    '{"recommendation": "approve" | "reject" | "needs_more_information", '
    '"rationale": str, "policy_flags": [str], "anomaly_flags": [str], '
    '"confidence": float between 0 and 1}. Do not approve or reject the expense yourself; '
    "provide a recommendation for a person to review."
)

# (threshold_days, level_key, tone) -- shared with InvoiceChaserScheduler (Task 7).
# Deliberately a flat constant, not a per-tenant rules model (see design spec).
_ESCALATION_LEVELS = [
    (1, "day_1", "a polite reminder"),
    (7, "day_7", "a polite reminder"),
    (14, "day_14", "a firmer follow-up"),
    (30, "day_30", "a final notice"),
]


def _tone_for_level(level_key):
    for _, key, tone in _ESCALATION_LEVELS:
        if key == level_key:
            return tone
    # Defensive fallback only -- this should never be reached in normal operation.
    # InvoiceChaserScheduler always sets a valid escalation_level on extracted_data
    # before InvoiceChaserService.run() ever reads it. If we land here, extracted_data
    # was corrupted or tampered with; we still produce a usable (if generically-toned)
    # email rather than crashing the Celery task, but this is not a real state a user
    # should expect to hit.
    return "a reminder"


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


class InvoiceChaserService:
    """Runs the Invoice Chaser agent against one AgentWorkflow's invoice.

    Same shape as ReceiptProcessorService: inject an LLMProvider, call it, validate
    the result through a Pydantic schema before it touches the workflow row.
    """

    def __init__(self, llm_provider: LLMProvider):
        self._llm = llm_provider

    def run(self, workflow: AgentWorkflow) -> AgentWorkflow:
        workflow.mark_running()
        invoice = workflow.invoice
        tone = _tone_for_level(workflow.extracted_data.get("escalation_level"))
        try:
            response = self._llm.complete(self._build_messages(invoice, tone))
            draft = InvoiceReminderDraft(**json.loads(_strip_code_fence(response.content)))
        except (json.JSONDecodeError, ValidationError) as exc:
            workflow.mark_needs_review(
                extracted_data=workflow.extracted_data,
                error_message=f"Could not draft a reminder for this invoice: {exc}",
            )
            return workflow
        workflow.mark_needs_review(
            extracted_data={**workflow.extracted_data, **draft.model_dump(mode="json")}
        )
        return workflow

    @staticmethod
    def _build_messages(invoice, tone) -> list[LLMMessage]:
        return [
            LLMMessage(role="system", content=_INVOICE_CHASER_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    f"Draft {tone} to {invoice.client_name} <{invoice.client_email}> "
                    f"about their invoice for {invoice.amount} {invoice.currency}, "
                    f"which was due on {invoice.due_date}."
                ),
            ),
        ]


class ExpenseApproverService:
    """Runs an LLM-backed assessment while preserving deterministic policy context."""

    def __init__(self, llm_provider: LLMProvider):
        self._llm = llm_provider

    def run(self, workflow: AgentWorkflow) -> AgentWorkflow:
        workflow.mark_running()
        deterministic_metadata = {
            **workflow.extracted_data,
            "policy_flags": _deterministic_policy_flags(
                workflow.expense, workflow.extracted_data
            ),
        }
        try:
            response = self._llm.complete(self._build_messages(workflow))
            assessment = ExpenseApprovalAssessment(
                **json.loads(_strip_code_fence(response.content))
            )
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            workflow.mark_needs_review(
                extracted_data=deterministic_metadata,
                error_message=f"Could not assess this expense: {exc}",
            )
            return workflow

        assessment_data = assessment.model_dump(mode="json")
        deterministic_flags = deterministic_metadata.get("policy_flags", [])
        workflow.mark_needs_review(
            extracted_data={
                **deterministic_metadata,
                **assessment_data,
                "policy_flags": [*deterministic_flags, *assessment_data["policy_flags"]],
            }
        )
        return workflow

    @staticmethod
    def _build_messages(workflow: AgentWorkflow) -> list[LLMMessage]:
        expense = workflow.expense
        policy = workflow.extracted_data.get("policy", {})
        historical_outcomes = []
        recent_workflows = (
            AgentWorkflow.objects.filter(
                workflow_type="expense_approver",
                status__in=[AgentWorkflow.Status.APPROVED, AgentWorkflow.Status.REJECTED],
            )
            .exclude(pk=workflow.pk)
            .select_related("expense")
            .order_by("-updated_at")[:5]
        )
        for prior_workflow in recent_workflows:
            prior_expense = prior_workflow.expense
            historical_outcomes.append(
                {
                    "outcome": prior_workflow.status,
                    "expense": {
                        "vendor": prior_expense.vendor,
                        "amount": str(prior_expense.amount),
                        "currency": prior_expense.currency,
                        "category": prior_expense.category,
                    },
                    "assessment": {
                        key: prior_workflow.extracted_data.get(key)
                        for key in ("recommendation", "rationale", "policy_flags", "anomaly_flags")
                        if key in prior_workflow.extracted_data
                    },
                }
            )
        return [
            LLMMessage(role="system", content=_EXPENSE_APPROVER_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    "Assess this expense for human review.\n"
                    f"Expense: {json.dumps({
                        'vendor': expense.vendor,
                        'amount': str(expense.amount),
                        'currency': expense.currency,
                        'category': expense.category,
                        'description': expense.description,
                        'expense_date': str(expense.expense_date),
                    })}\n"
                    f"Selected policy and deterministic flags: {json.dumps({
                        'policy': policy,
                        'policy_flags': workflow.extracted_data.get('policy_flags', []),
                    })}\n"
                    f"Recent tenant outcomes: {json.dumps(historical_outcomes)}"
                ),
            ),
        ]


class InvoiceChaserScheduler:
    """Finds overdue invoices that just crossed a new escalation threshold and starts
    one AgentWorkflow per (invoice, threshold). Runs within the caller's tenant
    context -- it does not set one itself. apps.agents.tasks.scan_overdue_invoices
    (the Celery beat task) sets that context once per tenant and calls this."""

    _EXCLUDED_STATUSES = [Invoice.Status.PAID, Invoice.Status.VOID, Invoice.Status.DRAFT]

    @staticmethod
    def scan_and_dispatch() -> list[AgentWorkflow]:
        from .tasks import run_invoice_chaser  # local import, same reason as start_receipt_processing

        today = timezone.localdate()
        started = []
        chaseable = Invoice.objects.exclude(
            status__in=InvoiceChaserScheduler._EXCLUDED_STATUSES
        ).filter(due_date__lt=today)

        for invoice in chaseable:
            days_overdue = (today - invoice.due_date).days
            level = _reached_level(days_overdue)
            if level is None:
                continue
            _, level_key, _tone = level
            already_reminded = AgentWorkflow.objects.filter(
                invoice=invoice, workflow_type="invoice_chaser",
                extracted_data__escalation_level=level_key,
            ).exists()
            if already_reminded:
                continue
            workflow = AgentWorkflow.objects.create(
                workflow_type="invoice_chaser", invoice=invoice,
                extracted_data={"escalation_level": level_key},
            )
            run_invoice_chaser.delay(tenant_id=invoice.tenant_id, workflow_id=workflow.id)
            started.append(workflow)
        return started


def _reached_level(days_overdue):
    reached = None
    for threshold_days, level_key, tone in _ESCALATION_LEVELS:
        if days_overdue >= threshold_days:
            reached = (threshold_days, level_key, tone)
    return reached


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
        _require_needs_review(workflow)
        if workflow.workflow_type == "expense_approver":
            return AgentWorkflowService._approve_expense_approver(
                workflow, reviewed_by=reviewed_by
            )
        if workflow.workflow_type == "invoice_chaser":
            return AgentWorkflowService._approve_invoice_chaser(
                workflow, reviewed_by=reviewed_by, overrides=overrides
            )
        return AgentWorkflowService._approve_receipt_processor(
            workflow, reviewed_by=reviewed_by, overrides=overrides
        )

    @staticmethod
    def _approve_receipt_processor(workflow: AgentWorkflow, *, reviewed_by, overrides) -> AgentWorkflow:
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
        AuditLog.objects.create(
            workflow=workflow,
            actor=reviewed_by,
            action="approved",
            metadata={"resulting_expense_id": expense.id, "overrides": overrides or {}},
        )
        return workflow

    @staticmethod
    def _approve_expense_approver(workflow: AgentWorkflow, *, reviewed_by) -> AgentWorkflow:
        expense = workflow.expense
        expense.approval_status = Expense.ApprovalStatus.APPROVED
        expense.save(update_fields=["approval_status", "updated_at"])
        workflow.mark_approved(reviewed_by=reviewed_by)
        AuditLog.objects.create(
            workflow=workflow, actor=reviewed_by, action="expense_approved"
        )
        return workflow

    @staticmethod
    def _approve_invoice_chaser(workflow: AgentWorkflow, *, reviewed_by, overrides) -> AgentWorkflow:
        """Simulated send: writes what would have been emailed to AuditLog. No real
        SMTP/SendGrid call -- see the design spec's explicit non-goal on this."""
        data = workflow.extracted_data
        overrides = overrides or {}
        subject = overrides.get("subject") or data.get("subject")
        body = overrides.get("body") or data.get("body")
        workflow.mark_approved(reviewed_by=reviewed_by)
        AuditLog.objects.create(
            workflow=workflow,
            actor=reviewed_by,
            action="reminder_sent",
            metadata={"subject": subject, "body": body, "to": workflow.invoice.client_email},
        )
        return workflow

    @staticmethod
    def reject(workflow: AgentWorkflow, *, reviewed_by, note: str | None = None) -> AgentWorkflow:
        _require_needs_review(workflow)
        if workflow.workflow_type == "expense_approver":
            return AgentWorkflowService._reject_expense_approver(
                workflow, reviewed_by=reviewed_by, note=note
            )
        workflow.mark_rejected(reviewed_by=reviewed_by)
        AuditLog.objects.create(
            workflow=workflow,
            actor=reviewed_by,
            action="rejected",
            metadata=_rejection_metadata(note),
        )
        return workflow

    @staticmethod
    def _reject_expense_approver(workflow: AgentWorkflow, *, reviewed_by, note) -> AgentWorkflow:
        expense = workflow.expense
        expense.approval_status = Expense.ApprovalStatus.REJECTED
        expense.save(update_fields=["approval_status", "updated_at"])
        workflow.mark_rejected(reviewed_by=reviewed_by)
        AuditLog.objects.create(
            workflow=workflow,
            actor=reviewed_by,
            action="expense_rejected",
            metadata=_rejection_metadata(note),
        )
        return workflow


class ExpenseApprovalService:
    """Starts one reviewable Expense Approver run for a tenant-scoped expense."""

    _ACTIVE_STATUSES = [
        AgentWorkflow.Status.PENDING,
        AgentWorkflow.Status.RUNNING,
        AgentWorkflow.Status.NEEDS_REVIEW,
    ]

    @classmethod
    def start(cls, expense) -> AgentWorkflow:
        from .tasks import run_expense_approver

        with transaction.atomic():
            expense = Expense.objects.select_for_update().get(pk=expense.pk)
            if AgentWorkflow.objects.filter(
                workflow_type="expense_approver",
                expense=expense,
                status__in=cls._ACTIVE_STATUSES,
            ).exists():
                raise ValueError("Expense already has an active expense approval workflow.")

            policy = ExpenseApprovalPolicyService.matching_policy(expense)
            workflow = AgentWorkflow.objects.create(
                workflow_type="expense_approver",
                expense=expense,
                extracted_data={
                    "policy": _policy_metadata(policy),
                    "approval_queue": policy.approval_queue if policy else "Finance",
                },
            )
            expense.approval_status = Expense.ApprovalStatus.PENDING
            expense.save(update_fields=["approval_status", "updated_at"])
            transaction.on_commit(
                lambda: run_expense_approver.delay(
                    tenant_id=expense.tenant_id, workflow_id=workflow.id
                )
            )
        return workflow


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = stripped.strip("`")
    if stripped.startswith("json"):
        stripped = stripped[len("json") :]
    return stripped.strip()


def _policy_metadata(policy) -> dict:
    if policy is None:
        return {}
    return {
        "id": policy.id,
        "name": policy.name,
        "priority": policy.priority,
        "category": policy.category,
        "minimum_amount": str(policy.minimum_amount),
        "maximum_amount": (
            str(policy.maximum_amount) if policy.maximum_amount is not None else None
        ),
        "approval_queue": policy.approval_queue,
    }


def _rejection_metadata(note: str | None) -> dict:
    return {"note": note} if note is not None else {}


def _require_needs_review(workflow: AgentWorkflow) -> None:
    if workflow.status != AgentWorkflow.Status.NEEDS_REVIEW:
        raise ValueError("Workflow must be in needs_review before a human decision.")


def _deterministic_policy_flags(expense, metadata: dict) -> list[str]:
    flags = list(metadata.get("policy_flags", []))
    maximum_amount = metadata.get("policy", {}).get("maximum_amount")
    if maximum_amount is None:
        return flags

    if Decimal(str(expense.amount)) > Decimal(str(maximum_amount)):
        flag = f"Amount exceeds the selected policy ceiling of {maximum_amount}."
        if flag not in flags:
            flags.append(flag)
    return flags
