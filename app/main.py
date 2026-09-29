
from pathlib import Path
import json

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Header
)

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import parse_workbook, analyze
from . import storage, postgres_storage


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
# Startup
# ============================================================

@app.on_event("startup")
def startup():

    # Initialize the current SQLite storage.
    # PostgreSQL is not yet the active storage backend.
    storage.init_db()

    # Check PostgreSQL automatically on every application
    # startup. The connection utility writes a safe
    # diagnostic code to the Render application logs.
    #
    # A failed PostgreSQL connection must not prevent
    # Alphaik from starting while migration is incomplete.

    try:
        postgres_storage.check_connection()

    except Exception:
        # The diagnostic category has already been logged
        # inside postgres_storage.check_connection().
        # Do not log the exception itself: database errors
        # may contain connection or credential details.
        pass


# ============================================================
# Public endpoints
# ============================================================

@app.get("/")
def home():
    return FileResponse(
        BASE / "static" / "index.html"
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "alphaik",
        "version": "0.2.0"
    }


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

    token = get_bearer_token(authorization)

    user = storage.user_for_token(token)

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
        "expires_in": storage.SESSION_TTL_HOURS * 3600
    }


@app.post("/api/logout")
def api_logout(
    authorization: str | None = Header(None)
):

    token = get_bearer_token(authorization)

    auth(authorization)

    storage.logout(token)

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

    auth(authorization)

    try:
        connected = postgres_storage.check_connection()

    except Exception:
        # Never expose database URLs or credentials.
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

    auth(authorization)

    return storage.list_projects()


@app.post("/api/projects")
def project_create(
    body: ProjectIn,
    authorization: str | None = Header(None)
):

    auth(authorization)

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

    auth(authorization)

    project_data = storage.get_project(
        project_id
    )

    if not project_data:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    project_data["uploads"] = storage.list_uploads(
        project_id
    )

    project_data["latest_analysis"] = (
        storage.latest_analysis(project_id)
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

    auth(authorization)

    if not storage.get_project(project_id):
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    if not file.filename or not file.filename.lower().endswith(
        ".xlsx"
    ):
        raise HTTPException(
            status_code=400,
            detail="Current MVP accepts P6 Excel .xlsx exports."
        )

    try:

        content = await file.read()

        task, relationships = parse_workbook(
            content
        )

        result = analyze(
            task,
            relationships
        )

        result["file_name"] = file.filename

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
