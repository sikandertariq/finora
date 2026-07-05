from rest_framework import serializers

from apps.expenses.serializers import ReceiptSerializer

from .models import AgentWorkflow


class AgentWorkflowSerializer(serializers.ModelSerializer):
    receipt = ReceiptSerializer(read_only=True)

    class Meta:
        model = AgentWorkflow
        fields = [
            "id",
            "workflow_type",
            "status",
            "receipt",
            "extracted_data",
            "error_message",
            "resulting_expense",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ConfirmWorkflowSerializer(serializers.Serializer):
    """Lets a human correct the AI's extraction before it becomes an Expense.

    Every field is optional — omit a field to accept what the agent extracted for it.
    """

    vendor = serializers.CharField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    currency = serializers.CharField(required=False, max_length=3)
    category = serializers.CharField(required=False, allow_blank=True)
    expense_date = serializers.DateField(required=False)
