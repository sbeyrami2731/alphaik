"""PostgreSQL application storage backend for Alphaik."""

from __future__ import annotations

import hashlib
import json
import os
import secrets

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import postgres_schema
from . import postgres_storage


# ============================================================
# Storage configuration
# ============================================================

BASE = Path(__file__).resolve().parent.parent

DATA_DIR = BASE / "runtime"
UPLOAD_DIR = DATA_DIR / "uploads"

SESSION_TTL_HOURS = 8

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# Date and time
# ============================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# Password security
# ============================================================

def _hash_password(
    password: str,
    salt: str | None = None
) -> str:

    salt = salt or secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        bytes.fromhex(salt),
        200_000
    ).hex()

    return f"{salt}${digest}"


def _verify(
    password: str,
    stored: str
) -> bool:

    try:
        salt, digest = stored.split(
            "$",
            1
        )

        calculated = _hash_password(
            password,
            salt
        ).split(
            "$",
            1
        )[1]

        return secrets.compare_digest(
            calculated,
            digest
        )

    except (ValueError, TypeError):
        return False


# ============================================================
# Database initialization
# ============================================================

def init_db() -> None:

    username = os.getenv(
        "ALPHAIK_ADMIN_USER",
        ""
    ).strip()

    password = os.getenv(
        "ALPHAIK_ADMIN_PASSWORD",
        ""
    )

    if not username or not password.strip():
        raise RuntimeError(
            "Administrator credentials must be configured"
        )

    postgres_schema.ensure_schema()

    with postgres_storage.get_connection() as connection:

        try:
            with connection.cursor() as cursor:

                # --------------------------------------------
                # Remove expired sessions
                # --------------------------------------------

                cursor.execute(
                    """
                    DELETE FROM sessions
                    WHERE expires_at <= %s
                    """,
                    (_now(),)
                )

                # --------------------------------------------
                # Bootstrap administrator
                # --------------------------------------------

                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    LIMIT 1
                    """
                )

                existing_user = cursor.fetchone()

                if not existing_user:

                    cursor.execute(
                        """
                        INSERT INTO users (
                            username,
                            password_hash,
                            created_at
                        )
                        VALUES (
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            username,
                            _hash_password(password),
                            _now(),
                        )
                    )

            connection.commit()

        except Exception:

            connection.rollback()
            raise


# ============================================================
# Authentication and session management
# ============================================================

def login(
    username: str,
    password: str
) -> str | None:

    with postgres_storage.get_connection() as connection:

        try:
            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        id,
                        username,
                        password_hash
                    FROM users
                    WHERE username = %s
                    """,
                    (username,)
                )

                row = cursor.fetchone()

                if (
                    not row
                    or not _verify(
                        password,
                        row["password_hash"]
                    )
                ):
                    return None

                token = secrets.token_urlsafe(32)

                now = _now()

                expires_at = (
                    now
                    + timedelta(
                        hours=SESSION_TTL_HOURS
                    )
                )

                cursor.execute(
                    """
                    INSERT INTO sessions (
                        token,
                        user_id,
                        created_at,
                        expires_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        token,
                        row["id"],
                        now,
                        expires_at,
                    )
                )

            connection.commit()

            return token

        except Exception:

            connection.rollback()
            raise


def user_for_token(
    token: str | None
):

    if not token:
        return None

    with postgres_storage.get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    u.id,
                    u.username
                FROM sessions s
                JOIN users u
                    ON u.id = s.user_id
                WHERE s.token = %s
                  AND s.expires_at > %s
                """,
                (
                    token,
                    _now(),
                )
            )

            row = cursor.fetchone()

            return (
                dict(row)
                if row
                else None
            )


def logout(
    token: str | None
) -> bool:

    if not token:
        return False

    with postgres_storage.get_connection() as connection:

        try:
            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    DELETE FROM sessions
                    WHERE token = %s
                    """,
                    (token,)
                )

                deleted = (
                    cursor.rowcount > 0
                )

            connection.commit()

            return deleted

        except Exception:

            connection.rollback()
            raise


# ============================================================
# Project management
# ============================================================

def create_project(
    name: str,
    code: str | None = None,
    client: str | None = None
) -> dict[str, Any]:

    with postgres_storage.get_connection() as connection:

        try:
            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    INSERT INTO projects (
                        name,
                        code,
                        client,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        name,
                        code,
                        client,
                        _now(),
                    )
                )

                row = cursor.fetchone()

                if not row:
                    raise RuntimeError(
                        "Project creation failed"
                    )

                project_id = int(
                    row["id"]
                )

            connection.commit()

        except Exception:

            connection.rollback()
            raise

    project = get_project(
        project_id
    )

    if not project:
        raise RuntimeError(
            "Created project could not be read"
        )

    return project


