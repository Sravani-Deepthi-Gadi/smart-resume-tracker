"""Resume library: upload, paste, inspect and delete resume versions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.parser import SUPPORTED_EXTENSIONS, UnsupportedFileType, extract_text
from app.database import get_session
from app.models import Resume
from app.schemas import ResumeCreate, ResumeDetail, ResumeSummary
from app.services import health_payload, resume_payload, store_parsed

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.get("", response_model=list[ResumeSummary], summary="List resume versions")
def list_resumes(session: Session = Depends(get_session)) -> list[dict]:
    resumes = session.scalars(
        select(Resume).order_by(Resume.is_primary.desc(), Resume.created_at.desc())
    ).all()
    return [resume_payload(r) for r in resumes]


@router.post("", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED,
             summary="Add a resume from pasted text")
def create_resume(payload: ResumeCreate, session: Session = Depends(get_session)) -> dict:
    resume = Resume(label=payload.label, raw_text=payload.raw_text)
    store_parsed(resume, payload.raw_text)
    session.add(resume)
    if payload.is_primary:
        session.flush()
        _set_primary(session, resume)
    session.commit()
    session.refresh(resume)
    return _detail(resume)


@router.post("/upload", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED,
             summary="Upload a PDF, DOCX or TXT resume")
async def upload_resume(
    file: UploadFile = File(..., description="PDF, DOCX or TXT resume"),
    label: str | None = Form(default=None, description="Defaults to the filename"),
    is_primary: bool = Form(default=False),
    session: Session = Depends(get_session),
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"{file.filename} is larger than the {limit_mb} MB limit.",
        )
    try:
        text = extract_text(data, file.filename or "resume.txt")
    except UnsupportedFileType:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type. Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    except Exception as exc:  # a corrupt PDF should be a 400, not a 500
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not read {file.filename}: {exc}")

    if len(text.split()) < 20:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Almost no text could be extracted - the file may be a scanned image. "
            "Paste the text instead, or upload a text-based PDF.",
        )

    resume = Resume(
        label=label or (file.filename or "Resume").rsplit(".", 1)[0],
        filename=file.filename,
        raw_text=text,
    )
    store_parsed(resume, text)
    session.add(resume)
    if is_primary:
        session.flush()
        _set_primary(session, resume)
    session.commit()
    session.refresh(resume)
    return _detail(resume)


@router.get("/{resume_id}", response_model=ResumeDetail, summary="One resume with parsed fields")
def get_resume(resume_id: int, session: Session = Depends(get_session)) -> dict:
    return _detail(_require(session, resume_id))


@router.post("/{resume_id}/primary", response_model=ResumeSummary,
             summary="Mark a resume as the default")
def make_primary(resume_id: int, session: Session = Depends(get_session)) -> dict:
    resume = _require(session, resume_id)
    _set_primary(session, resume)
    session.commit()
    session.refresh(resume)
    return resume_payload(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Delete a resume")
def delete_resume(resume_id: int, session: Session = Depends(get_session)) -> None:
    session.delete(_require(session, resume_id))
    session.commit()


def _require(session: Session, resume_id: int) -> Resume:
    resume = session.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No resume with id {resume_id}.")
    return resume


def _set_primary(session: Session, resume: Resume) -> None:
    """Exactly one resume is primary at a time."""
    for other in session.scalars(select(Resume).where(Resume.is_primary.is_(True))).all():
        other.is_primary = False
    resume.is_primary = True


def _detail(resume: Resume) -> dict:
    return {
        **resume_payload(resume),
        "raw_text": resume.raw_text,
        "parsed": resume.parsed,
        "health": health_payload(resume),
    }
