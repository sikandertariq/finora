from rest_framework import generics, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.agents.serializers import AgentWorkflowSerializer
from apps.agents.services import AgentWorkflowService, ExpenseApprovalService
from apps.tenancy.permissions import IsTenantMember

from .models import Expense, ExpenseApprovalPolicy, Receipt
from .serializers import (
    ExpenseApprovalPolicySerializer,
    ExpenseSerializer,
    ReceiptUploadSerializer,
)


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        # Not a `queryset =` class attribute: that's evaluated once at import time,
        # before any request has set the tenant context. get_queryset() runs per-request.
        return Expense.objects.all()

    @action(detail=True, methods=["post"], url_path="request-approval")
    def request_approval(self, request, pk=None):
        try:
            workflow = ExpenseApprovalService.start(self.get_object())
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(AgentWorkflowSerializer(workflow).data, status=status.HTTP_201_CREATED)


class ExpenseApprovalPolicyViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseApprovalPolicySerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        return ExpenseApprovalPolicy.objects.all()


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
