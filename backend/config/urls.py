from django.contrib import admin
from django.urls import path, include

from .views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/", include("apps.tenancy.urls")),
    path("api/", include("apps.expenses.urls")),
    path("api/", include("apps.invoices.urls")),
    path("api/", include("apps.agents.urls")),
]