def list_projects():

    with postgres_storage.get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    p.id,
                    p.name,
                    p.code,
                    p.client,
                    p.created_at,
                    COUNT(u.id) AS upload_count,
                    MAX(u.uploaded_at) AS last_upload
                FROM projects p
                LEFT JOIN uploads u
                    ON u.project_id = p.id
                GROUP BY
                    p.id,
                    p.name,
                    p.code,
                    p.client,
                    p.created_at
                ORDER BY p.id DESC
                """
            )

            rows = cursor.fetchall()

            return [
                dict(row)
                for row in rows
            ]


def get_project(
    project_id: int
):

    with postgres_storage.get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    code,
                    client,
                    created_at
                FROM projects
                WHERE id = %s
                """,
                (project_id,)
            )

            row = cursor.fetchone()

            return (
                dict(row)
                if row
                else None
            )


# ============================================================
# Upload storage
# ============================================================

def save_upload(
    project_id: int,
    filename: str,
    content: bytes,
    analysis_json: str
) -> dict[str, Any]:

    path: Path | None = None

    with postgres_storage.get_connection() as connection:

        try:
            with connection.cursor() as cursor:

                # Lock the project row so two simultaneous
                # uploads cannot receive the same version.
                cursor.execute(
                    """
                    SELECT id
                    FROM projects
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (project_id,)
                )

                project = cursor.fetchone()

                if not project:
                    raise ValueError(
                        "Project not found"
                    )

                cursor.execute(
                    """
                    SELECT
                        COALESCE(
                            MAX(version_no),
                            0
                        ) + 1 AS next_version
                    FROM uploads
                    WHERE project_id = %s
                    """,
                    (project_id,)
                )

                version_row = cursor.fetchone()

                if not version_row:
                    raise RuntimeError(
                        "Could not determine upload version"
                    )

                version = int(
                    version_row["next_version"]
                )

                project_dir = (
                    UPLOAD_DIR
                    / str(project_id)
                )

                project_dir.mkdir(
                    parents=True,
                    exist_ok=True
                )

                safe_name = (
                    f"U{version:03d}_"
                    f"{Path(filename).name}"
                )

                path = (
                    project_dir
                    / safe_name
                )

                path.write_bytes(
                    content
                )

                cursor.execute(
                    """
                    INSERT INTO uploads (
                        project_id,
                        filename,
                        stored_path,
                        uploaded_at,
                        version_no,
                        analysis_json,
                        status
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    RETURNING
                        id,
                        project_id,
                        filename,
                        stored_path,
                        uploaded_at,
                        version_no,
                        analysis_json,
                        status
                    """,
                    (
                        project_id,
                        filename,
                        str(path),
                        _now(),
                        version,
                        analysis_json,
                        "ANALYZED",
                    )
                )

                row = cursor.fetchone()

                if not row:
                    raise RuntimeError(
                        "Upload record creation failed"
                    )

            connection.commit()

            return dict(row)

        except Exception:

            connection.rollback()

            if (
                path is not None
                and path.exists()
            ):
                try:
                    path.unlink()
                except OSError:
                    pass

            raise


def list_uploads(
    project_id: int
):

    with postgres_storage.get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    filename,
                    uploaded_at,
                    version_no,
                    status
                FROM uploads
                WHERE project_id = %s
                ORDER BY version_no DESC
                """,
                (project_id,)
            )

            rows = cursor.fetchall()

            return [
                dict(row)
                for row in rows
            ]


# ============================================================
# Latest project analysis
# ============================================================

def latest_analysis(
    project_id: int
):

    with postgres_storage.get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    filename,
                    uploaded_at,
                    version_no,
                    analysis_json
                FROM uploads
                WHERE project_id = %s
                  AND analysis_json IS NOT NULL
                ORDER BY version_no DESC
                LIMIT 1
                """,
                (project_id,)
            )

            row = cursor.fetchone()

            if not row:
                return None

            result = json.loads(
                row["analysis_json"]
            )

            result["_upload"] = {
                "id": row["id"],
                "filename": row["filename"],
                "uploaded_at": row["uploaded_at"],
                "version_no": row["version_no"],
            }

            return result
