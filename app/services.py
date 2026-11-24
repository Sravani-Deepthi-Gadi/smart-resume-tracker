"""Logic shared by more than one router: corpus building, scoring, serialisation."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.parser import ParsedResume, parse_resume
from app.core.scoring import (
    MatchResult,
    TfidfIndex,
    analyse_job,
    match_resume_to_job,
    resume_health,
)
from app.models import Application, Job, Resume


def build_index(session: Session) -> TfidfIndex:
    """TF-IDF index fitted on every stored job description.

    Fitting on the real corpus is what makes keyword similarity meaningful:
    terms every posting uses ("python", "agile") stop dominating the score,
    and terms specific to one posting start to count.  With fewer than three
    descriptions stored the index falls back to plain TF cosine on its own.
    """
    descriptions = session.scalars(
        select(Job.description).where(Job.description != "")
    ).all()
    return TfidfIndex(list(descriptions))


def store_parsed(resume: Resume, text: str) -> ParsedResume:
    """Parse ``text`` and cache the result on the resume row."""
    parsed = parse_resume(text)
    resume.parsed_json = json.dumps(parsed.to_dict())
    return parsed


def health_payload(resume: Resume) -> list[dict]:
    """Resume hygiene checks, ready for the API response."""
    parsed = parse_resume(resume.raw_text)
    return [
        {"label": check.label, "passed": check.passed, "detail": check.detail}
        for check in resume_health(parsed, resume.raw_text)
    ]


def score_pair(
    session: Session,
    resume_text: str,
    job_description: str,
    candidate_years: float | None = None,
) -> MatchResult:
    """Score one resume against one job description using the stored corpus."""
    return match_resume_to_job(
        resume_text,
        job_description,
        candidate_years=candidate_years,
        index=build_index(session),
        weights=settings.weights,
    )


def refresh_application_score(session: Session, application: Application) -> float | None:
    """Recompute and cache an application's match score.

    Called whenever the application's resume changes, so the board can sort by
    fit without rescoring on every page load.
    """
    if application.resume is None or not application.job or not application.job.description:
        application.match_score = None
        return None
    result = score_pair(
        session,
        application.resume.raw_text,
        application.job.description,
        candidate_years=application.resume.experience_years,
    )
    application.match_score = result.overall
    return result.overall


def application_payload(application: Application) -> dict:
    """Flatten an application plus its job/resume labels into one dict."""
    return {
        "id": application.id,
        "job_id": application.job_id,
        "resume_id": application.resume_id,
        "status": application.status,
        "applied_on": application.applied_on,
        "next_action": application.next_action,
        "next_action_on": application.next_action_on,
        "notes": application.notes,
        "match_score": application.match_score,
        "created_at": application.created_at,
        "updated_at": application.updated_at,
        "job_title": application.job.title if application.job else None,
        "company": application.job.company if application.job else None,
        "location": application.job.location if application.job else None,
        "resume_label": application.resume.label if application.resume else None,
    }


def job_requirements(session: Session, job: Job) -> dict:
    """The analysed requirements of a job description."""
    if not job.description:
        return {}
    return analyse_job(job.description, build_index(session)).to_dict()


def resume_payload(resume: Resume) -> dict:
    """A resume row plus its parsed fields, for list responses."""
    return {
        "id": resume.id,
        "label": resume.label,
        "filename": resume.filename,
        "is_primary": resume.is_primary,
        "created_at": resume.created_at,
        "skills": resume.skills,
        "experience_years": resume.experience_years,
    }
