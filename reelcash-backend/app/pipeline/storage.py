"""Object storage helper: local / S3 / GCS, switchable via STORAGE_BACKEND.

Returns a public-ish URL for the uploaded object. The local backend writes to
``STORAGE_LOCAL_DIR`` and returns a ``file://`` URL — fine for dev. S3/GCS
need their respective SDKs + credentials.
"""
from __future__ import annotations

import os

from ..config import settings
from ..observability import get_logger

logger = get_logger("storage")


async def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    backend = settings.STORAGE_BACKEND
    if backend == "s3":
        return _upload_s3(key, data, content_type)
    if backend == "gcs":
        return _upload_gcs(key, data, content_type)
    return _upload_local(key, data)


def _upload_local(key: str, data: bytes) -> str:
    base = os.path.abspath(settings.STORAGE_LOCAL_DIR)
    path = os.path.join(base, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    logger.info("stored %d bytes locally at %s", len(data), path)
    return f"file://{path}"


def _upload_s3(key: str, data: bytes, content_type: str) -> str:  # pragma: no cover
    import boto3

    s3 = boto3.client("s3")
    s3.put_object(Bucket=settings.STORAGE_BUCKET, Key=key, Body=data, ContentType=content_type)
    return f"https://{settings.STORAGE_BUCKET}.s3.amazonaws.com/{key}"


def _upload_gcs(key: str, data: bytes, content_type: str) -> str:  # pragma: no cover
    from google.cloud import storage as gcs

    client = gcs.Client()
    bucket = client.bucket(settings.STORAGE_BUCKET)
    blob = bucket.blob(key)
    blob.upload_from_string(data, content_type=content_type)
    return f"https://storage.googleapis.com/{settings.STORAGE_BUCKET}/{key}"
