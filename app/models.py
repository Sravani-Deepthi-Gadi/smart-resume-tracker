"""ORM models: resumes, jobs, applications and recruiter screening runs."""

from __future__ import annotations

import json
from datetime import datetime, date, timezone

from sqlalchemy import ForeignKey, Integer, String, Text, Float, Date, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# The application funnel, in the order it is displayed.
APPLICATION_STATUSES = (
    "saved",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
)

# Statuses that mean the application is no longer live.
CLOSED_STATUSES = ("rejected", "withdrawn")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Resume(Base):
    """One version of the candidate's resume, plus its parsed fields."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    filename: Mapped[str | None] = mapped_column(String(255), default=None)
    raw_text: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[str] = mapped_column(Text, default="{}")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    applications: Mapped[list["Application"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )

    @property
    def parsed(self) -> dict:
        try:
            return json.loads(self.parsed_json or "{}")
        except json.JSONDecodeError:
            return {}

    @property
    def skills(self) -> list[str]:
        return list(self.parsed.get("skills", []))

    @property
    def experience_years(self) -> float:
        return float(self.parsed.get("experience_years") or 0.0)


class Job(Base):
    """A role the candidate is tracking, with its description text."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(160))
    location: Mapped[str | None] = mapped_column(String(160), default=None)
    source_url: Mapped[str | None] = mapped_column(String(500), default=None)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    screening_runs: Mapped[list["ScreeningRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Application(Base):
    """The candidate's application of one resume to one job, and its status."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), index=True, default=None
    )
    status: Mapped[str] = mapped_column(String(20), default="saved", index=True)
    applied_on: Mapped[date | None] = mapped_column(Date, default=None)
    next_action: Mapped[str | None] = mapped_column(String(200), default=None)
    next_action_on: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    # Cached so the board can sort by fit without rescoring every request.
    match_score: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    job: Mapped["Job"] = relationship(back_populates="applications")
    resume: Mapped["Resume | None"] = relationship(back_populates="applications")


class ScreeningRun(Base):
    """Recruiter side: one batch of resumes ranked against one job."""

    __tablename__ = "screening_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    job: Mapped["Job"] = relationship(back_populates="screening_runs")
    candidates: Mapped[list["ScreeningCandidate"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ScreeningCandidate.rank"
    )


class ScreeningCandidate(Base):
    """One resume's result inside a screening run."""

    __tablename__ = "screening_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("screening_runs.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    candidate_name: Mapped[str | None] = mapped_column(String(160), default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    filename: Mapped[str] = mapped_column(String(255), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(20), default="weak")
    experience_years: Mapped[float] = mapped_column(Float, default=0.0)
    matched_skills_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_skills_json: Mapped[str] = mapped_column(Text, default="[]")

    run: Mapped["ScreeningRun"] = relationship(back_populates="candidates")

    @property
    def matched_skills(self) -> list[str]:
        return json.loads(self.matched_skills_json or "[]")

    @property
    def missing_skills(self) -> list[str]:
        return json.loads(self.missing_skills_json or "[]")
