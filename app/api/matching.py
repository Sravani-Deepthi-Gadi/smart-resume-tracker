"""The matcher endpoint: score a resume against a job description."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Job, Resume
from app.schemas import MatchOut, MatchRequest
from app.services import score_pair

router = APIRouter(prefix="/api/match", tags=["matching"])


@router.post("", response_model=MatchOut, summary="Score a resume against a job description")
def match(payload: MatchRequest, session: Session = Depends(get_session)) -> dict:
    """Accepts stored ids, raw text, or a mix of the two.

    Ids win when both are supplied, so the UI can send a ``resume_id`` with a
    pasted job description that has not been saved as a job yet.
    """
    resume_text, candidate_years = payload.resume_text, None
    if payload.resume_id is not None:
        resume = session.get(Resume, payload.resume_id)
        if resume is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No resume with id {payload.resume_id}.")
        resume_text, candidate_years = resume.raw_text, resume.experience_years

    job_description = payload.job_description
    if payload.job_id is not None:
        job = session.get(Job, payload.job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job with id {payload.job_id}.")
        job_description = job.description

    if not (resume_text or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide resume_id or resume_text.")
    if not (job_description or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide job_id or job_description.")

    result = score_pair(session, resume_text, job_description, candidate_years)
    return result.to_dict()
