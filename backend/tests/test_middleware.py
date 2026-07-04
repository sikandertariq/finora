from django.test import RequestFactory
from rest_framework_simplejwt.tokens import AccessToken

from apps.tenancy import context
from apps.tenancy.middleware import TenantMiddleware


def teardown_function():
    context.clear_current_tenant()


def _request_with_tenant(tenant_id):
    token = AccessToken()
    token["tenant_id"] = tenant_id
    return RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_middleware_sets_and_clears_context_from_jwt():
    seen = {}

    def get_response(request):
        seen["during"] = context.get_current_tenant_id()
        return "ok"

    mw = TenantMiddleware(get_response)
    result = mw(_request_with_tenant(42))

    assert result == "ok"
    assert seen["during"] == 42
    assert context.get_current_tenant_id() is None  # cleared after


def test_middleware_no_token_leaves_context_empty():
    mw = TenantMiddleware(lambda request: "ok")
    mw(RequestFactory().get("/"))
    assert context.get_current_tenant_id() is None


def test_middleware_invalid_token_leaves_context_empty():
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer not-a-real-token")
    mw = TenantMiddleware(lambda r: "ok")
    mw(request)
    assert context.get_current_tenant_id() is None
