"""Controlled, disposable data for the public portfolio demonstration."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from apps.agents.models import AgentWorkflow
from apps.expenses.services import ExpenseService
from apps.invoices.models import Invoice
from apps.invoices.services import InvoiceService

from . import context
from .models import Tenant, TenantMembership


class DemoDataService:
    """Rebuild only the intentionally public demo tenant.

    A complete tenant delete lets database-level cascades remove every demo-owned
    workflow, receipt, expense, invoice, membership, and audit row without ever
    touching a real tenant. The demo user is retained so its known public password
    can be rotated through configuration on every reset.
    """

    TENANT_SLUG = "finora-demo"
    USERNAME = "demo"

    @classmethod
    @transaction.atomic
    def reset(cls, *, password: str) -> Tenant:
        demo_user, _ = User.objects.get_or_create(username=cls.USERNAME)
        existing_membership = TenantMembership.objects.filter(user=demo_user).select_related(
            "tenant"
        ).first()
        if existing_membership and existing_membership.tenant.slug != cls.TENANT_SLUG:
            raise RuntimeError("The reserved demo user belongs to a non-demo tenant.")

        Tenant.objects.filter(slug=cls.TENANT_SLUG).delete()
        tenant = Tenant.objects.create(name="Finora Public Demo", slug=cls.TENANT_SLUG)
        demo_user.set_password(password)
        demo_user.save(update_fields=["password"])
        TenantMembership.objects.create(user=demo_user, tenant=tenant)

        context.set_current_tenant(tenant.id)
        try:
            cls._seed(tenant=tenant, user=demo_user)
        finally:
            context.clear_current_tenant()
        return tenant

    @staticmethod
    def _seed(*, tenant: Tenant, user: User) -> None:
        today = timezone.localdate()
        ExpenseService.create(
            vendor="Northstar Office Supply",
            amount="84.50",
            currency="USD",
            category="Office supplies",
            description="Demo expense — generated sample data.",
            expense_date=today - timedelta(days=3),
            created_by=user,
        )
        overdue = InvoiceService.create(
            client_name="Atlas Studio",
            client_email="accounts@atlas-studio.example",
            amount="1240.00",
            currency="USD",
            issue_date=today - timedelta(days=31),
            due_date=today - timedelta(days=7),
            status=Invoice.Status.OVERDUE,
        )
        InvoiceService.create(
            client_name="River & Co.",
            client_email="finance@river-co.example",
            amount="680.00",
            currency="USD",
            issue_date=today - timedelta(days=2),
            due_date=today + timedelta(days=28),
            status=Invoice.Status.SENT,
        )
        AgentWorkflow.objects.create(
            workflow_type="invoice_chaser",
            invoice=overdue,
            status=AgentWorkflow.Status.NEEDS_REVIEW,
            extracted_data={
                "escalation_level": "day_7",
                "subject": "A quick reminder about your Finora invoice",
                "body": (
                    "Hi Atlas Studio,\\n\\nThis is a friendly reminder that your "
                    "invoice for $1,240.00 is now overdue. Please let us know if "
                    "you need anything to process it.\\n\\nThank you,\\nFinora"
                ),
            },
        )
