"""The matching engine: how well does a resume answer a job description?

The score is a weighted blend of three signals, each reported separately so a
number is never a black box:

================  ======  ====================================================
Signal            Weight  What it measures
================  ======  ====================================================
Skill coverage      0.55  Share of the JD's skills the resume evidences, with
                          skills in a "required" block counted roughly 3x the
                          ones in a "nice to have" block.
Keyword similarity  0.30  Cosine similarity of TF-IDF vectors over the whole
                          documents - catches domain language the taxonomy
                          does not list.
Experience fit      0.15  Candidate years against years the JD asks for.
================  ======  ====================================================

Any signal the inputs cannot support (a JD that names no skills, or states no
required years) drops out and its weight is redistributed across the rest, so
an unscoreable component never silently reads as a zero.

Everything is implemented in the standard library: no scikit-learn, no model
download, and the same inputs always produce the same score.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field, asdict

from app.core.skills import extract_skills, skill_counts, category_of

# ---------------------------------------------------------------------------
# Weights and tunables
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {"skills": 0.55, "keywords": 0.30, "experience": 0.15}

REQUIRED_WEIGHT = 3.0     # skill named under "must have" / "required"
NEUTRAL_WEIGHT = 1.5      # skill named in the body of the JD
PREFERRED_WEIGHT = 1.0    # skill named under "nice to have" / "preferred"

# Headings that open a block of hard requirements, and one of soft ones.
REQUIRED_HEADING_RE = re.compile(
    r"^\W*(?:required|requirements|must[- ]haves?|must have|minimum (?:qualifications|requirements)|"
    r"basic qualifications|essential|mandatory|what we(?:'re| are) looking for|who you are|"
    r"key skills|required skills|qualifications)\b",
    re.I | re.M,
)
PREFERRED_HEADING_RE = re.compile(
    r"^\W*(?:preferred|preferred (?:qualifications|skills)|nice[- ]to[- ]have|nice to haves?|"
    r"good[- ]to[- ]have|bonus|plus(?:es)?|desirable|added advantage|optional|"
    r"it would be (?:great|nice)|extra credit)\b",
    re.I | re.M,
)

REQUIRED_YEARS_RE = re.compile(
    r"(?:(?P<min>minimum|min\.?|at least|atleast)\s*)?"
    r"(?P<years>\d{1,2}(?:\.\d)?)\s*\+?\s*(?:-|–|to)?\s*\d{0,2}\s*"
    r"(?:years?|yrs?)\s*(?:of\s*)?"
    r"(?:relevant\s*|professional\s*|hands[- ]on\s*|industry\s*|total\s*|work\s*)?"
    r"experience",
    re.I,
)

# Common English plus resume/JD boilerplate that carries no signal.
STOPWORDS = {
    "a", "about", "above", "across", "after", "all", "also", "an", "and", "any", "are", "as", "at",
    "be", "been", "being", "both", "but", "by", "can", "closely", "come", "could", "d", "did", "do",
    "does", "doing", "done", "due", "during", "each", "end", "etc", "even", "every", "for", "from", "further",
    "get", "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how", "i", "if",
    "in", "inside", "into", "is", "it", "its", "just", "ll", "may", "me", "might", "more", "most",
    "much", "must", "my", "no", "nor", "not", "of", "off", "on", "once", "one", "only", "or", "other",
    "our", "ours", "out", "over", "own", "per", "re", "s", "same", "she", "should", "so", "some",
    "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "up", "upon", "us", "use", "used", "using", "ve", "very", "was",
    "we", "well", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will",
    "with", "within", "would", "you", "your", "yours",
    # Boilerplate: present in nearly every resume and JD, so it tells us nothing.
    "ability", "able", "applicant", "apply", "benefit", "benefits", "candidate", "candidates",
    "career", "company", "description", "employer", "employment", "equal", "excellent", "experience",
    "experienced", "familiar", "familiarity", "good", "great", "hiring", "job", "join", "knowledge",
    "location", "looking", "opportunity", "plus", "position", "preferred", "proficient", "qualification",
    "qualifications", "required", "requirement", "requirements", "responsibility", "responsibilities",
    "role", "salary", "skill", "skills", "strong", "team", "teams", "understanding", "work", "working",
    "year", "years",
}

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./_-]*")


# ---------------------------------------------------------------------------
# Tokenising and TF-IDF
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Lowercase content tokens, lightly de-pluralised, stopwords removed.

    Tokens keep ``+ # . / - _`` so that "c++", "ci/cd", "node.js" and
    "spring-boot" survive as single terms.
    """
    tokens: list[str] = []
    for raw in TOKEN_RE.findall((text or "").lower()):
        token = raw.strip("-._/")
        if len(token) < 2 or token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(_singular(token))
    return tokens


