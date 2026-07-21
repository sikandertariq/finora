import pytest
from django.core.files.uploadedfile import SimpleUploadedFile


pytestmark = pytest.mark.django_db


def test_receipt_upload_rejects_files_larger_than_five_megabytes(authed_client):
    upload = SimpleUploadedFile(
        "too-large.jpg",
        b"x" * (5 * 1024 * 1024 + 1),
        content_type="image/jpeg",
    )

    response = authed_client.post("/api/receipts/", {"file": upload}, format="multipart")

    assert response.status_code == 400
    assert "5 MB" in str(response.data)


def test_receipt_upload_rejects_unsupported_file_types(authed_client):
    upload = SimpleUploadedFile(
        "receipt.exe", b"not-a-receipt", content_type="application/octet-stream"
    )

    response = authed_client.post("/api/receipts/", {"file": upload}, format="multipart")

    assert response.status_code == 400
    assert "JPEG, PNG, WEBP, or PDF" in str(response.data)
