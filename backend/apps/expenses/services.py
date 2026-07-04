from decimal import Decimal

from .models import Expense

_MUTABLE_FIELDS = {"vendor", "amount", "currency", "category", "description", "expense_date", "receipt"}


class ExpenseService:
    """Business logic for expenses. HTTP-free so a viewset and a Celery task call the
    same code path — this is the reuse the agent layer depends on."""

    @staticmethod
    def create(*, vendor, amount, expense_date, created_by, category="", description="",
                currency="USD", receipt=None):
        _validate_amount(amount)
        return Expense.objects.create(
            vendor=vendor,
            amount=amount,
            currency=currency,
            category=category,
            description=description,
            expense_date=expense_date,
            created_by=created_by,
            receipt=receipt,
        )

    @staticmethod
    def update(expense, **fields):
        unknown = set(fields) - _MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Cannot update unknown field(s): {', '.join(sorted(unknown))}")
        if "amount" in fields:
            _validate_amount(fields["amount"])
        for key, value in fields.items():
            setattr(expense, key, value)
        expense.save()
        return expense

    @staticmethod
    def get(expense_id):
        return Expense.objects.get(id=expense_id)

    @staticmethod
    def list(**filters):
        return Expense.objects.filter(**filters)

    @staticmethod
    def delete(expense):
        expense.delete()


def _validate_amount(amount):
    if Decimal(str(amount)) <= 0:
        raise ValueError("Expense amount must be greater than zero.")
