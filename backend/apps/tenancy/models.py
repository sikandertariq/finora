from django.db import models
from .managers import TenantManager, AllTenantsManager


class Tenant(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class TenantScopedModel(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)

    objects = TenantManager()
    all_tenants = AllTenantsManager()

    class Meta:
        abstract = True
