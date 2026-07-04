from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from . import context


class TenantMiddleware:
    """Set the current tenant from the request's JWT ``tenant_id`` claim.

    DRF authenticates lazily *inside* the view (``APIView.initial``), which runs
    after Django middleware — so ``request.auth`` is not yet populated here. We
    therefore decode/validate the bearer token ourselves via SimpleJWT and read
    the claim. The token is validated again by DRF in the view; that duplication
    is the price of keeping tenant resolution in exactly one middleware.

    The context is cleared in ``finally`` so a reused worker never inherits a
    stale tenant.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._jwt = JWTAuthentication()

    def __call__(self, request):
        tenant_id = self._resolve_tenant_id(request)
        if tenant_id is not None:
            context.set_current_tenant(tenant_id)
        try:
            return self.get_response(request)
        finally:
            context.clear_current_tenant()

    def _resolve_tenant_id(self, request):
        header = self._jwt.get_header(request)
        if header is None:
            return None
        raw_token = self._jwt.get_raw_token(header)
        if raw_token is None:
            return None
        try:
            validated = self._jwt.get_validated_token(raw_token)
        except (InvalidToken, TokenError):
            return None
        return validated.get("tenant_id")
