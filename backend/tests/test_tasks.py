from apps.tenancy import context
from apps.tenancy.tasks import echo_current_tenant


def teardown_function():
    context.clear_current_tenant()


def test_task_binds_and_clears_tenant():
    result = echo_current_tenant.apply(kwargs={"tenant_id": 99}).get()
    assert result == 99
    assert context.get_current_tenant_id() is None  # cleared after run
