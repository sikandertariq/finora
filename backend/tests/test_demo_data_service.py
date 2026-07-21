from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from apps.expenses.models import Expense
from apps.invoices.models import Invoice
from apps.invoices.services import InvoiceService
from apps.tenancy import context
from apps.tenancy.demo import DemoDataService
from apps.tenancy.models import Tenant, TenantMembership


pytestmark = pytest.mark.django_db


def test_demo_reset_seeds_a_public_demo_without_touching_another_tenant():
    other_tenant = Tenant.objects.create(name="Other Company", slug="other-company")
    context.set_current_tenant(other_tenant.id)
    try:
        InvoiceService.create(
            client_name="Unrelated client",
            client_email="client@example.com",
            amount="125.00",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=14),
        )
    finally:
        context.clear_current_tenant()

    demo_tenant = DemoDataService.reset(password="public-demo-password")

    demo_user = User.objects.get(username="demo")
    assert demo_user.check_password("public-demo-password")
    assert TenantMembership.objects.get(user=demo_user).tenant == demo_tenant

    context.set_current_tenant(demo_tenant.id)
    try:
        assert Expense.objects.count() == 1
        assert Invoice.objects.count() == 2
        assert Invoice.objects.filter(status=Invoice.Status.OVERDUE).count() == 1
    finally:
        context.clear_current_tenant()

    context.set_current_tenant(other_tenant.id)
    try:
        assert Invoice.objects.count() == 1
    finally:
        context.clear_current_tenant()


def test_demo_reset_replaces_previous_demo_data():
    first_demo = DemoDataService.reset(password="first-password")
    context.set_current_tenant(first_demo.id)
    try:
        InvoiceService.create(
            client_name="Temporary visitor data",
            client_email="visitor@example.com",
            amount="10.00",
            issue_date=date.today(),
            due_date=date.today(),
        )
        assert Invoice.objects.count() == 3
    finally:
        context.clear_current_tenant()

    second_demo = DemoDataService.reset(password="second-password")

    assert second_demo.slug == "finora-demo"
    assert not Tenant.objects.filter(id=first_demo.id).exists()
    context.set_current_tenant(second_demo.id)
    try:
        assert Invoice.objects.count() == 2
    finally:
        context.clear_current_tenant()


def test_reset_demo_management_command_uses_configured_public_password(settings):
    settings.DEMO_USER_PASSWORD = "configured-demo-password"

    call_command("reset_demo_data")

    demo_user = User.objects.get(username="demo")
    assert demo_user.check_password("configured-demo-password")
