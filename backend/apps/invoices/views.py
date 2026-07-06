from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.tenancy.permissions import IsTenantMember

from .models import Invoice
from .serializers import InvoiceSerializer


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        # Not a `queryset =` class attribute -- see ExpenseViewSet.get_queryset.
        return Invoice.objects.all()
