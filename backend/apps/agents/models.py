from django.db import models

from apps.expenses.models import Expense, Receipt
from apps.tenancy.models import TenantScopedModel


class AgentWorkflow(TenantScopedModel):
    """One run of an agent against one piece of input, reviewable and reversible.

    ``workflow_type`` identifies which agent produced this row — only "receipt_processor"
    exists so far; the other three agents will add their own values later rather than a
    speculative enum defined up front.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        NEEDS_REVIEW = "needs_review"
        APPROVED = "approved"
        REJECTED = "rejected"

    workflow_type = models.CharField(max_length=50, default="receipt_processor")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="agent_workflows")
    extracted_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    resulting_expense = models.OneToOneField(
        Expense, on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_workflow"
    )
    reviewed_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.workflow_type} #{self.pk} ({self.status})"

    def mark_running(self):
        self.status = self.Status.RUNNING
        self.save(update_fields=["status", "updated_at"])

    def mark_needs_review(self, *, extracted_data=None, error_message=""):
        self.extracted_data = extracted_data or {}
        self.error_message = error_message
        self.status = self.Status.NEEDS_REVIEW
        self.save(update_fields=["extracted_data", "error_message", "status", "updated_at"])

    def mark_approved(self, *, reviewed_by, resulting_expense):
        self.reviewed_by = reviewed_by
        self.resulting_expense = resulting_expense
        self.status = self.Status.APPROVED
        self.save(
            update_fields=["reviewed_by", "resulting_expense", "status", "updated_at"]
        )

    def mark_rejected(self, *, reviewed_by):
        self.reviewed_by = reviewed_by
        self.status = self.Status.REJECTED
        self.save(update_fields=["reviewed_by", "status", "updated_at"])
