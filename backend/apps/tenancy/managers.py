from django.db import models
from . import context


class TenantQuerySet(models.QuerySet):
    pass


class TenantManager(models.Manager):
    """Auto-filters every query by the current tenant.

    Isolation lives here and only here. If no tenant is in context the manager
    fails loud (``TenantContextRequired``) rather than leaking or silently
    returning nothing. Cross-tenant access is opt-in via ``unscoped()`` or the
    sibling ``all_tenants`` manager.
    """

    def get_queryset(self):
        qs = TenantQuerySet(self.model, using=self._db)
        if context.is_unscoped():
            return qs
        tenant_id = context.get_current_tenant_id()
        if tenant_id is None:
            raise context.TenantContextRequired(
                f"{self.model.__name__} accessed with no tenant in context. "
                f"Set a tenant or use `unscoped()` / `all_tenants`."
            )
        return qs.filter(tenant_id=tenant_id)

    def create(self, **kwargs):
        if "tenant" not in kwargs and "tenant_id" not in kwargs:
            tenant_id = context.get_current_tenant_id()
            if tenant_id is None:
                raise context.TenantContextRequired(
                    f"Cannot create {self.model.__name__} without a tenant in context."
                )
            kwargs["tenant_id"] = tenant_id
        return super().create(**kwargs)


class AllTenantsManager(models.Manager):
    """Explicit cross-tenant access. Never filters."""
