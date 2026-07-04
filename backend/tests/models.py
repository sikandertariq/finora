from django.db import models
from apps.tenancy.models import TenantScopedModel


class ScopedThing(TenantScopedModel):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"
