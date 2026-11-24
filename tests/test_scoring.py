"""The matching engine: JD analysis, score composition and advice."""

import pytest

from app.core.scoring import (
    DEFAULT_WEIGHTS,
    TfidfIndex,
    analyse_job,
    match_resume_to_job,
    resume_health,
    tokenize,
    verdict_for,
)
from app.core.parser import parse_resume


# --------------------------------------------------------------------- #
# Tokenising
# --------------------------------------------------------------------- #

def test_tokenizer_keeps_technical_punctuation():
    tokens = tokenize("C++ and CI/CD with Node.js")
    assert "c++" in tokens
    assert "ci/cd" in tokens
    assert "node.js" in tokens


def test_tokenizer_drops_boilerplate_and_bare_numbers():
    tokens = tokenize("The ideal candidate has strong experience and 5 years")
    assert tokens == ["ideal"]


def test_plural_normalisation_does_not_mangle_short_words():
    assert "api" in tokenize("REST APIs")
    assert "css" in tokenize("CSS")


# --------------------------------------------------------------------- #
# TF-IDF
# --------------------------------------------------------------------- #

def test_similarity_is_one_for_identical_text():
    index = TfidfIndex()
    assert index.similarity("python fastapi docker", "python fastapi docker") == pytest.approx(1.0)


def test_similarity_is_zero_for_disjoint_text():
    assert TfidfIndex().similarity("python docker", "accounting payroll") == 0.0


def test_similarity_handles_empty_input():
    assert TfidfIndex().similarity("", "python") == 0.0


def test_small_corpus_falls_back_to_flat_idf():
    index = TfidfIndex(["python developer", "java developer"])
    assert index.document_count == 2
    assert index.idf("python") == 1.0


def test_idf_discounts_terms_every_posting_uses():
    corpus = ["python backend role", "python frontend role", "python data role", "rust systems role"]
    index = TfidfIndex(corpus)
    # "python" is in three of four postings, "rust" in one, so rust must weigh more.
    assert index.idf("rust") > index.idf("python")


# --------------------------------------------------------------------- #
# Job analysis
# --------------------------------------------------------------------- #

def test_required_and_preferred_blocks_are_separated(job_text):
    requirements = analyse_job(job_text)
    assert "Java" in requirements.required_skills
    assert "Spring Boot" in requirements.required_skills
    assert "Kubernetes" in requirements.preferred_skills
    assert "Kubernetes" not in requirements.required_skills


def test_required_skills_outweigh_preferred_ones(job_text):
    weights = analyse_job(job_text).skills
    assert weights["Java"] > weights["Kubernetes"]


def test_required_years_is_the_smallest_figure_named():
    requirements = analyse_job("Requirements\n5+ years experience\nor 2 years experience with Go")
    assert requirements.required_years == 2.0


def test_no_years_named_means_none():
    assert analyse_job("Requirements\nWrite good Python").required_years is None


def test_a_jd_without_headings_still_yields_skills():
    requirements = analyse_job("We want someone who knows Django and Redis well.")
    assert set(requirements.skills) == {"Django", "Redis"}
    assert requirements.required_skills == []


# --------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------- #

def test_a_relevant_resume_scores_above_an_irrelevant_one(resume_text, job_text):
    relevant = match_resume_to_job(resume_text, job_text).overall
    irrelevant = match_resume_to_job(
        "Pastry chef with ten years in patisserie, skilled in laminated dough.", job_text
    ).overall
    assert relevant > irrelevant
    assert irrelevant < 20


def test_identical_text_scores_very_highly():
    result = match_resume_to_job("Python FastAPI Docker PostgreSQL", "Python FastAPI Docker PostgreSQL")
    assert result.overall > 95
    assert result.verdict == "strong"


def test_matched_and_missing_skills_are_disjoint(resume_text, job_text):
    result = match_resume_to_job(resume_text, job_text)
    assert set(result.matched_skills).isdisjoint(result.missing_skills)
    assert "Java" in result.matched_skills
    assert "Mockito" in result.missing_skills


def test_missing_required_is_a_subset_of_missing(resume_text, job_text):
    result = match_resume_to_job(resume_text, job_text)
    assert set(result.missing_required) <= set(result.missing_skills)


def test_missing_skills_are_ordered_by_cost(resume_text, job_text):
    result = match_resume_to_job(resume_text, job_text)
    requirements = analyse_job(job_text)
    weights = [requirements.skills[skill] for skill in result.missing_skills]
    assert weights == sorted(weights, reverse=True)


def test_unscoreable_experience_redistributes_its_weight():
    # No years named in the JD, so experience drops out of the blend entirely.
    result = match_resume_to_job("Python developer", "Requirements\nPython")
    assert result.experience_score is None
    assert "experience" not in result.weights_used
    assert sum(result.weights_used.values()) == pytest.approx(1.0, abs=0.01)


def test_experience_gap_lowers_the_score_but_does_not_zero_it():
    jd = "Requirements\n6 years experience with Python and Django"
    result = match_resume_to_job("Python and Django developer", jd, candidate_years=0)
    assert result.experience_score == 0.0
    assert result.overall > 0  # skills still carry their share


def test_exceeding_the_required_years_is_capped_at_full_marks():
    jd = "Requirements\n2 years experience with Python"
    result = match_resume_to_job("Python developer", jd, candidate_years=20)
    assert result.experience_score == 100.0


def test_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_scores_stay_inside_the_scale(resume_text, job_text):
    result = match_resume_to_job(resume_text, job_text)
    for value in (result.overall, result.skill_score, result.keyword_score, result.experience_score):
        if value is not None:
            assert 0.0 <= value <= 100.0


@pytest.mark.parametrize(
    "score,expected",
    [(95, "strong"), (80, "strong"), (70, "good"), (65, "good"), (50, "fair"), (45, "fair"), (10, "weak")],
)
def test_verdict_bands(score, expected):
    assert verdict_for(score) == expected


def test_empty_inputs_do_not_raise():
    result = match_resume_to_job("", "")
    assert result.overall == 0.0
    assert result.verdict == "weak"


# --------------------------------------------------------------------- #
# Advice
# --------------------------------------------------------------------- #

def test_suggestions_name_the_missing_required_skills(resume_text, job_text):
    suggestions = " ".join(match_resume_to_job(resume_text, job_text).suggestions)
    assert "Mockito" in suggestions
    assert "2 years" in suggestions


def test_a_perfect_match_says_there_is_nothing_to_fix():
    result = match_resume_to_job("Python FastAPI Docker", "Required skills\nPython FastAPI Docker")
    assert "no gaps" in " ".join(result.suggestions).lower()


def test_one_off_jd_terms_are_not_reported_as_missing_keywords():
    # "Zyxcorp" appears once, so it is a company name rather than a theme.
    jd = "Required skills\nZyxcorp needs Python. Python work is Python heavy."
    result = match_resume_to_job("Java developer", jd)
    assert "zyxcorp" not in result.missing_keywords


def test_resume_health_flags_a_thin_resume():
    parsed = parse_resume("Jane Doe\nI know python.")
    failures = {check.label for check in resume_health(parsed, "Jane Doe\nI know python.") if not check.passed}
    assert "Length" in failures
    assert "Contact details" in failures


def test_resume_health_passes_a_complete_resume(resume_text):
    parsed = parse_resume(resume_text)
    passed = {check.label for check in resume_health(parsed, resume_text) if check.passed}
    assert {"Contact details", "Professional links", "Standard sections"} <= passed
