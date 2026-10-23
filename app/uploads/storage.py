"""
Local-disk object storage adapter for the demo. Swap this module for an
S3/GCS-backed implementation in production; every other module only
calls save_file()/read_file()/build_key() so the storage backend can
change without touching business logic.
"""
import os
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config.settings import get_settings
from app.common.exceptions import ValidationAppError

settings = get_settings()


def _ensure_root() -> Path:
    root = Path(settings.upload_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_key(category: str, entity_id: str, filename: str) -> str:
    ext = Path(filename).suffix.lower() or ".bin"
    return f"{category}/{entity_id}/{uuid.uuid4().hex}{ext}"


def save_upload(category: str, entity_id: str, file: UploadFile, max_bytes: int, allowed_types: tuple[str, ...]) -> str:
    if file.content_type not in allowed_types:
        raise ValidationAppError(f"Unsupported file type '{file.content_type}'. Allowed: {', '.join(allowed_types)}")

    contents = file.file.read()
    if len(contents) > max_bytes:
        raise ValidationAppError(f"File too large. Maximum size is {max_bytes // (1024*1024)} MB")

    key = build_key(category, entity_id, file.filename or "upload")
    root = _ensure_root()
    dest = root / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(contents)
    return key


def read_file(key: str) -> bytes:
    root = _ensure_root()
    path = root / key
    if not path.exists() or not path.is_relative_to(root):
        raise ValidationAppError("File not found")
    return path.read_bytes()
