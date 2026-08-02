from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status


MAX_ATTACHMENT_FILES = 10
MAX_ATTACHMENT_FILE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 25 * 1024 * 1024
ALLOWED_ATTACHMENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
        "video/mp4",
        "video/quicktime",
        "video/webm",
    }
)


@dataclass(frozen=True)
class ScheduledStorageSettings:
    endpoint_url: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str


@lru_cache(maxsize=1)
def get_scheduled_storage_settings() -> ScheduledStorageSettings:
    required = {
        "endpoint_url": os.getenv("SCHEDULED_POSTS_S3_ENDPOINT"),
        "bucket": os.getenv("SCHEDULED_POSTS_S3_BUCKET"),
        "access_key_id": os.getenv("SCHEDULED_POSTS_S3_ACCESS_KEY_ID"),
        "secret_access_key": os.getenv("SCHEDULED_POSTS_S3_SECRET_ACCESS_KEY"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        env_names = {
            "endpoint_url": "SCHEDULED_POSTS_S3_ENDPOINT",
            "bucket": "SCHEDULED_POSTS_S3_BUCKET",
            "access_key_id": "SCHEDULED_POSTS_S3_ACCESS_KEY_ID",
            "secret_access_key": "SCHEDULED_POSTS_S3_SECRET_ACCESS_KEY",
        }
        raise RuntimeError(
            "Scheduled-post object storage is not configured: "
            + ", ".join(env_names[name] for name in missing)
        )
    return ScheduledStorageSettings(
        endpoint_url=str(required["endpoint_url"]).rstrip("/"),
        bucket=str(required["bucket"]),
        access_key_id=str(required["access_key_id"]),
        secret_access_key=str(required["secret_access_key"]),
        region=os.getenv("SCHEDULED_POSTS_S3_REGION", "auto"),
    )


@lru_cache(maxsize=1)
def get_scheduled_s3_client():
    settings = get_scheduled_storage_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _encode_filename(filename: str) -> str:
    safe = Path(filename).name.strip()[:255] or "attachment"
    return base64.urlsafe_b64encode(safe.encode("utf-8")).decode("ascii").rstrip("=")


def _extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix[:16] if suffix and suffix[1:].isalnum() else ""


def attachment_key(server_id: int, post_id: UUID, filename: str) -> str:
    return f"scheduled-posts/{server_id}/{post_id}/{uuid4().hex}{_extension(filename)}"


def validate_attachment_totals(*, count: int, total_bytes: int) -> None:
    if count > MAX_ATTACHMENT_FILES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Attach at most {MAX_ATTACHMENT_FILES} files",
        )
    if total_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Attachments exceed the 25 MB total limit",
        )


def _put_object(
    *, server_id: int, post_id: UUID, key: str, filename: str, data: bytes, content_type: str
) -> None:
    settings = get_scheduled_storage_settings()
    get_scheduled_s3_client().put_object(
        Bucket=settings.bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        Metadata={
            "server-id": str(server_id),
            "scheduled-post-id": str(post_id),
            "original-filename-b64": _encode_filename(filename),
            "size": str(len(data)),
        },
    )


async def upload_scheduled_attachment(
    *, server_id: int, post_id: UUID, filename: str, data: bytes, content_type: str
) -> str:
    key = attachment_key(server_id, post_id, filename)
    try:
        await asyncio.to_thread(
            _put_object,
            server_id=server_id,
            post_id=post_id,
            key=key,
            filename=filename,
            data=data,
            content_type=content_type,
        )
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduled attachment storage is unavailable",
        ) from error
    return key


def _get_object(key: str) -> bytes:
    settings = get_scheduled_storage_settings()
    response = get_scheduled_s3_client().get_object(Bucket=settings.bucket, Key=key)
    return response["Body"].read()


async def download_scheduled_attachment(key: str) -> bytes:
    try:
        return await asyncio.to_thread(_get_object, key)
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError("Scheduled attachment could not be loaded") from error


def _delete_objects(keys: list[str]) -> None:
    if not keys:
        return
    settings = get_scheduled_storage_settings()
    get_scheduled_s3_client().delete_objects(
        Bucket=settings.bucket,
        Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
    )


async def delete_scheduled_attachments(keys: list[str]) -> None:
    if not keys:
        return
    try:
        await asyncio.to_thread(_delete_objects, keys)
    except (BotoCoreError, ClientError):
        # The database remains authoritative. A later storage reconciliation can
        # remove an orphan without making schedule edits or deletion unavailable.
        return
