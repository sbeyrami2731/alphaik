"""Object storage support for Alphaik project files."""

from __future__ import annotations

import io
import os
import uuid

from supabase import Client, create_client


DEFAULT_BUCKET = "alphaik-project-files"

XLSX_CONTENT_TYPE = (
    "application/"
    "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


# ============================================================
# Configuration
# ============================================================

def _required_env(name: str) -> str:
    value = os.getenv(
        name,
        ""
    ).strip()

    if not value:
        raise RuntimeError(
            f"{name} is not configured"
        )

    return value


def bucket_name() -> str:
    """
    Return the configured private project-files bucket.

    A default is provided for the current Alphaik development
    environment, while still allowing another bucket to be
    configured on future deployments.
    """

    value = os.getenv(
        "ALPHAIK_STORAGE_BUCKET",
        DEFAULT_BUCKET
    ).strip()

    if not value:
        raise RuntimeError(
            "ALPHAIK_STORAGE_BUCKET is not configured"
        )

    return value


def get_client() -> Client:
    """
    Create a server-side Supabase client.

    Credentials must only come from environment variables.
    """

    url = _required_env(
        "SUPABASE_URL"
    )

    secret_key = _required_env(
        "SUPABASE_SECRET_KEY"
    )

    return create_client(
        url,
        secret_key
    )


# ============================================================
# Object-key helpers
# ============================================================

def _safe_filename(
    filename: str
) -> str:
    """
    Remove any directory components from a supplied filename.
    """

    normalized = (
        filename
        .replace("\\", "/")
    )

    name = normalized.split("/")[-1]

    if not name:
        raise ValueError(
            "Invalid filename"
        )

    return name


def build_object_key(
    project_id: int,
    version_no: int,
    filename: str
) -> str:
    """
    Build a unique object key.

    The database stores this key, not a public URL.
    """

    safe_name = _safe_filename(
        filename
    )

    unique_part = (
        uuid.uuid4().hex
    )

    return (
        f"projects/{project_id}/"
        f"uploads/"
        f"U{version_no:03d}_"
        f"{unique_part}_"
        f"{safe_name}"
    )


# ============================================================
# Upload
# ============================================================

def upload_project_file(
    project_id: int,
    version_no: int,
    filename: str,
    content: bytes
) -> str:
    """
    Upload one project file to the private bucket.

    Returns the object key that must be stored in PostgreSQL.
    Existing objects are never overwritten.
    """

    if not content:
        raise ValueError(
            "Cannot upload an empty file"
        )

    object_key = build_object_key(
        project_id,
        version_no,
        filename
    )

    client = get_client()

    file_body = io.BytesIO(
        content
    )

    client.storage.from_(
        bucket_name()
    ).upload(
        path=object_key,
        file=file_body,
        file_options={
            "cache-control": "3600",
            "upsert": "false",
            "content-type": XLSX_CONTENT_TYPE,
        },
    )

    return object_key


# ============================================================
# Download
# ============================================================

def download_file(
    object_key: str
) -> bytes:
    """
    Download an object from the private bucket.
    """

    if not object_key:
        raise ValueError(
            "Object key is required"
        )

    client = get_client()

    content = client.storage.from_(
        bucket_name()
    ).download(
        object_key
    )

    return bytes(
        content
    )


# ============================================================
# Delete
# ============================================================

def delete_file(
    object_key: str
) -> None:
    """
    Remove one object from the private bucket.
    """

    if not object_key:
        return

    client = get_client()

    client.storage.from_(
        bucket_name()
    ).remove(
        [
            object_key
        ]
    )


# ============================================================
# Signed download URL
# ============================================================

def create_download_url(
    object_key: str,
    expires_in: int = 300
) -> str:
    """
    Create a temporary signed URL for a private object.
    """

    if not object_key:
        raise ValueError(
            "Object key is required"
        )

    if expires_in <= 0:
        raise ValueError(
            "expires_in must be greater than zero"
        )

    client = get_client()

    response = client.storage.from_(
        bucket_name()
    ).create_signed_url(
        object_key,
        expires_in
    )

    signed_url = (
        response.get("signedURL")
        or response.get("signedUrl")
    )

    if not signed_url:
        raise RuntimeError(
            "Supabase did not return a signed URL"
        )

    return signed_url
