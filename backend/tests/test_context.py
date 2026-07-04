import pytest
from apps.tenancy import context


def teardown_function():
    context.clear_current_tenant()


def test_set_and_get():
    context.set_current_tenant(7)
    assert context.get_current_tenant_id() == 7


def test_default_is_none():
    assert context.get_current_tenant_id() is None


def test_clear():
    context.set_current_tenant(7)
    context.clear_current_tenant()
    assert context.get_current_tenant_id() is None


def test_unscoped_flag():
    assert context.is_unscoped() is False
    with context.unscoped():
        assert context.is_unscoped() is True
    assert context.is_unscoped() is False
