"""Resume parsing: extraction, contact fields, sections and experience maths."""

from datetime import date

import pytest

from app.core.parser import (
    UnsupportedFileType,
    estimate_experience_years,
    extract_text,
    guess_name,
    normalise_whitespace,
    parse_resume,
    split_sections,
)


def test_plain_text_round_trips():
    assert extract_text(b"Hello  world", "cv.txt") == "Hello world"


def test_unsupported_extension_is_rejected():
    with pytest.raises(UnsupportedFileType):
        extract_text(b"data", "resume.pages")


def test_docx_text_and_tables_are_extracted(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Asha Rao")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Languages"
    table.rows[0].cells[1].text = "Python, Go"
    path = tmp_path / "cv.docx"
    document.save(path)

    text = extract_text(path.read_bytes(), "cv.docx")
    assert "Asha Rao" in text
    # Skills very often live in a table, so those cells must come through.
    assert "Python, Go" in text


def test_whitespace_normalisation_turns_bullets_into_lines():
    assert normalise_whitespace("a•b") == "a\n- b"
    assert normalise_whitespace("x\n\n\n\ny") == "x\n\ny"


def test_contact_fields(resume_text):
    parsed = parse_resume(resume_text)
    assert parsed.email == "sravani.deepthi@example.com"
    assert parsed.phone == "+91 98765 43210"
    assert parsed.github.endswith("/Sravani-Deepthi-Gadi")
    assert parsed.linkedin.startswith("https://linkedin.com/in/")


def test_name_is_the_first_plausible_line(resume_text):
    assert parse_resume(resume_text).name == "Gadi Sravani Deepthi"


def test_name_skips_contact_lines():
    assert guess_name("a@b.com\n+91 98765 43210\nPriya Menon") == "Priya Menon"


def test_sections_are_sliced(resume_text):
    sections = split_sections(resume_text)
    assert {"summary", "education", "experience", "skills", "projects"} <= set(sections)
    assert "Spring Boot" in sections["experience"]


def test_repeated_headings_append_rather_than_overwrite():
    text = "PROJECTS\nalpha\nEDUCATION\nb.tech\nPROJECTS\nbeta"
    assert "alpha" in split_sections(text)["projects"]
    assert "beta" in split_sections(text)["projects"]


def test_degrees_are_detected(resume_text):
    assert "B.Tech" in parse_resume(resume_text).degrees


def test_phone_is_not_confused_with_a_year_range():
    assert parse_resume("B.Tech 2022 - 2026\nAmrita").phone is None


def test_experience_from_a_month_range():
    years = estimate_experience_years("Mar 2026 - Jul 2026", today=date(2026, 11, 24))
    assert years == pytest.approx(0.4, abs=0.05)


def test_experience_counts_present_up_to_today():
    # Months are counted inclusively, the way people describe resume durations:
    # Jan 2024 through Jan 2026 is 25 months worked, not 24 elapsed.
    years = estimate_experience_years("Jan 2024 - Present", today=date(2026, 1, 1))
    assert years == pytest.approx(2.1, abs=0.05)


def test_overlapping_roles_are_not_double_counted():
    # Two concurrent 2023 roles are still one year of experience, not two.
    text = "Role A Jan 2023 - Dec 2023\nRole B Jun 2023 - Dec 2023"
    assert estimate_experience_years(text, today=date(2026, 1, 1)) == pytest.approx(1.0, abs=0.05)


def test_stated_years_are_the_fallback():
    assert estimate_experience_years("3+ years of professional experience") == 3.0


def test_no_dates_and_no_claim_means_zero():
    assert estimate_experience_years("Enthusiastic fresher") == 0.0


# --------------------------------------------------------------------- #
# PDF (uses the committed samples/sample_resume.pdf fixture)
# --------------------------------------------------------------------- #

def test_pdf_text_is_extracted(resume_pdf_bytes):
    text = extract_text(resume_pdf_bytes, "sample_resume.pdf")
    assert "Gadi Sravani Deepthi" in text
    assert "Spring Boot" in text


def test_pdf_parses_to_the_same_fields_as_the_text_version(resume_pdf_bytes, resume_text):
    from_pdf = parse_resume(extract_text(resume_pdf_bytes, "sample_resume.pdf"))
    from_text = parse_resume(resume_text)
    assert from_pdf.email == from_text.email
    assert from_pdf.phone == from_text.phone
    assert from_pdf.name == from_text.name
    assert set(from_pdf.skills) == set(from_text.skills)


def test_a_corrupt_pdf_raises_rather_than_returning_junk(resume_pdf_bytes):
    with pytest.raises(Exception):
        extract_text(b"%PDF-1.4 not really a pdf", "broken.pdf")
