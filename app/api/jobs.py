"""Jobs: the postings being tracked, and their analysed requirements."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Job
from app.schemas import JobCreate, JobDetail, JobSummary, JobUpdate
from app.services import job_requirements

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobSummary], summary="List tracked jobs")
def list_jobs(session: Session = Depends(get_session)) -> list[Job]:
    return list(session.scalars(select(Job).order_by(Job.created_at.desc())).all())


@router.post("", response_model=JobDetail, status_code=status.HTTP_201_CREATED,
             summary="Add a job posting")
def create_job(payload: JobCreate, session: Session = Depends(get_session)) -> dict:
    job = Job(**payload.model_dump())
    session.add(job)
    session.commit()
    session.refresh(job)
    return _detail(session, job)


@router.get("/{job_id}", response_model=JobDetail,
            summary="One job, with required vs preferred skills extracted")
def get_job(job_id: int, session: Session = Depends(get_session)) -> dict:
    return _detail(session, _require(session, job_id))


@router.patch("/{job_id}", response_model=JobDetail, summary="Update a job")
def update_job(job_id: int, payload: JobUpdate, session: Session = Depends(get_session)) -> dict:
    job = _require(session, job_id)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(job, field_name, value)
    session.commit()
    session.refresh(job)
    return _detail(session, job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
               summary="Delete a job and its applications")
def delete_job(job_id: int, session: Session = Depends(get_session)) -> None:
    session.delete(_require(session, job_id))
    session.commit()


def _require(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job with id {job_id}.")
    return job


def _detail(session: Session, job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source_url": job.source_url,
        "created_at": job.created_at,
        "description": job.description,
        "requirements": job_requirements(session, job),
    }