# Technology names that happen to end in "s" and must survive de-pluralising.
NO_STRIP = {
    "analysis", "aws", "basis", "css", "devops", "https", "ios", "jenkins", "jira", "js",
    "kubernetes", "kafkas", "nodejs", "redis", "sass", "sms", "sql-plus", "status", "tls",
}


def _singular(token: str) -> str:
    """"apis" -> "api", leaving names that merely end in "s" intact.

    Correct English is not the goal - consistency is.  Both the resume and the
    job description pass through this function, so a crude rule still matches
    "services" to "service" as long as it never mangles a technology name:

    * tokens carrying punctuation are left alone ("node.js", "ci/cd", "c++")
    * "ss", "us" and "sis" endings are left alone ("css", "status", "analysis")
    * anything in :data:`NO_STRIP` is left alone ("kubernetes", "jenkins")
    """
    if not token.isalpha():
        return token
    if token in NO_STRIP or len(token) <= 3:
        return token
    if token.endswith(("ss", "us", "sis")):
        return token
    return token[:-1] if token.endswith("s") else token


class TfidfIndex:
    """Minimal TF-IDF vectoriser with cosine similarity.

    :param corpus: background documents used to estimate IDF.  With fewer than
        three documents there is nothing to learn from, so every term gets an
        IDF of 1.0 and the result degrades gracefully to stopword-filtered TF
        cosine rather than to noise.
    """

    MIN_CORPUS = 3

    def __init__(self, corpus: list[str] | None = None) -> None:
        corpus = [doc for doc in (corpus or []) if doc and doc.strip()]
        self.document_count = len(corpus)
        self.document_frequency: Counter[str] = Counter()
        if self.document_count >= self.MIN_CORPUS:
            for document in corpus:
                for term in set(tokenize(document)):
                    self.document_frequency[term] += 1

    def idf(self, term: str) -> float:
        if self.document_count < self.MIN_CORPUS:
            return 1.0
        df = self.document_frequency.get(term, 0)
        # Smoothed IDF: never divides by zero, never returns a negative weight.
        return math.log((1 + self.document_count) / (1 + df)) + 1.0

    def vector(self, text: str) -> dict[str, float]:
        """L2-normalised sublinear-TF * IDF vector for ``text``."""
        counts = Counter(tokenize(text))
        if not counts:
            return {}
        weights = {
            term: (1.0 + math.log(count)) * self.idf(term)
            for term, count in counts.items()
        }
        norm = math.sqrt(sum(w * w for w in weights.values()))
        if norm == 0:
            return {}
        return {term: w / norm for term, w in weights.items()}

    def similarity(self, left: str, right: str) -> float:
        """Cosine similarity of two documents, in ``0.0 - 1.0``."""
        a, b = self.vector(left), self.vector(right)
        if not a or not b:
            return 0.0
        smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
        return max(0.0, min(1.0, sum(w * larger.get(term, 0.0) for term, w in smaller.items())))


# ---------------------------------------------------------------------------
# Job-description analysis
# ---------------------------------------------------------------------------

@dataclass
class JobRequirements:
    """What a job description asks for."""

    skills: dict[str, float] = field(default_factory=dict)  # canonical -> weight
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    required_years: float | None = None
    top_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def analyse_job(description: str, index: TfidfIndex | None = None) -> JobRequirements:
    """Split a JD into required vs preferred skills and pull out its asks."""
    description = description or ""
    required_block, preferred_block = _split_requirement_blocks(description)

    required = set(extract_skills(required_block))
    preferred = set(extract_skills(preferred_block)) - required
    mentioned = skill_counts(description)

    weights: dict[str, float] = {}
    for skill, count in mentioned.items():
        if skill in required:
            base = REQUIRED_WEIGHT
        elif skill in preferred:
            base = PREFERRED_WEIGHT
        else:
            base = NEUTRAL_WEIGHT
        # Repeated mentions nudge the weight up, with diminishing returns.
        weights[skill] = round(base * (1.0 + 0.15 * math.log(count)), 3)

    index = index or TfidfIndex()
    vector = index.vector(description)
    top = [term for term, _ in sorted(vector.items(), key=lambda kv: kv[1], reverse=True)[:20]]

    return JobRequirements(
        skills=weights,
        required_skills=sorted(required),
        preferred_skills=sorted(preferred),
        required_years=_required_years(description),
        top_keywords=top,
    )


