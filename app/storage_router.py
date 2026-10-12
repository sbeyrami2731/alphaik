"""Storage backend router for Alphaik."""

from __future__ import annotations

import os
from typing import Any

from . import storage as sqlite_storage
from . import postgres_app_storage


# ============================================================
# Supported storage backends
# ============================================================

SQLITE_BACKEND = "sqlite"
POSTGRES_BACKEND = "postgresql"

SUPPORTED_BACKENDS = {
    SQLITE_BACKEND,
    POSTGRES_BACKEND,
}


# ============================================================
# Backend selection
# ============================================================

def backend_name() -> str:
    """
    Return the configured Alphaik application storage backend.

    Default remains SQLite until PostgreSQL cutover is
    explicitly enabled.
    """

    value = os.getenv(
        "ALPHAIK_STORAGE_BACKEND",
        SQLITE_BACKEND
    ).strip().lower()

    aliases = {
        "postgres": POSTGRES_BACKEND,
        "postgresql": POSTGRES_BACKEND,
        "sqlite": SQLITE_BACKEND,
    }

    backend = aliases.get(
        value,
        value
    )

    if backend not in SUPPORTED_BACKENDS:
        raise RuntimeError(
            "ALPHAIK_STORAGE_BACKEND must be "
            "'sqlite' or 'postgresql'"
        )

    return backend


def _backend():
    """
    Return the active storage implementation.
    """

    backend = backend_name()

    if backend == POSTGRES_BACKEND:
        return postgres_app_storage

    return sqlite_storage


# ============================================================
# Shared configuration
# ============================================================

SESSION_TTL_HOURS = 8


# ============================================================
# Initialization
# ============================================================

def init_db() -> None:
    _backend().init_db()


# ============================================================
# Authentication
# ============================================================

def login(
    username: str,
    password: str
) -> str | None:

    return _backend().login(
        username,
        password
    )


def user_for_token(
    token: str | None
):

    return _backend().user_for_token(
        token
    )


def logout(
    token: str | None
) -> bool:

    return _backend().logout(
        token
    )


# ============================================================
# Projects
# ============================================================

def create_project(
    name: str,
    code: str | None = None,
    client: str | None = None
) -> dict[str, Any]:

    return _backend().create_project(
        name,
        code,
        client
    )


def list_projects():

    return _backend().list_projects()


def get_project(
    project_id: int
):

    return _backend().get_project(
        project_id
    )


# ============================================================
# Uploads
# ============================================================

def save_upload(
    project_id: int,
    filename: str,
    content: bytes,
    analysis_json: str
) -> dict[str, Any]:

    return _backend().save_upload(
        project_id,
        filename,
        content,
        analysis_json
    )


def list_uploads(
    project_id: int
):

    return _backend().list_uploads(
        project_id
    )


# ============================================================
# Analysis
# ============================================================

def latest_analysis(
    project_id: int
):

    return _backend().latest_analysis(
        project_id
    )
