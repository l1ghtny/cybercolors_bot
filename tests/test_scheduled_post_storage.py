import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException, status

from api.services import scheduled_post_storage


class FakeBody:
    def read(self) -> bytes:
        return b"stored file"


class FakeS3Client:
    def __init__(self):
        self.put_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"Body": FakeBody()}

    def delete_objects(self, **kwargs):
        self.delete_calls.append(kwargs)


@pytest.fixture(autouse=True)
def storage_env(monkeypatch):
    cached_client_factory = scheduled_post_storage.get_scheduled_s3_client
    monkeypatch.setenv(
        "SCHEDULED_POSTS_S3_ENDPOINT", "https://account.r2.cloudflarestorage.com/"
    )
    monkeypatch.setenv("SCHEDULED_POSTS_S3_BUCKET", "scheduled-attachments")
    monkeypatch.setenv("SCHEDULED_POSTS_S3_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("SCHEDULED_POSTS_S3_SECRET_ACCESS_KEY", "secret")
    scheduled_post_storage.get_scheduled_storage_settings.cache_clear()
    scheduled_post_storage.get_scheduled_s3_client.cache_clear()
    yield
    scheduled_post_storage.get_scheduled_storage_settings.cache_clear()
    cached_client_factory.cache_clear()


def test_settings_use_private_r2_endpoint() -> None:
    settings = scheduled_post_storage.get_scheduled_storage_settings()
    assert settings.endpoint_url == "https://account.r2.cloudflarestorage.com"
    assert settings.bucket == "scheduled-attachments"
    assert settings.region == "auto"


def test_attachment_round_trip_uses_server_and_post_scoped_key(monkeypatch) -> None:
    client = FakeS3Client()
    monkeypatch.setattr(scheduled_post_storage, "get_scheduled_s3_client", lambda: client)
    post_id = UUID("018f5f6e-7a11-7d3a-bc01-0123456789ab")

    key = asyncio.run(
        scheduled_post_storage.upload_scheduled_attachment(
            server_id=123,
            post_id=post_id,
            filename="объявление.pdf",
            data=b"stored file",
            content_type="application/pdf",
        )
    )

    assert key.startswith(f"scheduled-posts/123/{post_id}/")
    assert key.endswith(".pdf")
    assert client.put_calls[0]["Bucket"] == "scheduled-attachments"
    assert client.put_calls[0]["Metadata"]["scheduled-post-id"] == str(post_id)
    assert asyncio.run(scheduled_post_storage.download_scheduled_attachment(key)) == b"stored file"
    asyncio.run(scheduled_post_storage.delete_scheduled_attachments([key]))
    assert client.get_calls == [{"Bucket": "scheduled-attachments", "Key": key}]
    assert client.delete_calls[0]["Delete"]["Objects"] == [{"Key": key}]


def test_attachment_limits_reject_too_many_or_too_large() -> None:
    with pytest.raises(HTTPException) as too_many:
        scheduled_post_storage.validate_attachment_totals(count=11, total_bytes=1)
    assert too_many.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    with pytest.raises(HTTPException) as too_large:
        scheduled_post_storage.validate_attachment_totals(
            count=1,
            total_bytes=scheduled_post_storage.MAX_ATTACHMENT_TOTAL_BYTES + 1,
        )
    assert too_large.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
