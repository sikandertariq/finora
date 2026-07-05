import pytest

from apps.agents.models import AgentWorkflow, AuditLog
from apps.expenses.models import Receipt
from apps.tenancy import context
from tests.factories import TenantFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context():
    tenant = TenantFactory()
    context.set_current_tenant(tenant.id)
    yield tenant
    context.clear_current_tenant()


def _workflow(user):
    receipt = Receipt.objects.create(uploaded_by=user)
    return AgentWorkflow.objects.create(receipt=receipt)


def test_audit_log_records_who_did_what_to_which_workflow(tenant_context):
    user = UserFactory()
    workflow = _workflow(user)

    log = AuditLog.objects.create(
        workflow=workflow, actor=user, action="approved", metadata={"resulting_expense_id": 1}
    )

    assert log.tenant_id == tenant_context.id
    assert log.workflow_id == workflow.id
    assert log.actor_id == user.id
    assert log.action == "approved"
    assert log.metadata == {"resulting_expense_id": 1}


def test_audit_log_is_scoped_to_the_current_tenant():
    other_tenant = TenantFactory()
    user = UserFactory()
    workflow = _workflow(user)
    AuditLog.objects.create(workflow=workflow, actor=user, action="approved")

    context.set_current_tenant(other_tenant.id)
    assert AuditLog.objects.count() == 0


def test_audit_log_without_tenant_context_raises():
    user = UserFactory()
    workflow = _workflow(user)
    AuditLog.objects.create(workflow=workflow, actor=user, action="approved")

    context.clear_current_tenant()
    with pytest.raises(context.TenantContextRequired):
        list(AuditLog.objects.all())
