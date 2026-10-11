"""Controlled SQLite to PostgreSQL data migration for Alphaik."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from . import postgres_storage
from . import storage


logger = logging.getLogger("uvicorn.error")


def _sqlite_connection() -> sqlite3.Connection:
    """Open the current Alphaik SQLite database safely."""

    connection = sqlite3.connect(storage.DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")

    return connection


def _source_counts(
    connection: sqlite3.Connection
) -> dict[str, int]:
    """Count the SQLite records that are eligible for migration."""

    return {
        "users": connection.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0],

        "projects": connection.execute(
            "SELECT COUNT(*) FROM projects"
        ).fetchone()[0],

        "uploads": connection.execute(
            "SELECT COUNT(*) FROM uploads"
        ).fetchone()[0],

        "sessions": connection.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0],
    }


def _target_counts(cursor) -> dict[str, int]:
    """Count migrated records currently stored in PostgreSQL."""

    cursor.execute("SELECT COUNT(*) AS count FROM users")
    users = int(cursor.fetchone()["count"])

    cursor.execute("SELECT COUNT(*) AS count FROM projects")
    projects = int(cursor.fetchone()["count"])

    cursor.execute("SELECT COUNT(*) AS count FROM uploads")
    uploads = int(cursor.fetchone()["count"])

    return {
        "users": users,
        "projects": projects,
        "uploads": uploads,
    }


def _reset_sequences(cursor) -> None:
    """
    Synchronize PostgreSQL BIGSERIAL sequences after inserting
    records with preserved SQLite IDs.
    """

    cursor.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('users', 'id'),
            COALESCE(MAX(id), 1),
            MAX(id) IS NOT NULL
        )
        FROM users
        """
    )

    cursor.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('projects', 'id'),
            COALESCE(MAX(id), 1),
            MAX(id) IS NOT NULL
        )
        FROM projects
        """
    )

    cursor.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('uploads', 'id'),
            COALESCE(MAX(id), 1),
            MAX(id) IS NOT NULL
        )
        FROM uploads
        """
    )


def migrate_sqlite_to_postgres() -> dict[str, Any]:
    """
    Copy Alphaik metadata from SQLite to PostgreSQL.

    The migration is intentionally idempotent:
    existing PostgreSQL rows with the same IDs are left intact.

    Sessions are not migrated. Users must authenticate again
    after PostgreSQL becomes the active backend.

    Uploaded file bytes are not moved by this function.
    Object-storage migration is handled separately.
    """

    logger.info(
        "ALPHAIK_DATA_MIGRATION: STARTED"
    )

    with _sqlite_connection() as sqlite_connection:

        source = _source_counts(
            sqlite_connection
        )

        sqlite_users = sqlite_connection.execute(
            """
            SELECT
                id,
                username,
                password_hash,
                created_at
            FROM users
            ORDER BY id
            """
        ).fetchall()

        sqlite_projects = sqlite_connection.execute(
            """
            SELECT
                id,
                name,
                code,
                client,
                created_at
            FROM projects
            ORDER BY id
            """
        ).fetchall()

        sqlite_uploads = sqlite_connection.execute(
            """
            SELECT
                id,
                project_id,
                filename,
                stored_path,
                uploaded_at,
                version_no,
                analysis_json,
                status
            FROM uploads
            ORDER BY id
            """
        ).fetchall()

    with postgres_storage.get_connection() as pg_connection:

        try:
            with pg_connection.cursor() as cursor:

                # --------------------------------------------
                # Users
                # --------------------------------------------

                for row in sqlite_users:

                    cursor.execute(
                        """
                        INSERT INTO users (
                            id,
                            username,
                            password_hash,
                            created_at
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        ON CONFLICT (id)
                        DO NOTHING
                        """,
                        (
                            row["id"],
                            row["username"],
                            row["password_hash"],
                            row["created_at"],
                        )
                    )

                # --------------------------------------------
                # Projects
                # --------------------------------------------

                for row in sqlite_projects:

                    cursor.execute(
                        """
                        INSERT INTO projects (
                            id,
                            name,
                            code,
                            client,
                            created_at
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        ON CONFLICT (id)
                        DO NOTHING
                        """,
                        (
                            row["id"],
                            row["name"],
                            row["code"],
                            row["client"],
                            row["created_at"],
                        )
                    )

                # --------------------------------------------
                # Upload metadata and analysis
                # --------------------------------------------

                for row in sqlite_uploads:

                    cursor.execute(
                        """
                        INSERT INTO uploads (
                            id,
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
                            %s,
                            %s
                        )
                        ON CONFLICT (id)
                        DO NOTHING
                        """,
                        (
                            row["id"],
                            row["project_id"],
                            row["filename"],
                            row["stored_path"],
                            row["uploaded_at"],
                            row["version_no"],
                            row["analysis_json"],
                            row["status"],
                        )
                    )

                _reset_sequences(cursor)

                target = _target_counts(cursor)

            pg_connection.commit()

        except Exception:

            pg_connection.rollback()

            logger.exception(
                "ALPHAIK_DATA_MIGRATION: FAILED"
            )

            raise

    result = {
        "status": "ok",
        "source": {
            "users": source["users"],
            "projects": source["projects"],
            "uploads": source["uploads"],
        },
        "target": target,
        "sessions_skipped": source["sessions"],
    }

    logger.info(
        (
            "ALPHAIK_DATA_MIGRATION: COMPLETED "
            "users=%s projects=%s uploads=%s "
            "sessions_skipped=%s"
        ),
        source["users"],
        source["projects"],
        source["uploads"],
        source["sessions"],
    )

    return result
