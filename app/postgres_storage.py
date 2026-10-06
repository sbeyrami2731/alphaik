"""PostgreSQL connection and safe diagnostics for Alphaik."""

from __future__ import annotations

import logging
import os

import psycopg
from psycopg.rows import dict_row


logger = logging.getLogger("uvicorn.error")


def _required_env(name: str) -> str:
    """Read a required environment variable."""

    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"{name} is not configured"
        )

    return value


def get_connection():
    """Open a secure PostgreSQL connection."""

    host = _required_env("DB_HOST")
    port = _required_env("DB_PORT")
    database = _required_env("DB_NAME")
    user = _required_env("DB_USER")
    password = _required_env("DB_PASSWORD")

    try:
        port_number = int(port)

    except ValueError as exc:
        raise RuntimeError(
            "DB_PORT must be a valid integer"
        ) from exc

    return psycopg.connect(
        host=host,
        port=port_number,
        dbname=database,
        user=user,
        password=password,
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
        "too many connections" in message
        or "max client connections reached" in message
    ):
        return "POOLER_CONNECTION_LIMIT"

    if (
        "server closed the connection unexpectedly" in message
        or "connection reset by peer" in message
    ):
        return "CONNECTION_DROPPED"

    return "OTHER_CONNECTION_ERROR"


def check_connection() -> bool:
    """Test connectivity and log a safe diagnostic category."""

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        1 AS result,
                        current_database() AS database_name,
                        current_user AS database_user
                    """
                )

                row = cursor.fetchone()

        connected = (
            row is not None
            and row["result"] == 1
        )

        if connected:
            logger.info(
                "ALPHAIK_POSTGRES_CHECK: CONNECTED"
            )

            logger.info(
                "ALPHAIK_POSTGRES_DATABASE: %s",
                row["database_name"],
            )

            logger.info(
                "ALPHAIK_POSTGRES_USER: %s",
                row["database_user"],
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

        logger.error(
            "ALPHAIK_POSTGRES_EXCEPTION: %s",
            exc.__class__.__name__,
        )

        sqlstate = getattr(exc, "sqlstate", None)

        if sqlstate:
            logger.error(
                "ALPHAIK_POSTGRES_SQLSTATE: %s",
                sqlstate,
            )

        raise
