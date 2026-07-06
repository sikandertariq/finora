from django.conf import settings

from apps.tenancy import context
from apps.tenancy.models import Tenant
from apps.tenancy.tasks import TenantBoundTask
from config.celery import app

from .models import AgentWorkflow
from .providers.gemini import GeminiProvider
from .services import InvoiceChaserScheduler, InvoiceChaserService, ReceiptProcessorService


@app.task(base=TenantBoundTask, bind=False)
def run_receipt_processor(workflow_id):
    """Thin Celery entrypoint: fetch the row, delegate everything else to the service.

    TenantBoundTask (see apps.tenancy.tasks) has already set the tenant context from the
    tenant_id kwarg by the time this body runs, so the tenant-scoped lookup below is safe.
    """
    workflow = AgentWorkflow.objects.get(id=workflow_id)
    provider = GeminiProvider.from_settings(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
    ReceiptProcessorService(provider).run(workflow)


@app.task(base=TenantBoundTask, bind=False)
def run_invoice_chaser(workflow_id):
    """Thin Celery entrypoint, same shape as run_receipt_processor."""
    workflow = AgentWorkflow.objects.get(id=workflow_id)
    provider = GeminiProvider.from_settings(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
    InvoiceChaserService(provider).run(workflow)


@app.task(bind=False)
def scan_overdue_invoices():
    """Celery-beat-scheduled (daily). Not a TenantBoundTask: nothing dispatches this
    with a single tenant_id kwarg -- it owns iterating every tenant itself, setting
    and clearing context around each one so InvoiceChaserScheduler's tenant-scoped
    queries are safe."""
    for tenant in Tenant.objects.all():
        context.set_current_tenant(tenant.id)
        try:
            InvoiceChaserScheduler.scan_and_dispatch()
        finally:
            context.clear_current_tenant()
