"""Applications: the tracker's funnel - which resume went to which job, and where it stands."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_session
from app.models import APPLICATION_STATUSES, Application, Job, Resume
from app.schemas import ApplicationCreate, ApplicationOut, ApplicationUpdate
from app.services import application_payload, refresh_application_score

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationOut], summary="List applications")
def list_applications(
    status_filter: str | None = Query(default=None, alias="status",
                                     description="Filter to one funnel stage"),
    session: Session = Depends(get_session),
) -> list[dict]:
    if status_filter and status_filter not in APPLICATION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown status {status_filter!r}. Expected one of {', '.join(APPLICATION_STATUSES)}.",
        )
    query = (
        select(Application)
        .options(selectinload(Application.job), selectinload(Application.resume))
        .order_by(Application.updated_at.desc())
    )
    if status_filter:
        query = query.where(Application.status == status_filter)
    return [application_payload(a) for a in session.scalars(query).all()]


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED,
             summary="Track a new application")
def create_application(payload: ApplicationCreate, session: Session = Depends(get_session)) -> dict:
    if session.get(Job, payload.job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job with id {payload.job_id}.")
    if payload.resume_id is not None and session.get(Resume, payload.resume_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No resume with id {payload.resume_id}.")

    application = Application(**payload.model_dump())
    session.add(application)
    session.flush()
    refresh_application_score(session, application)
    session.commit()
    session.refresh(application)
    return application_payload(application)


@router.get("/{application_id}", response_model=ApplicationOut, summary="One application")
def get_application(application_id: int, session: Session = Depends(get_session)) -> dict:
    return application_payload(_require(session, application_id))


@router.patch("/{application_id}", response_model=ApplicationOut,
              summary="Update status, notes or next action")
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    session: Session = Depends(get_session),
) -> dict:
    application = _require(session, application_id)
    changes = payload.model_dump(exclude_unset=True)

    if "resume_id" in changes and changes["resume_id"] is not None:
        if session.get(Resume, changes["resume_id"]) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No resume with id {changes['resume_id']}.")

    for field_name, value in changes.items():
        setattr(application, field_name, value)

    # The score depends on the resume, so only recompute when that changed.
    if "resume_id" in changes:
        session.flush()
        refresh_application_score(session, application)

    session.commit()
    session.refresh(application)
    return application_payload(application)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
               summary="Stop tracking an application")
def delete_application(application_id: int, session: Session = Depends(get_session)) -> None:
    session.delete(_require(session, application_id))
    session.commit()


def _require(session: Session, application_id: int) -> Application:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No application with id {application_id}.")
    return application
