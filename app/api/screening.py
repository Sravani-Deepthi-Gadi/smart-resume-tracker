"""Recruiter side: rank a batch of resumes against one job."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.core.parser import UnsupportedFileType, extract_text, parse_resume
from app.database import get_session
from app.models import Job, ScreeningCandidate, ScreeningRun
from app.schemas import ScreeningRunOut
from app.services import score_pair

router = APIRouter(prefix="/api/screening", tags=["screening"])


@router.get("/runs", response_model=list[ScreeningRunOut], summary="List screening runs")
def list_runs(session: Session = Depends(get_session)) -> list[dict]:
    runs = session.scalars(
        select(ScreeningRun)
        .options(selectinload(ScreeningRun.job))
        .order_by(ScreeningRun.created_at.desc())
    ).all()
    # Candidates are omitted from the list view; fetch a run to get them.
    return [_run_payload(run, include_candidates=False) for run in runs]


@router.post("/runs", response_model=ScreeningRunOut, status_code=status.HTTP_201_CREATED,
             summary="Screen and rank resumes against a job")
async def create_run(
    job_id: int = Form(..., description="Job the candidates are screened against"),
    files: list[UploadFile] = File(..., description="One or more PDF / DOCX / TXT resumes"),
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job with id {job_id}.")
    if not job.description.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That job has no description saved, so there is nothing to screen against.",
        )
    if len(files) > settings.max_screening_files:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"At most {settings.max_screening_files} resumes per run.",
        )

    scored: list[dict] = []
    skipped: list[str] = []

    for upload in files:
        data = await upload.read()
        filename = upload.filename or "resume"
        if not data or len(data) > settings.max_upload_bytes:
            skipped.append(filename)
            continue
        try:
            text = extract_text(data, filename)
        except (UnsupportedFileType, Exception):  # noqa: B014 - skip, never fail the batch
            skipped.append(filename)
            continue
        if len(text.split()) < 20:
            skipped.append(filename)
            continue

        parsed = parse_resume(text)
        result = score_pair(session, text, job.description, parsed.experience_years)
        scored.append(
            {
                "candidate_name": parsed.name,
                "email": parsed.email,
                "filename": filename,
                "score": result.overall,
                "verdict": result.verdict,
                "experience_years": parsed.experience_years,
                "matched_skills": result.matched_skills,
                "missing_skills": result.missing_skills[:10],
            }
        )

    if not scored:
        detail = "None of the uploaded files could be read as a text-based resume."
        if skipped:
            detail += " Skipped: " + ", ".join(skipped[:5])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)

    scored.sort(key=lambda candidate: candidate["score"], reverse=True)

    run = ScreeningRun(job_id=job.id, candidate_count=len(scored))
    session.add(run)
    session.flush()
    for position, candidate in enumerate(scored, start=1):
        session.add(
            ScreeningCandidate(
                run_id=run.id,
                rank=position,
                candidate_name=candidate["candidate_name"],
                email=candidate["email"],
                filename=candidate["filename"],
                score=candidate["score"],
                verdict=candidate["verdict"],
                experience_years=candidate["experience_years"],
                matched_skills_json=json.dumps(candidate["matched_skills"]),
                missing_skills_json=json.dumps(candidate["missing_skills"]),
            )
        )
    session.commit()
    session.refresh(run)
    return _run_payload(run)


@router.get("/runs/{run_id}", response_model=ScreeningRunOut,
            summary="One screening run with its ranked candidates")
def get_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = session.get(ScreeningRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No screening run with id {run_id}.")
    return _run_payload(run)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
               summary="Delete a screening run")
def delete_run(run_id: int, session: Session = Depends(get_session)) -> None:
    run = session.get(ScreeningRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No screening run with id {run_id}.")
    session.delete(run)
    session.commit()


def _run_payload(run: ScreeningRun, include_candidates: bool = True) -> dict:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "candidate_count": run.candidate_count,
        "created_at": run.created_at,
        "job_title": run.job.title if run.job else None,
        "company": run.job.company if run.job else None,
        "candidates": [
            {
                "id": candidate.id,
                "rank": candidate.rank,
                "candidate_name": candidate.candidate_name,
                "email": candidate.email,
                "filename": candidate.filename,
                "score": candidate.score,
                "verdict": candidate.verdict,
                "experience_years": candidate.experience_years,
                "matched_skills": candidate.matched_skills,
                "missing_skills": candidate.missing_skills,
            }
            for candidate in (run.candidates if include_candidates else [])
        ],
    }
