import pytest
from apps.tenancy import context
from apps.tenancy.models import Tenant
from tests.models import ScopedThing

pytestmark = pytest.mark.django_db


def teardown_function():
    context.clear_current_tenant()


def _seed():
    t1 = Tenant.objects.create(name="A", slug="a")
    t2 = Tenant.objects.create(name="B", slug="b")
    ScopedThing.all_tenants.create(tenant=t1, name="a-thing")
    ScopedThing.all_tenants.create(tenant=t2, name="b-thing")
    return t1, t2


def test_scoped_query_returns_only_current_tenant():
    t1, _ = _seed()
    context.set_current_tenant(t1.id)
    names = set(ScopedThing.objects.values_list("name", flat=True))
    assert names == {"a-thing"}


def test_scoped_query_without_context_raises():
    _seed()
    with pytest.raises(context.TenantContextRequired):
        list(ScopedThing.objects.all())


def test_all_tenants_sees_across_tenants():
    _seed()
    assert ScopedThing.all_tenants.count() == 2


def test_unscoped_block_sees_across_tenants():
    _seed()
    with context.unscoped():
        assert ScopedThing.objects.count() == 2


def test_create_autostamps_current_tenant():
    t1, _ = _seed()
    context.set_current_tenant(t1.id)
    thing = ScopedThing.objects.create(name="new")
    assert thing.tenant_id == t1.id
