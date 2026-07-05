from apps.tenancy import context
from apps.tenancy.tasks import echo_current_tenant


def teardown_function():
    context.clear_current_tenant()


def test_task_binds_and_clears_tenant():
    result = echo_current_tenant.apply(kwargs={"tenant_id": 99}).get()
    assert result == 99
    assert context.get_current_tenant_id() is None  # cleared after run


def test_task_can_be_dispatched_via_delay_not_just_apply():
    """Regression: .apply() (used above) never goes through apply_async, so it never
    exercises Celery's own pre-flight argument check -- which validates kwargs against
    the *undecorated* run()'s signature, before TenantBoundTask.__call__ ever gets a
    chance to strip tenant_id out. echo_current_tenant.run() takes no arguments, so
    without `typing = False` on TenantBoundTask, this raises TypeError before the task
    is even sent -- exactly what broke the real receipt-upload endpoint in manual
    testing. .delay() is the call production code actually uses.
    """
    echo_current_tenant.app.conf.task_always_eager = True
    try:
        result = echo_current_tenant.delay(tenant_id=99)
        assert result.get() == 99
    finally:
        echo_current_tenant.app.conf.task_always_eager = False
        context.clear_current_tenant()
