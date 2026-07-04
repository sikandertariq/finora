from contextlib import contextmanager
from contextvars import ContextVar

_current_tenant_id: ContextVar[int | None] = ContextVar("current_tenant_id", default=None)
_unscoped: ContextVar[bool] = ContextVar("tenant_unscoped", default=False)


class TenantContextRequired(Exception):
    """Raised when a tenant-scoped query runs with no tenant in context."""


def set_current_tenant(tenant_id: int) -> None:
    _current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> int | None:
    return _current_tenant_id.get()


def clear_current_tenant() -> None:
    _current_tenant_id.set(None)


def is_unscoped() -> bool:
    return _unscoped.get()


@contextmanager
def unscoped():
    token = _unscoped.set(True)
    try:
        yield
    finally:
        _unscoped.reset(token)
