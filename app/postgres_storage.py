
"""PostgreSQL connection utilities for Alphaik development."""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row


def get_connection():
    """Open a secure connection to the configured PostgreSQL database."""

    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    if "[YOUR-PASSWORD]" in database_url:
        raise RuntimeError(
            "Replace the password placeholder in DATABASE_URL"
        )

    return psycopg.connect(
        database_url,
        sslmode="require",
        connect_timeout=10,
        row_factory=dict_row,
    )


def check_connection() -> bool:
    """Check database connectivity without modifying any data."""

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS result")
            row = cursor.fetchone()

    return row is not None and row["result"] == 1
