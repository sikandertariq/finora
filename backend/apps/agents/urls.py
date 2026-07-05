from rest_framework.routers import SimpleRouter

from .views import AgentWorkflowViewSet

router = SimpleRouter()
router.register("agent-workflows", AgentWorkflowViewSet, basename="agent-workflow")

urlpatterns = router.urls
