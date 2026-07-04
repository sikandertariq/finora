from rest_framework.permissions import BasePermission

from . import context


class IsTenantMember(BasePermission):
    """Allow only requests that resolved a tenant (set by TenantMiddleware)."""

    message = "No tenant context on this request."

    def has_permission(self, request, view):
        return context.get_current_tenant_id() is not None
