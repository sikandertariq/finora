from django.db import models

from apps.tenancy.models import TenantScopedModel


class Invoice(TenantScopedModel):
    """A bill sent to a client, tracked so the Invoice Chaser agent knows what's overdue.

    No line items here (that's Expense's concern) -- this is one client, one amount,
    one due date. ``OVERDUE`` is a recognized status but nothing in this slice sets
    it automatically: the chaser computes overdue-ness from ``due_date`` directly at
    scan time, not from this field. It's here for a future status-sync job, not dead
    code.
    """

    class Status(models.TextChoices):
        DRAFT = "draft"
        SENT = "sent"
        PAID = "paid"
        OVERDUE = "overdue"
        VOID = "void"

    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    issue_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-due_date"]

    def __str__(self):
        return f"{self.client_name} — {self.amount} {self.currency} (due {self.due_date})"
