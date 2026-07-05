import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.agents.models import AgentWorkflow
from apps.agents.tasks import run_receipt_processor

pytestmark = pytest.mark.django_db


def test_upload_receipt_creates_a_pending_workflow_and_enqueues_processing(
    authed_client, monkeypatch
):
    calls = []
    monkeypatch.setattr(run_receipt_processor, "delay", lambda **kw: calls.append(kw))
    upload = SimpleUploadedFile("receipt.jpg", b"bytes", content_type="image/jpeg")

    resp = authed_client.post("/api/receipts/", {"file": upload}, format="multipart")

    assert resp.status_code == 201, resp.data
    assert resp.data["status"] == AgentWorkflow.Status.PENDING
    assert resp.data["receipt"]["uploaded_by"] == authed_client.user.id
    assert calls == [{"tenant_id": authed_client.tenant.id, "workflow_id": resp.data["id"]}]


def test_upload_receipt_requires_authentication():
    client = APIClient()
    upload = SimpleUploadedFile("receipt.jpg", b"bytes", content_type="image/jpeg")

    resp = client.post("/api/receipts/", {"file": upload}, format="multipart")

    assert resp.status_code == 401


def test_upload_receipt_without_a_file_is_a_400(authed_client):
    resp = authed_client.post("/api/receipts/", {}, format="multipart")

    assert resp.status_code == 400
