
"""PostgreSQL connection and safe diagnostics for Alphaik."""

from __future__ import annotations

import logging
import os

import psycopg
from psycopg.rows import dict_row


logger = logging.getLogger("uvicorn.error")


def get_connection():
    """Open a secure PostgreSQL connection."""

    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    if "[YOUR-PASSWORD]" in database_url:
        raise RuntimeError(
            "Database password placeholder has not been replaced"
        )

    return psycopg.connect(
        database_url,
        sslmode="require",
        connect_timeout=10,
        row_factory=dict_row,
    )


def classify_error(exc: Exception) -> str:
    """Classify failures without exposing credentials."""

    if isinstance(exc, RuntimeError):
        return "CONFIGURATION_ERROR"

    sqlstate = getattr(exc, "sqlstate", None)

    if sqlstate == "28P01":
        return "INVALID_DATABASE_PASSWORD"

    if sqlstate == "28000":
        return "INVALID_DATABASE_USER"

    message = str(exc).lower()

    if "tenant or user not found" in message:
        return "INVALID_POOLER_USERNAME_OR_REGION"

    if (
        "password authentication failed" in message
        or "authentication failed" in message
    ):
        return "DATABASE_AUTHENTICATION_FAILED"

    if (
        "could not translate host name" in message
        or "name or service not known" in message
        or "nodename nor servname" in message
    ):
        return "DNS_OR_HOST_ERROR"

    if (
        "timeout" in message
        or "timed out" in message
    ):
        return "CONNECTION_TIMEOUT"

    if (
        "network is unreachable" in message
        or "no route to host" in message
    ):
        return "NETWORK_ERROR"

    if "connection refused" in message:
        return "CONNECTION_REFUSED"

    if (
        "ssl" in message
        or "certificate" in message
    ):
        return "SSL_ERROR"

    if (
        "invalid" in message
        and (
            "uri" in message
            or "connection string" in message
            or "percent" in message
        )
    ):
        return "INVALID_CONNECTION_STRING"

    return "OTHER_CONNECTION_ERROR"


def check_connection() -> bool:
    """Test connectivity and log a safe diagnostic category."""

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS result")
                row = cursor.fetchone()

        connected = (
            row is not None
            and row["result"] == 1
        )

        if connected:
            logger.info(
                "ALPHAIK_POSTGRES_CHECK: CONNECTED"
            )
        else:
            logger.warning(
                "ALPHAIK_POSTGRES_CHECK: UNEXPECTED_RESULT"
            )

        return connected

    except Exception as exc:
        category = classify_error(exc)

        logger.error(
            "ALPHAIK_POSTGRES_CHECK: %s",
            category,
        )

        raise
