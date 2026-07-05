from django.conf import settings

from apps.tenancy.tasks import TenantBoundTask
from config.celery import app

from .models import AgentWorkflow
from .providers.gemini import GeminiProvider
from .services import ReceiptProcessorService


@app.task(base=TenantBoundTask, bind=False)
def run_receipt_processor(workflow_id):
    """Thin Celery entrypoint: fetch the row, delegate everything else to the service.

    TenantBoundTask (see apps.tenancy.tasks) has already set the tenant context from the
    tenant_id kwarg by the time this body runs, so the tenant-scoped lookup below is safe.
    """
    workflow = AgentWorkflow.objects.get(id=workflow_id)
    provider = GeminiProvider.from_settings(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
    ReceiptProcessorService(provider).run(workflow)
