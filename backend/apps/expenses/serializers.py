from rest_framework import serializers

from .models import Expense, Receipt
from .services import ExpenseService


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = ["id", "file", "uploaded_by", "uploaded_at"]
        read_only_fields = fields


class ReceiptUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = [
            "id",
            "vendor",
            "amount",
            "currency",
            "category",
            "description",
            "expense_date",
            "receipt",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return self._via_service(ExpenseService.create, **validated_data)

    def update(self, instance, validated_data):
        return self._via_service(ExpenseService.update, instance, **validated_data)

    @staticmethod
    def _via_service(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
