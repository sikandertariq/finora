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


class TenantMembership(models.Model):
    """Links a Django user to the tenant whose data their token may access.

    Minimal for this slice: one user belongs to one tenant. The membership is
    the source of truth the JWT reads its ``tenant_id`` claim from.
    """

    user = models.OneToOneField(
        "auth.User", on_delete=models.CASCADE, related_name="tenant_membership"
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="memberships"
    )

    def __str__(self):
        return f"{self.user} @ {self.tenant}"
