"""SQLAlchemy engine, session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# check_same_thread=False: FastAPI serves requests from a thread pool, and
# SQLite's default guard would reject the connection being reused there.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that always closes."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create any missing tables. Safe to call on every startup."""
    from app import models  # noqa: F401  (import registers the mappers)

    Base.metadata.create_all(bind=engine)
