"""End-to-end API tests against a throwaway database."""

import io

import pytest


# --------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------- #

def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_index_serves_the_app(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Smart Resume Tracker" in response.text


def test_openapi_schema_is_valid(client):
    schema = client.get("/openapi.json").json()
    assert "/api/match" in schema["paths"]


# --------------------------------------------------------------------- #
# Resumes
# --------------------------------------------------------------------- #

def test_create_and_list_resume(client, resume_text):
    created = client.post(
        "/api/resumes", json={"label": "Backend", "raw_text": resume_text}
    ).json()
    assert created["parsed"]["email"] == "sravani.deepthi@example.com"
    assert "Spring Boot" in created["skills"]
    assert any(check["label"] == "Contact details" for check in created["health"])

    listed = client.get("/api/resumes").json()
    assert [r["id"] for r in listed] == [created["id"]]


def test_short_resume_text_is_rejected(client):
    response = client.post("/api/resumes", json={"label": "x", "raw_text": "too short"})
    assert response.status_code == 422


def test_upload_a_text_resume(client, resume_text):
    response = client.post(
        "/api/resumes/upload",
        files={"file": ("cv.txt", resume_text.encode(), "text/plain")},
        data={"label": "Uploaded", "is_primary": "true"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["is_primary"] is True
    assert body["filename"] == "cv.txt"
    assert body["experience_years"] > 0


def test_upload_rejects_an_unsupported_type(client):
    response = client.post(
        "/api/resumes/upload", files={"file": ("cv.pages", b"x" * 500, "application/octet-stream")}
    )
    assert response.status_code == 415


def test_upload_rejects_an_empty_file(client):
    response = client.post("/api/resumes/upload", files={"file": ("cv.txt", b"", "text/plain")})
    assert response.status_code == 400


def test_upload_rejects_a_file_with_almost_no_text(client):
    # Stands in for a scanned PDF: a valid file that yields nothing useful.
    response = client.post("/api/resumes/upload", files={"file": ("cv.txt", b"Jane Doe", "text/plain")})
    assert response.status_code == 422
    assert "scanned image" in response.json()["detail"]


def test_upload_rejects_an_oversized_file(client):
    big = b"word " * 1_200_000  # ~6 MB, over the 5 MB default
    response = client.post("/api/resumes/upload", files={"file": ("cv.txt", big, "text/plain")})
    assert response.status_code == 413


def test_only_one_resume_is_primary(client, resume_text):
    first = client.post(
        "/api/resumes", json={"label": "A", "raw_text": resume_text, "is_primary": True}
    ).json()
    second = client.post(
        "/api/resumes", json={"label": "B", "raw_text": resume_text, "is_primary": True}
    ).json()

    by_id = {r["id"]: r for r in client.get("/api/resumes").json()}
    assert by_id[second["id"]]["is_primary"] is True
    assert by_id[first["id"]]["is_primary"] is False

    client.post(f"/api/resumes/{first['id']}/primary")
    by_id = {r["id"]: r for r in client.get("/api/resumes").json()}
    assert by_id[first["id"]]["is_primary"] is True
    assert by_id[second["id"]]["is_primary"] is False


def test_missing_resume_is_404(client):
    assert client.get("/api/resumes/999").status_code == 404


def test_delete_resume(client, saved_resume):
    assert client.delete(f"/api/resumes/{saved_resume['id']}").status_code == 204
    assert client.get("/api/resumes").json() == []


# --------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------- #

def test_job_requirements_are_analysed(client, saved_job):
    job = client.get(f"/api/jobs/{saved_job['id']}").json()
    requirements = job["requirements"]
    assert "Java" in requirements["required_skills"]
    assert "Kubernetes" in requirements["preferred_skills"]
    assert requirements["required_years"] == 2.0


def test_update_job(client, saved_job):
    updated = client.patch(f"/api/jobs/{saved_job['id']}", json={"location": "Bengaluru"}).json()
    assert updated["location"] == "Bengaluru"
    assert updated["title"] == saved_job["title"]  # untouched fields survive


def test_job_requires_a_title(client):
    assert client.post("/api/jobs", json={"company": "Acme"}).status_code == 422


def test_deleting_a_job_removes_its_applications(client, saved_job, saved_resume):
    client.post(
        "/api/applications", json={"job_id": saved_job["id"], "resume_id": saved_resume["id"]}
    )
    assert len(client.get("/api/applications").json()) == 1
    client.delete(f"/api/jobs/{saved_job['id']}")
    assert client.get("/api/applications").json() == []


# --------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------- #

def test_application_caches_its_match_score(client, saved_job, saved_resume):
    created = client.post(
        "/api/applications",
        json={
            "job_id": saved_job["id"],
            "resume_id": saved_resume["id"],
            "status": "applied",
            "applied_on": "2026-11-20",
            "next_action": "Follow up",
            "next_action_on": "2026-11-28",
        },
    ).json()
    assert created["match_score"] > 0
    assert created["job_title"] == "Java Backend Engineer"
    assert created["resume_label"] == "Backend - Java focus"


def test_application_without_a_resume_has_no_score(client, saved_job):
    created = client.post("/api/applications", json={"job_id": saved_job["id"]}).json()
    assert created["match_score"] is None


def test_attaching_a_resume_later_scores_it(client, saved_job, saved_resume):
    created = client.post("/api/applications", json={"job_id": saved_job["id"]}).json()
    updated = client.patch(
        f"/api/applications/{created['id']}", json={"resume_id": saved_resume["id"]}
    ).json()
    assert updated["match_score"] > 0


def test_status_transition(client, saved_job, saved_resume):
    created = client.post(
        "/api/applications", json={"job_id": saved_job["id"], "resume_id": saved_resume["id"]}
    ).json()
    updated = client.patch(f"/api/applications/{created['id']}", json={"status": "interview"}).json()
    assert updated["status"] == "interview"


def test_unknown_status_is_rejected(client, saved_job):
    created = client.post("/api/applications", json={"job_id": saved_job["id"]}).json()
    assert client.patch(f"/api/applications/{created['id']}", json={"status": "ghosted"}).status_code == 422


def test_filter_applications_by_status(client, saved_job, saved_resume):
    client.post("/api/applications", json={"job_id": saved_job["id"], "status": "applied"})
    client.post("/api/applications", json={"job_id": saved_job["id"], "status": "offer"})
    assert len(client.get("/api/applications?status=offer").json()) == 1
    assert client.get("/api/applications?status=nonsense").status_code == 400


def test_application_needs_an_existing_job(client):
    assert client.post("/api/applications", json={"job_id": 404}).status_code == 404


def test_application_rejects_an_unknown_resume(client, saved_job):
    response = client.post(
        "/api/applications", json={"job_id": saved_job["id"], "resume_id": 777}
    )
    assert response.status_code == 404


# --------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------- #

def test_match_by_ids(client, saved_job, saved_resume):
    result = client.post(
        "/api/match", json={"resume_id": saved_resume["id"], "job_id": saved_job["id"]}
    ).json()
    assert 0 < result["overall"] <= 100
    assert "Java" in result["matched_skills"]
    assert result["suggestions"]


def test_match_with_pasted_text(client, saved_resume):
    result = client.post(
        "/api/match",
        json={
            "resume_id": saved_resume["id"],
            "job_description": "Required skills\nPython, FastAPI and Docker. 1 year experience.",
        },
    ).json()
    assert "FastAPI" in result["matched_skills"]


def test_match_with_no_resume_is_400(client, saved_job):
    assert client.post("/api/match", json={"job_id": saved_job["id"]}).status_code == 400


def test_match_with_no_job_is_400(client, saved_resume):
    assert client.post("/api/match", json={"resume_id": saved_resume["id"]}).status_code == 400


def test_match_with_unknown_ids_is_404(client):
    assert client.post("/api/match", json={"resume_id": 1, "job_id": 1}).status_code == 404


# --------------------------------------------------------------------- #
# Screening
# --------------------------------------------------------------------- #

def _resume_file(name: str, body: str) -> tuple:
    return ("files", (name, io.BytesIO(body.encode()), "text/plain"))


STRONG = """Rahul Verma
rahul@example.com | +91 90000 11111
EXPERIENCE
Backend Engineer, Acme. Jan 2021 - Present
- Java and Spring Boot microservices with Hibernate against PostgreSQL.
- Docker and Kubernetes on AWS, JUnit and Mockito for unit testing.
SKILLS
Java, Spring Boot, Hibernate, REST API, SQL, PostgreSQL, MySQL, AWS, Docker, JUnit, Mockito, Kafka
"""

WEAK = """Meera Nair
meera@example.com | +91 90000 22222
EXPERIENCE
Graphic Designer, Studio Ten. Jan 2022 - Present
- Brand identity, print layout and illustration for retail clients.
SKILLS
Photoshop, Illustrator, InDesign, typography, colour theory
"""


def test_screening_ranks_the_stronger_candidate_first(client, saved_job):
    response = client.post(
        "/api/screening/runs",
        data={"job_id": str(saved_job["id"])},
        files=[_resume_file("weak.txt", WEAK), _resume_file("strong.txt", STRONG)],
    )
    assert response.status_code == 201
    run = response.json()
    assert run["candidate_count"] == 2
    assert [c["rank"] for c in run["candidates"]] == [1, 2]
    assert run["candidates"][0]["filename"] == "strong.txt"
    assert run["candidates"][0]["score"] > run["candidates"][1]["score"]
    assert run["candidates"][0]["candidate_name"] == "Rahul Verma"
    assert "Spring Boot" in run["candidates"][0]["matched_skills"]


def test_screening_run_can_be_fetched_and_listed(client, saved_job):
    run = client.post(
        "/api/screening/runs",
        data={"job_id": str(saved_job["id"])},
        files=[_resume_file("strong.txt", STRONG)],
    ).json()

    assert client.get(f"/api/screening/runs/{run['id']}").json()["candidates"][0]["rank"] == 1
    listed = client.get("/api/screening/runs").json()
    assert listed[0]["candidate_count"] == 1
    assert listed[0]["candidates"] == []  # omitted from the list view


def test_screening_skips_unreadable_files_but_keeps_the_rest(client, saved_job):
    run = client.post(
        "/api/screening/runs",
        data={"job_id": str(saved_job["id"])},
        files=[
            _resume_file("strong.txt", STRONG),
            _resume_file("bad.pages", "unsupported type"),
            _resume_file("tiny.txt", "Hi"),
        ],
    ).json()
    assert run["candidate_count"] == 1


def test_screening_with_nothing_readable_is_422(client, saved_job):
    response = client.post(
        "/api/screening/runs",
        data={"job_id": str(saved_job["id"])},
        files=[_resume_file("tiny.txt", "Hi")],
    )
    assert response.status_code == 422


def test_screening_needs_a_job_description(client):
    job = client.post("/api/jobs", json={"title": "Role", "company": "Acme"}).json()
    response = client.post(
        "/api/screening/runs",
        data={"job_id": str(job["id"])},
        files=[_resume_file("strong.txt", STRONG)],
    )
    assert response.status_code == 422


def test_screening_needs_an_existing_job(client):
    response = client.post(
        "/api/screening/runs", data={"job_id": "999"}, files=[_resume_file("a.txt", STRONG)]
    )
    assert response.status_code == 404


def test_delete_screening_run(client, saved_job):
    run = client.post(
        "/api/screening/runs",
        data={"job_id": str(saved_job["id"])},
        files=[_resume_file("strong.txt", STRONG)],
    ).json()
    assert client.delete(f"/api/screening/runs/{run['id']}").status_code == 204
    assert client.get("/api/screening/runs").json() == []


# --------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------- #

def test_stats_on_an_empty_database(client):
    stats = client.get("/api/stats").json()
    assert stats["total_applications"] == 0
    assert stats["average_match_score"] is None
    assert stats["interview_rate"] is None
    assert [stage["status"] for stage in stats["funnel"]][:2] == ["saved", "applied"]


def test_stats_aggregate_the_funnel(client, saved_job, saved_resume):
    for status in ("applied", "interview", "rejected"):
        client.post(
            "/api/applications",
            json={"job_id": saved_job["id"], "resume_id": saved_resume["id"], "status": status},
        )
    stats = client.get("/api/stats").json()
    funnel = {stage["status"]: stage["count"] for stage in stats["funnel"]}

    assert stats["total_applications"] == 3
    assert stats["active_applications"] == 2  # rejected is closed
    assert funnel["interview"] == 1
    assert stats["average_match_score"] > 0
    # One of three submitted applications reached interview.
    assert stats["interview_rate"] == pytest.approx(33.3, abs=0.1)


def test_stats_surface_recurring_skill_gaps(client, saved_job, saved_resume):
    client.post(
        "/api/applications",
        json={"job_id": saved_job["id"], "resume_id": saved_resume["id"], "status": "applied"},
    )
    gaps = {row["skill"] for row in client.get("/api/stats").json()["top_missing_skills"]}
    assert "Mockito" in gaps


def test_upcoming_actions_flag_overdue_items(client, saved_job):
    client.post(
        "/api/applications",
        json={"job_id": saved_job["id"], "status": "applied",
              "next_action": "Chase recruiter", "next_action_on": "2020-01-01"},
    )
    upcoming = client.get("/api/stats").json()["upcoming"]
    assert upcoming[0]["next_action"] == "Chase recruiter"
    assert upcoming[0]["overdue"] is True


def test_upload_a_pdf_resume(client, resume_pdf_bytes):
    response = client.post(
        "/api/resumes/upload",
        files={"file": ("sample_resume.pdf", resume_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["parsed"]["name"] == "Gadi Sravani Deepthi"
    assert "Spring Boot" in body["skills"]


def test_upload_a_corrupt_pdf_is_400(client):
    response = client.post(
        "/api/resumes/upload",
        files={"file": ("broken.pdf", b"%PDF-1.4 " + b"x" * 400, "application/pdf")},
    )
    assert response.status_code == 400
