"""PostgreSQL schema management for Alphaik."""

from __future__ import annotations

import logging

from . import postgres_storage


logger = logging.getLogger("uvicorn.error")


SCHEMA_VERSION = 1


def ensure_schema() -> None:
    """
    Create the initial Alphaik PostgreSQL schema.

    This operation is idempotent:
    running it multiple times must not delete or overwrite
    existing project data.
    """

    with postgres_storage.get_connection() as connection:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Schema migration tracking
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ------------------------------------------------
            # Users
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )

            # ------------------------------------------------
            # Sessions
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )

            # ------------------------------------------------
            # Projects
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    code TEXT,
                    client TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )

            # ------------------------------------------------
            # Uploads
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    id BIGSERIAL PRIMARY KEY,
                    project_id BIGINT NOT NULL
                        REFERENCES projects(id)
                        ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    uploaded_at TIMESTAMPTZ NOT NULL,
                    version_no INTEGER NOT NULL,
                    analysis_json TEXT,
                    status TEXT NOT NULL
                        DEFAULT 'UPLOADED',
                    CONSTRAINT uploads_project_version_unique
                        UNIQUE (project_id, version_no)
                )
                """
            )

            # ------------------------------------------------
            # Indexes
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_sessions_expires_at
                ON sessions (expires_at)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_uploads_project_id
                ON uploads (project_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_uploads_project_version
                ON uploads (
                    project_id,
                    version_no DESC
                )
                """
            )

            # ------------------------------------------------
            # Migration version
            # ------------------------------------------------

            cursor.execute(
                """
                INSERT INTO schema_migrations (
                    version
                )
                VALUES (%s)
                ON CONFLICT (version)
                DO NOTHING
                """,
                (SCHEMA_VERSION,)
            )

        connection.commit()

    logger.info(
        "ALPHAIK_POSTGRES_SCHEMA: READY version=%s",
        SCHEMA_VERSION,
    )
