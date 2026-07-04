from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from . import context
from .permissions import IsTenantMember
from .serializers import TenantAwareTokenObtainPairSerializer


class TenantTokenObtainPairView(TokenObtainPairView):
    serializer_class = TenantAwareTokenObtainPairSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsTenantMember])
def whoami(request):
    return Response({
        "user": request.user.username,
        "tenant_id": context.get_current_tenant_id(),
    })
