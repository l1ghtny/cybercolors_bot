from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_UPLOAD_TTL_SECONDS = 15 * 60
DEFAULT_DOWNLOAD_TTL_SECONDS = 5 * 60

ALLOWED_CONTENT_TYPES = frozenset(
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

CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "text/plain": ".txt",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


@dataclass(frozen=True)
class EvidenceStorageSettings:
    endpoint_url: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str
    upload_ttl_seconds: int
    download_ttl_seconds: int
    max_file_bytes: int


@dataclass(frozen=True)
class EvidenceObjectMetadata:
    key: str
    filename: str
    content_type: str
    size_bytes: int


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@lru_cache(maxsize=1)
def get_evidence_storage_settings() -> EvidenceStorageSettings:
    required = {
        "endpoint_url": os.getenv("EVIDENCE_S3_ENDPOINT"),
        "bucket": os.getenv("EVIDENCE_S3_BUCKET"),
        "access_key_id": os.getenv("EVIDENCE_S3_ACCESS_KEY_ID"),
        "secret_access_key": os.getenv("EVIDENCE_S3_SECRET_ACCESS_KEY"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        env_name_by_setting = {
            "endpoint_url": "EVIDENCE_S3_ENDPOINT",
            "bucket": "EVIDENCE_S3_BUCKET",
            "access_key_id": "EVIDENCE_S3_ACCESS_KEY_ID",
            "secret_access_key": "EVIDENCE_S3_SECRET_ACCESS_KEY",
        }
        env_names = ", ".join(env_name_by_setting[name] for name in missing)
        raise RuntimeError(f"Evidence object storage is not configured: {env_names}")

    return EvidenceStorageSettings(
        endpoint_url=str(required["endpoint_url"]).rstrip("/"),
        bucket=str(required["bucket"]),
        access_key_id=str(required["access_key_id"]),
        secret_access_key=str(required["secret_access_key"]),
        region=os.getenv("EVIDENCE_S3_REGION", "auto"),
        upload_ttl_seconds=_positive_int_env("EVIDENCE_UPLOAD_TTL_SECONDS", DEFAULT_UPLOAD_TTL_SECONDS),
        download_ttl_seconds=_positive_int_env("EVIDENCE_DOWNLOAD_TTL_SECONDS", DEFAULT_DOWNLOAD_TTL_SECONDS),
        max_file_bytes=_positive_int_env("EVIDENCE_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES),
    )


@lru_cache(maxsize=1)
def get_evidence_s3_client():
    settings = get_evidence_storage_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def normalize_content_type(filename: str, content_type: str | None) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized or normalized == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(filename)
        normalized = (guessed or "").lower()
    if normalized not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported evidence file type",
        )
    return normalized


def validate_file_size(size_bytes: int) -> None:
    settings = get_evidence_storage_settings()
    if size_bytes <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Evidence file is empty")
    if size_bytes > settings.max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Evidence file exceeds the {settings.max_file_bytes}-byte limit",
        )


def evidence_key_prefix(server_id: int, case_id: UUID) -> str:
    return f"evidence/{server_id}/{case_id}/"


def create_evidence_key(server_id: int, case_id: UUID, content_type: str) -> str:
    extension = CONTENT_TYPE_EXTENSIONS[content_type]
    return f"{evidence_key_prefix(server_id, case_id)}{uuid4().hex}{extension}"


def _encode_filename(filename: str) -> str:
    value = Path(filename).name.strip() or "evidence"
    encoded = value.encode("utf-8")
    if len(encoded) > 384:
        value = encoded[:384].decode("utf-8", "ignore") or "evidence"
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_filename(value: str | None) -> str:
    if not value:
        return "evidence"
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8")[:255] or "evidence"
    except (ValueError, UnicodeDecodeError):
        return "evidence"


def create_upload_ticket(
    *,
    server_id: int,
    case_id: UUID,
    filename: str,
    content_type: str | None,
    size_bytes: int,
) -> dict:
    validate_file_size(size_bytes)
    normalized_type = normalize_content_type(filename, content_type)
    key = create_evidence_key(server_id, case_id, normalized_type)
    filename_b64 = _encode_filename(filename)
    headers = {
        "Content-Type": normalized_type,
        "x-amz-meta-server-id": str(server_id),
        "x-amz-meta-case-id": str(case_id),
        "x-amz-meta-original-filename-b64": filename_b64,
        "x-amz-meta-declared-size": str(size_bytes),
    }
    settings = get_evidence_storage_settings()
    params = {
        "Bucket": settings.bucket,
        "Key": key,
        "ContentType": normalized_type,
        "Metadata": {
            "server-id": str(server_id),
            "case-id": str(case_id),
            "original-filename-b64": filename_b64,
            "declared-size": str(size_bytes),
        },
    }
    try:
        upload_url = get_evidence_s3_client().generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=settings.upload_ttl_seconds,
            HttpMethod="PUT",
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evidence storage unavailable") from exc
    return {
        "upload_url": upload_url,
        "key": key,
        "method": "PUT",
        "headers": headers,
        "expires_in_seconds": settings.upload_ttl_seconds,
    }


def _head_evidence_object(key: str) -> dict:
    settings = get_evidence_storage_settings()
    return get_evidence_s3_client().head_object(Bucket=settings.bucket, Key=key)


async def validate_uploaded_evidence(
    *,
    server_id: int,
    case_id: UUID,
    key: str,
) -> EvidenceObjectMetadata:
    if not key.startswith(evidence_key_prefix(server_id, case_id)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid evidence object key")
    try:
        head = await asyncio.to_thread(_head_evidence_object, key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        http_status = status.HTTP_404_NOT_FOUND if code in {"404", "NoSuchKey", "NotFound"} else status.HTTP_503_SERVICE_UNAVAILABLE
        detail = "Uploaded evidence object was not found" if http_status == status.HTTP_404_NOT_FOUND else "Evidence storage unavailable"
        raise HTTPException(status_code=http_status, detail=detail) from exc
    except BotoCoreError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evidence storage unavailable") from exc

    metadata = {str(k).lower(): str(v) for k, v in (head.get("Metadata") or {}).items()}
    if metadata.get("server-id") != str(server_id) or metadata.get("case-id") != str(case_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Evidence object scope does not match the case")

    size_bytes = int(head.get("ContentLength") or 0)
    validate_file_size(size_bytes)
    declared_size = metadata.get("declared-size")
    if not declared_size or not declared_size.isdigit() or int(declared_size) != size_bytes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Evidence object size does not match the upload ticket")

    content_type = normalize_content_type(key, str(head.get("ContentType") or ""))
    return EvidenceObjectMetadata(
        key=key,
        filename=_decode_filename(metadata.get("original-filename-b64")),
        content_type=content_type,
        size_bytes=size_bytes,
    )


def create_download_ticket(*, key: str, filename: str | None) -> dict:
    settings = get_evidence_storage_settings()
    safe_filename = (Path(filename or "evidence").name.strip() or "evidence")[:255]
    ascii_fallback = safe_filename.encode("ascii", "replace").decode("ascii").replace('"', "'")
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe_filename)}"
    params = {
        "Bucket": settings.bucket,
        "Key": key,
        "ResponseContentDisposition": disposition,
    }
    try:
        download_url = get_evidence_s3_client().generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=settings.download_ttl_seconds,
            HttpMethod="GET",
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evidence storage unavailable") from exc
    return {
        "download_url": download_url,
        "expires_in_seconds": settings.download_ttl_seconds,
    }
