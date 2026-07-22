from django.db import models

from apps.tenancy.models import TenantScopedModel


class Receipt(TenantScopedModel):
    """An uploaded receipt file, before or after an agent has extracted data from it."""

    file = models.FileField(upload_to="receipts/%Y/%m/")
    uploaded_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, related_name="receipts"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.file.name


class Expense(TenantScopedModel):
    class ApprovalStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Not requested"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    vendor = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    expense_date = models.DateField()
    receipt = models.OneToOneField(
        Receipt, on_delete=models.SET_NULL, null=True, blank=True, related_name="expense"
    )
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, related_name="expenses"
    )
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.NOT_REQUESTED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-created_at"]

    def __str__(self):
        return f"{self.vendor} — {self.amount} {self.currency}"


class ExpenseApprovalPolicy(TenantScopedModel):
    """A tenant-defined rule that routes expenses to a human approval queue."""

    name = models.CharField(max_length=200)
    priority = models.PositiveIntegerField(default=100)
    category = models.CharField(max_length=100, blank=True)
    minimum_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    maximum_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    approval_queue = models.CharField(max_length=100, default="Finance")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "id"]

    def __str__(self):
        return self.name
