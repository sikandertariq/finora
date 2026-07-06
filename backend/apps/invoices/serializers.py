from rest_framework import serializers

from .models import Invoice
from .services import InvoiceService


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            "id",
            "client_name",
            "client_email",
            "amount",
            "currency",
            "issue_date",
            "due_date",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        return self._via_service(InvoiceService.create, **validated_data)

    def update(self, instance, validated_data):
        return self._via_service(InvoiceService.update, instance, **validated_data)

    @staticmethod
    def _via_service(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
