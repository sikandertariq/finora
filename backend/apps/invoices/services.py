from decimal import Decimal

from .models import Invoice

_MUTABLE_FIELDS = {
    "client_name", "client_email", "amount", "currency", "issue_date", "due_date", "status",
}


class InvoiceService:
    """Business logic for invoices. HTTP-free, mirrors ExpenseService exactly so
    InvoiceViewSet and the (future) chaser-adjacent code share one code path."""

    @staticmethod
    def create(*, client_name, client_email, amount, issue_date, due_date,
               currency="USD", status=Invoice.Status.DRAFT):
        _validate_amount(amount)
        return Invoice.objects.create(
            client_name=client_name,
            client_email=client_email,
            amount=amount,
            currency=currency,
            issue_date=issue_date,
            due_date=due_date,
            status=status,
        )

    @staticmethod
    def update(invoice, **fields):
        unknown = set(fields) - _MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Cannot update unknown field(s): {', '.join(sorted(unknown))}")
        if "amount" in fields:
            _validate_amount(fields["amount"])
        for key, value in fields.items():
            setattr(invoice, key, value)
        invoice.save()
        return invoice

    @staticmethod
    def get(invoice_id):
        return Invoice.objects.get(id=invoice_id)

    @staticmethod
    def list(**filters):
        return Invoice.objects.filter(**filters)

    @staticmethod
    def delete(invoice):
        invoice.delete()


def _validate_amount(amount):
    if Decimal(str(amount)) <= 0:
        raise ValueError("Invoice amount must be greater than zero.")
