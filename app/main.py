"""Smart Resume Tracker - application entry point.

Run it with::

    uvicorn app.main:app --reload

then open http://127.0.0.1:8000.  Interactive API docs live at ``/docs``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import applications, jobs, matching, resumes, screening, stats
from app.config import settings
from app.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("smart_resume_tracker")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables before the first request is served."""
    init_db()
    logger.info("%s %s ready", settings.app_name, settings.version)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
    description=(
        "Track job applications and screen resumes against job descriptions. "
        "One parsing and scoring core serves both: the candidate view scores "
        "your resume against a posting and tells you what is missing, the "
        "recruiter view ranks a batch of resumes against one job."
    ),
)

# Open CORS so the same API can back a separate front end later. Tighten this
# with SRT_-prefixed settings before putting the app on a public host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (resumes, jobs, applications, matching, screening, stats):
    app.include_router(module.router)


@app.get("/api/health", tags=["meta"], summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": settings.version}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Mounted last so it never shadows an /api route.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
