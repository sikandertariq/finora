from celery import Task

from config.celery import app
from . import context


class TenantBoundTask(Task):
    """Base task that binds the tenant context from a ``tenant_id`` kwarg.

    Agents run inside Celery, but must go through the *same* tenant-scoped
    services a user's request does. This base sets the tenant context for the
    duration of the task and clears it afterwards, so a worker process reused
    for the next task never inherits a stale tenant.
    """

    def __call__(self, *args, **kwargs):
        tenant_id = kwargs.pop("tenant_id", None)
        if tenant_id is not None:
            context.set_current_tenant(tenant_id)
        try:
            return self.run(*args, **kwargs)
        finally:
            context.clear_current_tenant()


@app.task(base=TenantBoundTask, bind=False)
def echo_current_tenant():
    """Demo task proving the base binds tenant context around execution."""
    return context.get_current_tenant_id()
