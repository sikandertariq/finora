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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-created_at"]

    def __str__(self):
        return f"{self.vendor} — {self.amount} {self.currency}"
