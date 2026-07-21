from rest_framework import generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.agents.serializers import AgentWorkflowSerializer
from apps.agents.services import AgentWorkflowService
from apps.tenancy.permissions import IsTenantMember

from .models import Expense, Receipt
from .serializers import ExpenseSerializer, ReceiptUploadSerializer


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        # Not a `queryset =` class attribute: that's evaluated once at import time,
        # before any request has set the tenant context. get_queryset() runs per-request.
        return Expense.objects.all()


class ReceiptUploadView(generics.GenericAPIView):
    """Thin: validate the upload, create the Receipt, hand off to the agent service."""

    serializer_class = ReceiptUploadSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "receipt_upload"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receipt = Receipt.objects.create(
            file=serializer.validated_data["file"], uploaded_by=request.user
        )
        workflow = AgentWorkflowService.start_receipt_processing(receipt)
        return Response(
            AgentWorkflowSerializer(workflow).data, status=status.HTTP_201_CREATED
        )