def _split_requirement_blocks(description: str) -> tuple[str, str]:
    """Return (required text, preferred text) from a job description.

    Walks the JD line by line and attributes each line to whichever heading
    most recently opened.  A JD with no such headings yields two empty blocks,
    which is the signal to treat every skill as neutral weight.
    """
    required_lines: list[str] = []
    preferred_lines: list[str] = []
    current: list[str] | None = None
    for line in description.split("\n"):
        if REQUIRED_HEADING_RE.match(line):
            current = required_lines
            # The heading line can itself carry the requirement ("Required: Java").
            required_lines.append(line)
            continue
        if PREFERRED_HEADING_RE.match(line):
            current = preferred_lines
            preferred_lines.append(line)
            continue
        if current is not None:
            current.append(line)
    return "\n".join(required_lines), "\n".join(preferred_lines)


def _required_years(description: str) -> float | None:
    """Smallest number of years the JD asks for, if it asks at all."""
    candidates = [
        float(match.group("years"))
        for match in REQUIRED_YEARS_RE.finditer(description or "")
        if float(match.group("years")) <= 40
    ]
    return min(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    """An explainable match between one resume and one job description."""

    overall: float = 0.0
    skill_score: float | None = None
    keyword_score: float | None = None
    experience_score: float | None = None
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    extra_skills: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    required_years: float | None = None
    candidate_years: float = 0.0
    weights_used: dict[str, float] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    verdict: str = "weak"

    def to_dict(self) -> dict:
        return asdict(self)


def match_resume_to_job(
    resume_text: str,
    job_description: str,
    candidate_years: float | None = None,
    index: TfidfIndex | None = None,
    weights: dict[str, float] | None = None,
) -> MatchResult:
    """Score ``resume_text`` against ``job_description``.

    :param candidate_years: years of experience; parsed from the resume when omitted
    :param index: TF-IDF index fitted on a background corpus of job descriptions.
        Passing one makes keyword similarity corpus-aware; omitting it falls back
        to stopword-filtered TF cosine.
    :param weights: override :data:`DEFAULT_WEIGHTS`
    """
    from app.core.parser import estimate_experience_years  # local import: avoids a cycle

    index = index or TfidfIndex()
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    requirements = analyse_job(job_description, index)

    resume_skills = extract_skills(resume_text)
    resume_skill_set = set(resume_skills)
    jd_skills = requirements.skills

    matched = [s for s in resume_skills if s in jd_skills]
    missing = [s for s in jd_skills if s not in resume_skill_set]
    # Order missing skills by how much they cost: heaviest weight first.
    missing.sort(key=lambda s: jd_skills[s], reverse=True)

    components: list[tuple[str, float, float]] = []  # (name, score 0-100, weight)

    skill_score: float | None = None
    if jd_skills:
        total_weight = sum(jd_skills.values())
        hit_weight = sum(weight for skill, weight in jd_skills.items() if skill in resume_skill_set)
        skill_score = round(100 * hit_weight / total_weight, 1)
        components.append(("skills", skill_score, weights["skills"]))

    keyword_score = round(100 * index.similarity(resume_text, job_description), 1)
    components.append(("keywords", keyword_score, weights["keywords"]))

    years = candidate_years if candidate_years is not None else estimate_experience_years(resume_text)
    experience_score: float | None = None
    if requirements.required_years:
        ratio = years / requirements.required_years
        experience_score = round(100 * min(1.0, ratio), 1)
        components.append(("experience", experience_score, weights["experience"]))

    applied_weight = sum(weight for _, _, weight in components) or 1.0
    overall = round(sum(score * weight for _, score, weight in components) / applied_weight, 1)

    result = MatchResult(
        overall=overall,
        skill_score=skill_score,
        keyword_score=keyword_score,
        experience_score=experience_score,
        matched_skills=matched,
        missing_skills=missing,
        missing_required=[s for s in requirements.required_skills if s not in resume_skill_set],
        extra_skills=[s for s in resume_skills if s not in jd_skills][:15],
        missing_keywords=_missing_keywords(requirements.top_keywords, job_description, resume_text),
        required_years=requirements.required_years,
        candidate_years=years,
        weights_used={name: round(weight / applied_weight, 3) for name, _, weight in components},
        verdict=verdict_for(overall),
    )
    result.suggestions = build_suggestions(result)
    return result


def _missing_keywords(top_keywords: list[str], job_description: str, resume_text: str) -> list[str]:
    """JD terms worth flagging as absent from the resume.

    A term the posting uses only once is usually a company name or incidental
    phrasing, so requiring two mentions keeps the advice about recurring themes
    rather than noise.
    """
    jd_counts = Counter(tokenize(job_description))
    resume_terms = set(tokenize(resume_text))
    return [
        term
        for term in top_keywords
        if term not in resume_terms and jd_counts.get(term, 0) >= 2
    ][:10]


def verdict_for(score: float) -> str:
    """Plain-language band for a score, used for badges in the UI."""
    if score >= 80:
        return "strong"
    if score >= 65:
        return "good"
    if score >= 45:
        return "fair"
    return "weak"


def build_suggestions(result: MatchResult) -> list[str]:
    """Concrete, actionable notes - what to change on the resume, in priority order."""
    notes: list[str] = []

    if result.missing_required:
        shown = ", ".join(result.missing_required[:5])
        plural = len(result.missing_required) > 1
        notes.append(
            f"The job lists {shown} as required and your resume does not mention "
            f"{'them' if plural else 'it'}. "
            f"Add {'them' if plural else 'it'} wherever you genuinely have the experience "
            "- a project line counts."
        )

    other_missing = [s for s in result.missing_skills if s not in result.missing_required]
    if other_missing:
        notes.append(
            "Also mentioned in the posting but absent from your resume: "
            + ", ".join(other_missing[:6])
            + "."
        )

    if result.required_years and result.candidate_years < result.required_years:
        gap = round(result.required_years - result.candidate_years, 1)
        notes.append(
            f"The posting asks for {result.required_years:g} years and your resume evidences "
            f"{result.candidate_years:g} - a {gap:g}-year gap. Internships, freelance work and "
            "substantial course projects are worth dating explicitly so they count."
        )

    if result.keyword_score is not None and result.keyword_score < 25:
        notes.append(
            "Keyword overlap is low even outside the skill list. Mirror the posting's own "
            "vocabulary for the work you have actually done, especially in your summary."
        )

    if result.missing_keywords:
        notes.append(
            "Terms the posting leans on that your resume never uses: "
            + ", ".join(result.missing_keywords[:8])
            + "."
        )

    if not notes:
        notes.append("Strong coverage - no gaps worth flagging against this posting.")
    return notes


# ---------------------------------------------------------------------------
# Resume hygiene (job-independent)
# ---------------------------------------------------------------------------

@dataclass
class HealthCheck:
    label: str
    passed: bool
    detail: str


def resume_health(parsed, text: str) -> list[HealthCheck]:
    """Checks that hold regardless of which job the resume is aimed at.

    :param parsed: a :class:`app.core.parser.ParsedResume`
    """
    checks: list[HealthCheck] = []
    words = parsed.word_count or len((text or "").split())

    checks.append(HealthCheck(
        "Contact details",
        bool(parsed.email and parsed.phone),
        "Email and phone both present." if parsed.email and parsed.phone
        else "Add whichever of email / phone is missing near the top.",
    ))
    checks.append(HealthCheck(
        "Professional links",
        bool(parsed.linkedin or parsed.github),
        "LinkedIn or GitHub linked." if parsed.linkedin or parsed.github
        else "No LinkedIn or GitHub URL found - add at least one.",
    ))
    checks.append(HealthCheck(
        "Length",
        300 <= words <= 1000,
        f"{words} words - a comfortable one-to-two pages." if 300 <= words <= 1000
        else (f"Only {words} words - thin for a technical resume; expand your project impact."
              if words < 300 else
              f"{words} words - long enough that recruiters will skim. Cut to the strongest material."),
    ))
    checks.append(HealthCheck(
        "Skills breadth",
        len(parsed.skills) >= 8,
        f"{len(parsed.skills)} recognised skills." if len(parsed.skills) >= 8
        else f"Only {len(parsed.skills)} recognised skills - name your stack explicitly in a skills section.",
    ))

    expected_sections = {"experience", "education", "skills"}
    present = expected_sections & set(parsed.sections)
    checks.append(HealthCheck(
        "Standard sections",
        present == expected_sections,
        "Experience, education and skills all found." if present == expected_sections
        else "Missing clear heading(s) for: " + ", ".join(sorted(expected_sections - present))
             + ". Resume parsers rely on these.",
    ))

    body = " ".join(parsed.sections.get(key, "") for key in ("experience", "projects")) or (text or "")
    quantified = len(re.findall(r"\d+\s*(?:%|percent|x|k\b|users?|requests?|ms\b|hours?|days?)", body, re.I))
    checks.append(HealthCheck(
        "Quantified impact",
        quantified >= 2,
        f"{quantified} quantified result(s) found." if quantified >= 2
        else (f"Only {quantified} quantified result(s) in your experience bullets. "
              if quantified else "No numbers in your experience bullets. ")
             + "Quantify outcomes - latency, coverage, users, time saved.",
    ))

    categories = {category_of(skill) for skill in parsed.skills} - {None}
    checks.append(HealthCheck(
        "Stack coverage",
        len(categories) >= 3,
        f"Skills span {len(categories)} areas." if len(categories) >= 3
        else "Your skills cluster in one or two areas - show database, cloud or testing exposure too.",
    ))
    return checks
