"""Dashboard numbers: funnel counts, match quality and what needs doing next."""

from __future__ import annotations

from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.scoring import analyse_job
from app.database import get_session
from app.models import APPLICATION_STATUSES, CLOSED_STATUSES, Application, Job, Resume
from app.schemas import StatsOut

router = APIRouter(prefix="/api/stats", tags=["dashboard"])


@router.get("", response_model=StatsOut, summary="Dashboard metrics")
def get_stats(session: Session = Depends(get_session)) -> dict:
    applications = session.scalars(
        select(Application).options(selectinload(Application.job), selectinload(Application.resume))
    ).all()

    by_status = Counter(application.status for application in applications)
    scores = [a.match_score for a in applications if a.match_score is not None]
    # Anyone who reached interview or beyond, as a share of everyone who applied.
    reached_interview = sum(by_status[s] for s in ("interview", "offer"))
    submitted = sum(count for status_name, count in by_status.items() if status_name != "saved")

    return {
        "total_applications": len(applications),
        "active_applications": sum(
            1 for a in applications if a.status not in CLOSED_STATUSES
        ),
        "resumes": session.scalar(select(func.count()).select_from(Resume)) or 0,
        "jobs": session.scalar(select(func.count()).select_from(Job)) or 0,
        "average_match_score": round(sum(scores) / len(scores), 1) if scores else None,
        "best_match": max(scores) if scores else None,
        "interview_rate": round(100 * reached_interview / submitted, 1) if submitted else None,
        "funnel": [
            {"status": status_name, "count": by_status.get(status_name, 0)}
            for status_name in APPLICATION_STATUSES
        ],
        "upcoming": _upcoming(applications),
        "top_missing_skills": _top_missing_skills(session, applications),
    }


def _upcoming(applications: list[Application]) -> list[dict]:
    """Open next-actions, soonest first, with overdue ones flagged."""
    today = date.today()
    items = [
        {
            "application_id": a.id,
            "job_title": a.job.title if a.job else "",
            "company": a.job.company if a.job else "",
            "next_action": a.next_action or "",
            "next_action_on": a.next_action_on,
            "overdue": bool(a.next_action_on and a.next_action_on < today),
        }
        for a in applications
        if a.next_action and a.status not in CLOSED_STATUSES
    ]
    # Dated actions first (soonest to latest), undated ones after.
    items.sort(key=lambda item: (item["next_action_on"] is None, item["next_action_on"] or today))
    return items[:10]


def _top_missing_skills(session: Session, applications: list[Application]) -> list[dict]:
    """Skills most often required by tracked jobs but absent from the resume used.

    This is the single most useful thing on the dashboard: it turns a pile of
    applications into a ranked list of what to learn or document next.
    """
    counts: Counter[str] = Counter()
    for application in applications:
        job, resume = application.job, application.resume
        if not job or not job.description or not resume:
            continue
        requirements = analyse_job(job.description)
        have = set(resume.skills)
        for skill in requirements.required_skills:
            if skill not in have:
                counts[skill] += 1
    return [{"skill": skill, "count": count} for skill, count in counts.most_common(8)]
