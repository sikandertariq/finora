from rest_framework.routers import SimpleRouter

from .views import AgentWorkflowViewSet, AuditLogViewSet

router = SimpleRouter()
router.register("agent-workflows", AgentWorkflowViewSet, basename="agent-workflow")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")

urlpatterns = router.urls
