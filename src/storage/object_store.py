"""Uploads the resulting CSV to S3, GCS, or skips upload (local mode)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from ..config import StorageConfig

log = logging.getLogger(__name__)


def _timestamped_key(prefix: str, filename: str) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y/%m/%d/%H%M%S")
    base, ext = os.path.splitext(filename)
    return f"{prefix.rstrip('/')}/{ts}-{base}{ext}"


def upload(local_path: str, cfg: StorageConfig) -> str | None:
    """
    Uploads `local_path` to the configured backend.
    Returns the remote URI (or None if backend == 'local').
    """
    if cfg.backend == "local":
        log.info("Storage backend = local; skipping upload (file kept at %s)", local_path)
        return None

    if not cfg.bucket:
        raise RuntimeError("STORAGE_BUCKET must be set for non-local backends")

    if cfg.backend == "s3":
        return _upload_s3(local_path, cfg)
    if cfg.backend == "gcs":
        return _upload_gcs(local_path, cfg)
    raise ValueError(f"Unsupported storage backend: {cfg.backend}")


def _upload_s3(local_path: str, cfg: StorageConfig) -> str:
    import boto3  # imported lazily so local runs don't need it

    key_versioned = _timestamped_key(cfg.prefix, cfg.output_filename)
    key_latest = f"{cfg.prefix.rstrip('/')}/latest/{cfg.output_filename}"

    s3 = boto3.client("s3", region_name=cfg.aws_region)
    s3.upload_file(local_path, cfg.bucket, key_versioned)
    s3.upload_file(local_path, cfg.bucket, key_latest)

    uri = f"s3://{cfg.bucket}/{key_versioned}"
    log.info("Uploaded to %s (and overwrote latest)", uri)
    return uri


def _upload_gcs(local_path: str, cfg: StorageConfig) -> str:
    from google.cloud import storage  # type: ignore

    client = storage.Client()
    bucket = client.bucket(cfg.bucket)

    key_versioned = _timestamped_key(cfg.prefix, cfg.output_filename)
    key_latest = f"{cfg.prefix.rstrip('/')}/latest/{cfg.output_filename}"

    bucket.blob(key_versioned).upload_from_filename(local_path)
    bucket.blob(key_latest).upload_from_filename(local_path)

    uri = f"gs://{cfg.bucket}/{key_versioned}"
    log.info("Uploaded to %s (and overwrote latest)", uri)
    return uri
