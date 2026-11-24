"""Skill taxonomy: the boundary cases that break naive substring matching."""

from app.core.skills import all_skills, categories_for, category_of, extract_skills, skill_counts


def test_taxonomy_is_populated():
    skills = all_skills()
    assert len(skills) > 100
    assert skills == sorted(skills)
    assert all(category_of(skill) for skill in skills)


def test_aliases_resolve_to_canonical_names():
    assert "JavaScript" in extract_skills("strong js developer")
    assert "Kubernetes" in extract_skills("ran k8s in production")
    assert "PostgreSQL" in extract_skills("tuned postgres queries")
    assert "Spring Boot" in extract_skills("built springboot services")


def test_java_is_not_found_inside_javascript():
    assert extract_skills("JavaScript only") == ["JavaScript"]
    assert "Java" not in extract_skills("JavaScript only")


def test_sql_is_not_found_inside_mysql():
    found = extract_skills("MySQL administration")
    assert "MySQL" in found
    assert "SQL" not in found


def test_short_names_need_word_boundaries():
    assert extract_skills("I am going to the shop") == []
    assert "Go" in extract_skills("services written in Go")


def test_punctuation_at_a_sentence_end_still_matches():
    found = extract_skills("Deployed on AWS. Also wrote C++.")
    assert "AWS" in found
    assert "C++" in found


def test_longer_match_shadows_the_shorter_one():
    # "Spring Boot" should not also register as a bare "Spring" mention.
    assert extract_skills("We use Spring Boot") == ["Spring Boot"]


def test_a_space_in_an_alias_also_matches_a_hyphen():
    # Resumes write "unit-test coverage" as often as "unit testing".
    assert "Unit Testing" in extract_skills("raised unit-test coverage to 85 percent")
    assert "Machine Learning" in extract_skills("machine-learning pipelines")
    assert "Spring Boot" in extract_skills("spring-boot services")


def test_counts_are_case_insensitive():
    assert skill_counts("Python python PYTHON")["Python"] == 3


def test_categories_group_by_taxonomy_section():
    grouped = categories_for(["Python", "Docker", "MySQL"])
    assert grouped["languages"] == ["Python"]
    assert grouped["cloud_devops"] == ["Docker"]
    assert grouped["databases"] == ["MySQL"]
