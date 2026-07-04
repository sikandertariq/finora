from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import TenantTokenObtainPairView, whoami

urlpatterns = [
    path("token/", TenantTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("whoami/", whoami, name="whoami"),
]
