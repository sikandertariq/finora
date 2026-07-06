from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.tenancy.urls")),
    path("api/", include("apps.expenses.urls")),
    path("api/", include("apps.invoices.urls")),
    path("api/", include("apps.agents.urls")),
]
