from django.conf import settings
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

    def validate_file(self, value):
        if value.size > settings.MAX_RECEIPT_UPLOAD_BYTES:
            raise serializers.ValidationError("Receipt files must be 5 MB or smaller.")
        if value.content_type not in settings.ALLOWED_RECEIPT_MIME_TYPES:
            raise serializers.ValidationError("Upload a JPEG, PNG, WEBP, or PDF receipt.")
        return value


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
