"""Pydantic request and response models - the API's contract."""

from __future__ import annotations

from datetime import datetime, date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import APPLICATION_STATUSES

Status = Literal["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"]


class ORMModel(BaseModel):
    """Base for responses read straight off an ORM object."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

class ResumeCreate(BaseModel):
    """Create a resume from pasted text (file uploads use the multipart route)."""

    label: Annotated[str, Field(min_length=1, max_length=120)]
    raw_text: Annotated[str, Field(min_length=30, description="Full resume text")]
    is_primary: bool = False


class ResumeSummary(ORMModel):
    id: int
    label: str
    filename: str | None = None
    is_primary: bool
    created_at: datetime
    skills: list[str] = []
    experience_years: float = 0.0


class ResumeDetail(ResumeSummary):
    raw_text: str
    parsed: dict = {}
    health: list["HealthItem"] = []


class HealthItem(BaseModel):
    label: str
    passed: bool
    detail: str


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class JobCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    company: Annotated[str, Field(min_length=1, max_length=160)]
    location: str | None = Field(default=None, max_length=160)
    source_url: str | None = Field(default=None, max_length=500)
    description: Annotated[str, Field(default="", description="Full job description text")] = ""


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    source_url: str | None = Field(default=None, max_length=500)
    description: str | None = None


class JobSummary(ORMModel):
    id: int
    title: str
    company: str
    location: str | None = None
    source_url: str | None = None
    created_at: datetime


class JobDetail(JobSummary):
    description: str
    requirements: dict = {}


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

class ApplicationCreate(BaseModel):
    job_id: int
    resume_id: int | None = None
    status: Status = "saved"
    applied_on: date | None = None
    next_action: str | None = Field(default=None, max_length=200)
    next_action_on: date | None = None
    notes: str | None = None


class ApplicationUpdate(BaseModel):
    resume_id: int | None = None
    status: Status | None = None
    applied_on: date | None = None
    next_action: str | None = Field(default=None, max_length=200)
    next_action_on: date | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def known_status(cls, value: str | None) -> str | None:
        if value is not None and value not in APPLICATION_STATUSES:
            raise ValueError(f"status must be one of {APPLICATION_STATUSES}")
        return value


class ApplicationOut(ORMModel):
    id: int
    job_id: int
    resume_id: int | None = None
    status: str
    applied_on: date | None = None
    next_action: str | None = None
    next_action_on: date | None = None
    notes: str | None = None
    match_score: float | None = None
    created_at: datetime
    updated_at: datetime
    # Flattened for the board so the UI needs one request, not N.
    job_title: str | None = None
    company: str | None = None
    location: str | None = None
    resume_label: str | None = None


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

class MatchRequest(BaseModel):
    """Score a resume against a job. Ids are resolved from the database;
    raw text is accepted too so the matcher can be tried without saving anything."""

    resume_id: int | None = None
    job_id: int | None = None
    resume_text: str | None = None
    job_description: str | None = None


class MatchOut(BaseModel):
    overall: float
    verdict: str
    skill_score: float | None = None
    keyword_score: float | None = None
    experience_score: float | None = None
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    missing_required: list[str] = []
    extra_skills: list[str] = []
    missing_keywords: list[str] = []
    required_years: float | None = None
    candidate_years: float = 0.0
    weights_used: dict[str, float] = {}
    suggestions: list[str] = []


# ---------------------------------------------------------------------------
# Screening (recruiter side)
# ---------------------------------------------------------------------------

class ScreeningCandidateOut(ORMModel):
    id: int
    rank: int
    candidate_name: str | None = None
    email: str | None = None
    filename: str
    score: float
    verdict: str
    experience_years: float
    matched_skills: list[str] = []
    missing_skills: list[str] = []


class ScreeningRunOut(ORMModel):
    id: int
    job_id: int
    candidate_count: int
    created_at: datetime
    job_title: str | None = None
    company: str | None = None
    candidates: list[ScreeningCandidateOut] = []


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class FunnelStage(BaseModel):
    status: str
    count: int


class UpcomingAction(BaseModel):
    application_id: int
    job_title: str
    company: str
    next_action: str
    next_action_on: date | None = None
    overdue: bool = False


class StatsOut(BaseModel):
    total_applications: int = 0
    active_applications: int = 0
    resumes: int = 0
    jobs: int = 0
    average_match_score: float | None = None
    best_match: float | None = None
    interview_rate: float | None = None
    funnel: list[FunnelStage] = []
    upcoming: list[UpcomingAction] = []
    top_missing_skills: list[dict] = []


ResumeDetail.model_rebuild()
