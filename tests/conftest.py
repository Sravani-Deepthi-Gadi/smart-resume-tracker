"""Shared fixtures: a throwaway database and a TestClient bound to it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, get_session  # noqa: E402
from app.main import app  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture()
def client(tmp_path):
    """A TestClient whose database is a fresh SQLite file per test."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}, future=True
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture(scope="session")
def resume_text() -> str:
    return (SAMPLES / "sample_resume.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def job_text() -> str:
    return (SAMPLES / "sample_job.txt").read_text(encoding="utf-8")


@pytest.fixture()
def saved_job(client, job_text) -> dict:
    response = client.post(
        "/api/jobs",
        json={
            "title": "Java Backend Engineer",
            "company": "QualiZeal",
            "location": "Hyderabad",
            "description": job_text,
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture()
def saved_resume(client, resume_text) -> dict:
    response = client.post(
        "/api/resumes",
        json={"label": "Backend - Java focus", "raw_text": resume_text, "is_primary": True},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture(scope="session")
def resume_pdf_bytes() -> bytes:
    """A real, text-based PDF resume committed under samples/."""
    path = SAMPLES / "sample_resume.pdf"
    if not path.exists():
        pytest.skip("samples/sample_resume.pdf is missing")
    return path.read_bytes()
