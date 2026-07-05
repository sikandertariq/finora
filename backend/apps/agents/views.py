from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenancy.permissions import IsTenantMember

from .models import AgentWorkflow
from .serializers import AgentWorkflowSerializer, ConfirmWorkflowSerializer
from .services import AgentWorkflowService


class AgentWorkflowViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only for the workflow itself; confirm/reject are the only writes, and both
    delegate entirely to AgentWorkflowService."""

    serializer_class = AgentWorkflowSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        # See ExpenseViewSet.get_queryset for why this isn't a `queryset =` class attribute.
        return AgentWorkflow.objects.all()

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        workflow = self.get_object()
        serializer = ConfirmWorkflowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workflow = AgentWorkflowService.approve(
            workflow, reviewed_by=request.user, overrides=serializer.validated_data
        )
        return Response(AgentWorkflowSerializer(workflow).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        workflow = AgentWorkflowService.reject(self.get_object(), reviewed_by=request.user)
        return Response(AgentWorkflowSerializer(workflow).data)
