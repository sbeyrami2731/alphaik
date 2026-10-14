from pathlib import Path
import json
import threading

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Header,
    Response
)

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import parse_workbook, analyze
from . import (
    storage_router as storage,
    postgres_storage,
    postgres_schema,
    postgres_migration,
)


# ============================================================
# Application
# ============================================================

BASE = Path(__file__).resolve().parent

app = FastAPI(
    title="Alphaik Project Controls",
    version="0.2.0"
)

app.mount(
    "/static",
    StaticFiles(directory=BASE / "static"),
    name="static"
)


# ============================================================
# Background PostgreSQL bootstrap and migration
# ============================================================

def _prepare_postgres_in_background():
    """
    Prepare PostgreSQL without blocking Render/FastAPI startup.

    Current migration stage:
    1. Verify PostgreSQL connectivity.
    2. Ensure schema version 1 exists.
    3. Copy current SQLite metadata into PostgreSQL.

    The migration itself is idempotent.
    """

    try:
        connected = postgres_storage.check_connection()

        if not connected:
            return

        postgres_schema.ensure_schema()

        result = (
            postgres_migration.migrate_sqlite_to_postgres()
        )

        source = result["source"]
        target = result["target"]

        if (
            target["users"] < source["users"]
            or target["projects"] < source["projects"]
            or target["uploads"] < source["uploads"]
        ):
            raise RuntimeError(
                "PostgreSQL migration verification failed"
            )

    except Exception:
        # Detailed safe diagnostics are emitted by the
        # migration/database modules. Alphaik must remain
        # available while migration is being validated.
        pass


# ============================================================
# Startup
# ============================================================

@app.on_event("startup")
def startup():

    # The active application storage backend is selected
    # through ALPHAIK_STORAGE_BACKEND.
    #
    # Default remains SQLite until PostgreSQL cutover is
    # explicitly enabled in the environment.
    storage.init_db()

    # PostgreSQL preparation runs in a background thread so
    # Render port binding and health checks are never blocked.
    thread = threading.Thread(
        target=_prepare_postgres_in_background,
        name="alphaik-postgres-migration",
        daemon=True
    )

    thread.start()


# ============================================================
# Public endpoints
# ============================================================

@app.get("/")
def home():
    return FileResponse(
        BASE / "static" / "index.html"
    )


@app.head("/")
def home_head():
    return Response(status_code=200)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "alphaik",
        "version": "0.2.0",
        "storage_backend": storage.backend_name()
    }


@app.head("/api/health")
def health_head():
    return Response(status_code=200)


# ============================================================
# Request models
# ============================================================

class LoginIn(BaseModel):
    username: str
    password: str


class ProjectIn(BaseModel):
    name: str
    code: str | None = None
    client: str | None = None


# ============================================================
# Authentication
# ============================================================

def get_bearer_token(
    authorization: str | None
) -> str:

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    scheme, separator, token = authorization.partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not token.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header"
        )

    return token.strip()


def auth(authorization: str | None):

    token = get_bearer_token(
        authorization
    )

    user = storage.user_for_token(
        token
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    return user


# ============================================================
# Login and logout
# ============================================================

@app.post("/api/login")
def api_login(body: LoginIn):

    token = storage.login(
        body.username,
        body.password
    )

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    return {
        "token": token,
        "username": body.username,
        "expires_in": (
            storage.SESSION_TTL_HOURS
            * 3600
        )
    }


@app.post("/api/logout")
def api_logout(
    authorization: str | None = Header(None)
):

    token = get_bearer_token(
        authorization
    )

    auth(
        authorization
    )

    storage.logout(
        token
    )

    return {
        "status": "ok",
        "message": "Logged out successfully"
    }


# ============================================================
# Protected PostgreSQL connectivity check
# ============================================================

@app.get("/api/admin/postgres-check")
def postgres_check(
    authorization: str | None = Header(None)
):

    auth(
        authorization
    )

    try:
        connected = (
            postgres_storage.check_connection()
        )

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL connection check failed"
        )

    if not connected:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL connection check failed"
        )

    return {
        "status": "ok",
        "database": "postgresql",
        "connected": True
    }


# ============================================================
# Projects
# ============================================================

@app.get("/api/projects")
def projects(
    authorization: str | None = Header(None)
):

    auth(
        authorization
    )

    return storage.list_projects()


@app.post("/api/projects")
def project_create(
    body: ProjectIn,
    authorization: str | None = Header(None)
):

    auth(
        authorization
    )

    return storage.create_project(
        body.name,
        body.code,
        body.client
    )


@app.get("/api/projects/{project_id}")
def project(
    project_id: int,
    authorization: str | None = Header(None)
):

    auth(
        authorization
    )

    project_data = storage.get_project(
        project_id
    )

    if not project_data:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    project_data["uploads"] = (
        storage.list_uploads(
            project_id
        )
    )

    project_data["latest_analysis"] = (
        storage.latest_analysis(
            project_id
        )
    )

    return project_data


# ============================================================
# Project uploads
# ============================================================

@app.post("/api/projects/{project_id}/upload")
async def project_upload(
    project_id: int,
    file: UploadFile = File(...),
    authorization: str | None = Header(None)
):

    auth(
        authorization
    )

    if not storage.get_project(
        project_id
    ):
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    if (
        not file.filename
        or not file.filename.lower().endswith(
            ".xlsx"
        )
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Current MVP accepts "
                "P6 Excel .xlsx exports."
            )
        )

    try:

        content = await file.read()

        task, relationships = (
            parse_workbook(
                content
            )
        )

        result = analyze(
            task,
            relationships
        )

        result["file_name"] = (
            file.filename
        )

        upload = storage.save_upload(
            project_id,
            file.filename,
            content,
            json.dumps(
                result,
                ensure_ascii=False,
                default=str
            )
        )

        result["_upload"] = {
            "id": upload["id"],
            "version_no": upload["version_no"],
            "uploaded_at": upload["uploaded_at"]
        }

        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        )

    except Exception:

        raise HTTPException(
            status_code=500,
            detail="Analysis failed"
        )
