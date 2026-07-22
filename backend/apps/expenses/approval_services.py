from decimal import Decimal, InvalidOperation

from .models import ExpenseApprovalPolicy


_MUTABLE_FIELDS = {
    "name",
    "priority",
    "category",
    "minimum_amount",
    "maximum_amount",
    "approval_queue",
    "is_active",
}


class ExpenseApprovalPolicyService:
    """HTTP-free business logic for tenant-scoped expense approval policies."""

    @staticmethod
    def create(
        *,
        name,
        priority=100,
        category="",
        minimum_amount=0,
        maximum_amount=None,
        approval_queue="Finance",
        is_active=True,
    ):
        _validate_amount_range(minimum_amount, maximum_amount)
        return ExpenseApprovalPolicy.objects.create(
            name=name,
            priority=priority,
            category=category,
            minimum_amount=minimum_amount,
            maximum_amount=maximum_amount,
            approval_queue=approval_queue,
            is_active=is_active,
        )

    @staticmethod
    def update(policy, **fields):
        unknown = set(fields) - _MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Cannot update unknown field(s): {', '.join(sorted(unknown))}")

        _validate_amount_range(
            fields.get("minimum_amount", policy.minimum_amount),
            fields.get("maximum_amount", policy.maximum_amount),
        )
        for key, value in fields.items():
            setattr(policy, key, value)
        policy.save()
        return policy

    @staticmethod
    def get(policy_id):
        return ExpenseApprovalPolicy.objects.get(id=policy_id)

    @staticmethod
    def list(**filters):
        return ExpenseApprovalPolicy.objects.filter(**filters)

    @staticmethod
    def delete(policy):
        policy.delete()

    @staticmethod
    def matching_policy(expense):
        """Return the highest-priority active policy that routes ``expense``.

        A blank policy category applies to every expense category. A non-null maximum
        amount is a ceiling for the later workflow to flag, not a routing constraint.
        """
        return (
            ExpenseApprovalPolicy.objects.filter(
                is_active=True,
                minimum_amount__lte=expense.amount,
            )
            .filter(category__in=["", expense.category])
            .order_by("priority", "id")
            .first()
        )


def _validate_amount_range(minimum_amount, maximum_amount):
    try:
        minimum = Decimal(str(minimum_amount))
        maximum = None if maximum_amount is None else Decimal(str(maximum_amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Policy amounts must be valid decimal values.") from exc

    if not minimum.is_finite() or (maximum is not None and not maximum.is_finite()):
        raise ValueError("Policy amounts must be finite decimal values.")
    if minimum < 0:
        raise ValueError("Minimum amount cannot be negative.")
    if maximum is not None and maximum < minimum:
        raise ValueError("Maximum amount cannot be less than minimum amount.")
