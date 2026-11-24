"""Populate the database with demo data, so a fresh clone has something to show.

    python scripts/seed_demo.py          # add demo rows
    python scripts/seed_demo.py --reset  # wipe every table first

The resume text is fictional. Nothing here is required to run the app.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.parser import parse_resume  # noqa: E402
from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import Application, Job, Resume  # noqa: E402
from app.services import refresh_application_score  # noqa: E402

RESUME_BACKEND = """Asha Rao
Hyderabad, India | +91 90000 12345 | asha.rao@example.com
linkedin.com/in/asha-rao | github.com/asha-rao

SUMMARY
Backend engineer with two years building REST services in Java and Python.

EXPERIENCE
Software Engineer, Northwind Systems, Hyderabad
Jan 2024 - Present
- Built Spring Boot microservices backed by PostgreSQL, cutting p95 latency by 40 percent.
- Containerised six services with Docker and deployed them to AWS via Jenkins.
- Raised unit-test coverage from 48 percent to 86 percent with JUnit and Mockito.

EDUCATION
B.Tech, Information Technology - Osmania University (2019 - 2023)

TECHNICAL SKILLS
Languages: Java, Python, SQL
Backend: Spring Boot, Hibernate, REST API, Microservices
Databases: PostgreSQL, MySQL, Redis
Cloud: AWS, Docker, Jenkins, Git, Linux
Testing: JUnit, Mockito, pytest
"""

RESUME_DATA = """Asha Rao
Hyderabad, India | +91 90000 12345 | asha.rao@example.com
github.com/asha-rao

SUMMARY
Python developer moving into data engineering, with ETL and analytics work.

EXPERIENCE
Software Engineer, Northwind Systems, Hyderabad
Jan 2024 - Present
- Built Airflow pipelines moving 20 million rows a day into Snowflake.
- Wrote Pandas and NumPy transformations covering 12 reporting datasets.

EDUCATION
B.Tech, Information Technology - Osmania University (2019 - 2023)

TECHNICAL SKILLS
Languages: Python, SQL
Data: Pandas, NumPy, Airflow, ETL, Apache Spark, Snowflake
Cloud: AWS, Docker, Linux, Git
"""

JOBS = [
    {
        "title": "Java Backend Engineer",
        "company": "QualiZeal",
        "location": "Hyderabad",
        "description": """Required skills
- 2+ years of professional experience building backend services in Java
- Strong Spring Boot and Hibernate, with solid REST API design
- Hands-on SQL with MySQL or PostgreSQL
- Deploying to AWS and containerising with Docker
- Unit testing with JUnit and Mockito

Nice to have
- Kubernetes in production
- Apache Kafka for event-driven workflows
- Terraform for infrastructure as code
""",
    },
    {
        "title": "Full Stack Developer",
        "company": "Aganitha",
        "location": "Hyderabad",
        "description": """What we are looking for
- 1+ years with Python and FastAPI or Django on the backend
- React and TypeScript on the front end
- PostgreSQL and REST API design
- Docker, Git and CI/CD discipline

Good to have
- Kubernetes, GraphQL
- Exposure to machine learning workflows
""",
    },
    {
        "title": "Data Engineer",
        "company": "Brightfield Analytics",
        "location": "Bengaluru (hybrid)",
        "description": """Minimum qualifications
- 3 years of experience with Python and SQL
- Building ETL pipelines with Airflow
- Apache Spark at scale, and a cloud warehouse such as Snowflake
- Docker and AWS

Preferred qualifications
- Kafka streaming
- Terraform, Kubernetes
""",
    },
    {
        "title": "Site Reliability Engineer",
        "company": "Helix Cloud",
        "location": "Remote (India)",
        "description": """Requirements
- 2+ years of experience operating Linux systems in production
- Kubernetes, Docker and Terraform
- Prometheus and Grafana for observability
- Python or Go for automation
- CI/CD with Jenkins or GitHub Actions

Nice to have
- Google Cloud, Kafka
""",
    },
]

TODAY = date.today()
APPLICATIONS = [
    # (job index, resume key, status, applied days ago, next action, due in days)
    (0, "backend", "interview", 18, "Prepare system design round", 3),
    (1, "backend", "applied", 9, "Follow up with the recruiter", -2),
    (2, "data", "screening", 6, "Send the take-home exercise", 5),
    (3, "backend", "rejected", 30, None, None),
    (1, "data", "saved", None, "Tailor the resume for this one", 1),
]


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(bind=engine)
    init_db()

    with SessionLocal() as session:
        if session.query(Job).count() or session.query(Resume).count():
            print("Database already has data. Re-run with --reset to replace it.")
            return

        resumes = {}
        for key, label, text, primary in (
            ("backend", "Backend - Java focus", RESUME_BACKEND, True),
            ("data", "Data engineering - Python focus", RESUME_DATA, False),
        ):
            resume = Resume(
                label=label,
                filename=None,
                raw_text=text,
                parsed_json=json.dumps(parse_resume(text).to_dict()),
                is_primary=primary,
            )
            session.add(resume)
            resumes[key] = resume

        jobs = [Job(**payload) for payload in JOBS]
        session.add_all(jobs)
        session.flush()

        for job_index, resume_key, status, applied_ago, action, due_in in APPLICATIONS:
            application = Application(
                job_id=jobs[job_index].id,
                resume_id=resumes[resume_key].id,
                status=status,
                applied_on=TODAY - timedelta(days=applied_ago) if applied_ago is not None else None,
                next_action=action,
                next_action_on=TODAY + timedelta(days=due_in) if due_in is not None else None,
            )
            session.add(application)
            session.flush()
            refresh_application_score(session, application)

        session.commit()
        print(f"Seeded {len(resumes)} resumes, {len(jobs)} jobs, {len(APPLICATIONS)} applications.")
        print("Start the app with: uvicorn app.main:app --reload")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop every table before seeding")
    seed(reset=parser.parse_args().reset)
