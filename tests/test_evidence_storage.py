import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException, status

from api.services import evidence_storage


class FakeS3Client:
    def __init__(self, head_response: dict | None = None):
        self.head_response = head_response or {}
        self.presign_calls: list[dict] = []
        self.head_calls: list[dict] = []

    def generate_presigned_url(self, operation: str, **kwargs):
        self.presign_calls.append({"operation": operation, **kwargs})
        return f"https://private-storage.example/{operation}"

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        return self.head_response


@pytest.fixture(autouse=True)
def evidence_storage_env(monkeypatch):
    cached_client_factory = evidence_storage.get_evidence_s3_client
    monkeypatch.setenv("EVIDENCE_S3_ENDPOINT", "https://account.eu.r2.cloudflarestorage.com")
    monkeypatch.setenv("EVIDENCE_S3_BUCKET", "case-evidence")
    monkeypatch.setenv("EVIDENCE_S3_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("EVIDENCE_S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("EVIDENCE_MAX_FILE_BYTES", "1024")
    monkeypatch.setenv("EVIDENCE_UPLOAD_TTL_SECONDS", "900")
    monkeypatch.setenv("EVIDENCE_DOWNLOAD_TTL_SECONDS", "300")
    evidence_storage.get_evidence_storage_settings.cache_clear()
    evidence_storage.get_evidence_s3_client.cache_clear()
    yield
    evidence_storage.get_evidence_storage_settings.cache_clear()
    cached_client_factory.cache_clear()


def test_upload_ticket_is_case_scoped_and_signs_required_headers(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(evidence_storage, "get_evidence_s3_client", lambda: client)

    ticket = evidence_storage.create_upload_ticket(
        server_id=123,
        case_id=UUID("018f5f6e-7a11-7d3a-bc01-0123456789ab"),
        filename="proof.png",
        content_type="image/png",
        size_bytes=512,
    )

    assert ticket["key"].startswith("evidence/123/018f5f6e-7a11-7d3a-bc01-0123456789ab/")
    assert ticket["headers"]["Content-Type"] == "image/png"
    assert ticket["headers"]["x-amz-meta-declared-size"] == "512"
    assert ticket["expires_in_seconds"] == 900
    signed = client.presign_calls[0]
    assert signed["operation"] == "put_object"
    assert signed["Params"]["Bucket"] == "case-evidence"
    assert signed["Params"]["Metadata"]["server-id"] == "123"


@pytest.mark.parametrize(
    ("filename", "content_type", "size_bytes", "expected_status"),
    [
        ("payload.svg", "image/svg+xml", 10, status.HTTP_422_UNPROCESSABLE_CONTENT),
        ("payload.exe", "application/octet-stream", 10, status.HTTP_422_UNPROCESSABLE_CONTENT),
        ("proof.png", "image/png", 1025, status.HTTP_413_CONTENT_TOO_LARGE),
    ],
)
def test_upload_ticket_rejects_unsafe_type_and_oversized_files(
    filename,
    content_type,
    size_bytes,
    expected_status,
):
    with pytest.raises(HTTPException) as exc_info:
        evidence_storage.create_upload_ticket(
            server_id=123,
            case_id=UUID("018f5f6e-7a11-7d3a-bc01-0123456789ab"),
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
        )
    assert exc_info.value.status_code == expected_status


def test_uploaded_object_is_verified_against_ticket_scope_and_size(monkeypatch):
    filename = "доказательство.png"
    client = FakeS3Client(
        {
            "ContentLength": 512,
            "ContentType": "image/png",
            "Metadata": {
                "server-id": "123",
                "case-id": "018f5f6e-7a11-7d3a-bc01-0123456789ab",
                "original-filename-b64": evidence_storage._encode_filename(filename),
                "declared-size": "512",
            },
        }
    )
    monkeypatch.setattr(evidence_storage, "get_evidence_s3_client", lambda: client)
    case_id = UUID("018f5f6e-7a11-7d3a-bc01-0123456789ab")
    key = f"evidence/123/{case_id}/abc.png"

    metadata = asyncio.run(
        evidence_storage.validate_uploaded_evidence(server_id=123, case_id=case_id, key=key)
    )

    assert metadata.filename == filename
    assert metadata.content_type == "image/png"
    assert metadata.size_bytes == 512
    assert client.head_calls == [{"Bucket": "case-evidence", "Key": key}]


def test_uploaded_object_with_wrong_case_metadata_is_rejected(monkeypatch):
    client = FakeS3Client(
        {
            "ContentLength": 512,
            "ContentType": "image/png",
            "Metadata": {
                "server-id": "123",
                "case-id": "wrong-case",
                "original-filename-b64": evidence_storage._encode_filename("proof.png"),
                "declared-size": "512",
            },
        }
    )
    monkeypatch.setattr(evidence_storage, "get_evidence_s3_client", lambda: client)
    case_id = UUID("018f5f6e-7a11-7d3a-bc01-0123456789ab")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            evidence_storage.validate_uploaded_evidence(
                server_id=123,
                case_id=case_id,
                key=f"evidence/123/{case_id}/abc.png",
            )
        )
    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_download_ticket_is_short_lived_and_private(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(evidence_storage, "get_evidence_s3_client", lambda: client)

    ticket = evidence_storage.create_download_ticket(
        key="evidence/123/case/proof.pdf",
        filename="proof.pdf",
    )

    assert ticket["expires_in_seconds"] == 300
    signed = client.presign_calls[0]
    assert signed["operation"] == "get_object"
    assert signed["ExpiresIn"] == 300
    assert signed["Params"]["ResponseContentDisposition"] == (
        "attachment; filename=\"proof.pdf\"; filename*=UTF-8''proof.pdf"
    )
