from rest_framework import serializers

from apps.expenses.serializers import ReceiptSerializer

from .models import AgentWorkflow, AuditLog


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
    """Lets a human correct the AI's output before it's acted on.

    Every field is optional -- omit a field to accept what the agent produced for it.
    vendor/amount/currency/category/expense_date apply to receipt_processor workflows;
    subject/body apply to invoice_chaser ones. A given workflow only ever uses one set.
    """

    vendor = serializers.CharField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    currency = serializers.CharField(required=False, max_length=3)
    category = serializers.CharField(required=False, allow_blank=True)
    expense_date = serializers.DateField(required=False)
    subject = serializers.CharField(required=False)
    body = serializers.CharField(required=False)


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ["id", "workflow", "actor", "action", "metadata", "created_at"]
        read_only_fields = fields
