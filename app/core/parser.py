"""Resume text extraction and structured parsing.

Two jobs live here:

``extract_text``   bytes of a PDF / DOCX / TXT upload -> plain text
``parse_resume``   plain text -> :class:`ParsedResume` (contact, skills, dates)

The parsing is deliberately heuristic and dependency-light: regexes plus a
section splitter.  That keeps the install small and - more importantly - keeps
every decision inspectable, which matters when a candidate asks *why* their
resume scored the way it did.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from datetime import date

from app.core.skills import extract_skills

# ---------------------------------------------------------------------------
# File-type dispatch
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class UnsupportedFileType(ValueError):
    """Raised when an upload is not a PDF, DOCX or plain-text file."""


def extract_text(data: bytes, filename: str) -> str:
    """Return the plain text of an uploaded resume.

    :param data: raw bytes of the upload
    :param filename: used only to pick a decoder, never to read from disk
    :raises UnsupportedFileType: for anything outside ``SUPPORTED_EXTENSIONS``
    """
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == ".pdf":
        text = _extract_pdf(data)
    elif suffix == ".docx":
        text = _extract_docx(data)
    elif suffix in {".txt", ".md"}:
        text = data.decode("utf-8", errors="replace")
    else:
        raise UnsupportedFileType(
            f"{filename!r}: expected one of {sorted(SUPPORTED_EXTENSIONS)}"
        )
    return normalise_whitespace(text)


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # a single malformed page should not kill the upload
            pages.append("")
    return "\n".join(pages)


def _extract_docx(data: bytes) -> str:
    import docx  # python-docx

    document = docx.Document(io.BytesIO(data))
    blocks = [p.text for p in document.paragraphs]
    # Skills are very often laid out in a table, so pull those cells in too.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return "\n".join(blocks)


def normalise_whitespace(text: str) -> str:
    """Collapse the ragged whitespace that PDF extraction leaves behind."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("•", "\n- ").replace("●", "\n- ")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


# ---------------------------------------------------------------------------
# Field patterns
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Phone numbers vary too much for one strict pattern (Indian "+91 98765 43210"
# groups 5+5, US "(555) 123-4567" groups 3+3+4), so match loosely on a single
# line and let _phone() validate the digit count.  Newlines are excluded on
# purpose: a real number never wraps, but stacked year ranges would otherwise
# merge into a plausible-looking 12-digit "number".
PHONE_RE = re.compile(
    r"(?<![\w])(?:\+\d{1,3}[ \t.-]?)?(?:\(\d{2,4}\)[ \t.-]?)?\d[\d \t.\-()]{7,16}\d(?![\w])"
)
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w%-]+/?", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w.-]+/?", re.I)
URL_RE = re.compile(r"https?://[^\s,;)>\]]+", re.I)

DEGREE_RE = re.compile(
    r"\b(?:b\.?\s?tech|b\.?\s?e\.?|m\.?\s?tech|m\.?\s?e\.?|b\.?\s?sc|m\.?\s?sc|"
    r"b\.?\s?c\.?a|m\.?\s?c\.?a|b\.?\s?com|mba|ph\.?\s?d|bachelor(?:'s)?|master(?:'s)?|"
    r"diploma|intermediate|12th|10th)\b",
    re.I,
)

SECTION_HEADINGS = {
    "summary": ("summary", "objective", "profile", "about me", "career objective"),
    "skills": ("skills", "technical skills", "core competencies", "technologies", "tech stack"),
    "experience": (
        "experience", "work experience", "professional experience",
        "employment", "internship", "internships", "work history",
    ),
    "education": ("education", "academic", "academics", "qualifications", "academic details"),
    "projects": ("projects", "academic projects", "personal projects", "key projects"),
    "certifications": ("certifications", "certificates", "licenses", "courses"),
    "achievements": ("achievements", "awards", "honors", "accomplishments", "activities"),
}

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(MONTHS)
DATE_RANGE_RE = re.compile(
    rf"(?P<m1>{_MONTH_ALT})[a-z]*\.?\s*(?P<y1>(?:19|20)\d{{2}})"
    r"\s*(?:-|–|—|to|until|till)\s*"
    rf"(?:(?P<present>present|current|now|date)|(?P<m2>{_MONTH_ALT})[a-z]*\.?\s*(?P<y2>(?:19|20)\d{{2}}))",
    re.I,
)
YEAR_RANGE_RE = re.compile(
    r"(?<!\d)(?P<y1>(?:19|20)\d{2})\s*(?:-|–|—|to)\s*(?:(?P<present>present|current|now)|(?P<y2>(?:19|20)\d{2}))(?!\d)",
    re.I,
)
STATED_YEARS_RE = re.compile(
    r"(?P<years>\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:relevant\s*|professional\s*|hands[- ]on\s*)?experience",
    re.I,
)


# ---------------------------------------------------------------------------
# Parsed result
# ---------------------------------------------------------------------------

@dataclass
class ParsedResume:
    """Everything the tracker knows about one resume after parsing."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    github: str | None = None
    links: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    degrees: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    experience_years: float = 0.0
    word_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def parse_resume(text: str) -> ParsedResume:
    """Pull structured fields out of resume text."""
    text = text or ""
    sections = split_sections(text)
    return ParsedResume(
        name=guess_name(text),
        email=_first(EMAIL_RE, text),
        phone=_phone(text),
        linkedin=_normalise_url(_first(LINKEDIN_RE, text)),
        github=_normalise_url(_first(GITHUB_RE, text)),
        links=sorted(set(URL_RE.findall(text)))[:10],
        skills=extract_skills(text),
        degrees=_degrees(text),
        sections=sections,
        experience_years=estimate_experience_years(text),
        word_count=len(text.split()),
    )


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0).strip() if match else None


def _phone(text: str) -> str | None:
    """First candidate in ``text`` that actually looks like a phone number.

    Scanning every candidate rather than only the first means a date range
    earlier in the document ("2022 - 2026") cannot mask the real number
    further down.
    """
    for match in PHONE_RE.finditer(text):
        raw = match.group(0).strip(" \t.-")
        # "(555) 123-4567" starts matching at the digit, leaving a dangling
        # ")" - put the opening bracket back so the stored value reads right.
        if ")" in raw and "(" not in raw and match.start() > 0 and text[match.start() - 1] == "(":
            raw = "(" + raw
        if _looks_like_phone(raw):
            return raw
    return None


def _looks_like_phone(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    if not 10 <= len(digits) <= 13:
        return False
    # " - " with spaces around it reads as a range, not a dialling separator.
    if " - " in raw and not raw.startswith("+"):
        return False
    # "2022 2026 2018" is three years, not a phone number.
    groups = re.findall(r"\d+", raw)
    if all(len(g) == 4 and 1900 <= int(g) <= 2099 for g in groups):
        return False
    return True


def _normalise_url(raw: str | None) -> str | None:
    if not raw:
        return None
    url = raw.rstrip("/")
    return url if url.startswith("http") else f"https://{url}"


def _degrees(text: str) -> list[str]:
    seen: list[str] = []
    for match in DEGREE_RE.finditer(text):
        label = re.sub(r"\s+", " ", match.group(0)).strip().title()
        if label.lower() not in {d.lower() for d in seen}:
            seen.append(label)
    return seen[:6]


def guess_name(text: str) -> str | None:
    """Best guess at the candidate's name: the first line that looks like one."""
    for line in text.split("\n")[:8]:
        line = line.strip(" |,-")
        if not line or len(line) > 60:
            continue
        if EMAIL_RE.search(line) or URL_RE.search(line) or PHONE_RE.search(line):
            continue
        if any(ch.isdigit() for ch in line):
            continue
        if line.lower().rstrip(":") in {h for group in SECTION_HEADINGS.values() for h in group}:
            continue
        words = line.split()
        if 1 < len(words) <= 5 and all(w[:1].isalpha() for w in words):
            # A heading in ALL CAPS is still a plausible name on a resume.
            return line.title() if line.isupper() else line
    return None


def split_sections(text: str) -> dict[str, str]:
    """Slice the resume into known sections keyed by canonical section name."""
    lines = text.split("\n")
    heading_at: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        canonical = _match_heading(line)
        if canonical:
            heading_at.append((index, canonical))

    sections: dict[str, str] = {}
    for position, (index, canonical) in enumerate(heading_at):
        end = heading_at[position + 1][0] if position + 1 < len(heading_at) else len(lines)
        body = "\n".join(lines[index + 1 : end]).strip()
        if body:
            # Repeated headings (two "Projects" blocks) append rather than clobber.
            sections[canonical] = f"{sections[canonical]}\n{body}" if canonical in sections else body
    return sections


def _match_heading(line: str) -> str | None:
    cleaned = re.sub(r"[^a-z ]", "", line.lower()).strip()
    if not cleaned or len(cleaned.split()) > 4:
        return None
    for canonical, variants in SECTION_HEADINGS.items():
        if cleaned in variants:
            return canonical
    return None


def estimate_experience_years(text: str, today: date | None = None) -> float:
    """Years of experience, from date ranges if present and a stated figure if not.

    Overlapping ranges are merged, so a resume listing a concurrent internship
    and a part-time role does not double-count the same months.
    """
    today = today or date.today()
    intervals: list[tuple[int, int]] = []  # (start_month_index, end_month_index)

    for match in DATE_RANGE_RE.finditer(text):
        start = _month_index(int(match.group("y1")), MONTHS[match.group("m1").lower()[:4].rstrip(".")])
        if match.group("present"):
            end = _month_index(today.year, today.month)
        else:
            end = _month_index(int(match.group("y2")), MONTHS[match.group("m2").lower()[:4].rstrip(".")])
        if end >= start:
            intervals.append((start, end))

    if not intervals:
        for match in YEAR_RANGE_RE.finditer(text):
            start = _month_index(int(match.group("y1")), 1)
            end = (
                _month_index(today.year, today.month)
                if match.group("present")
                else _month_index(int(match.group("y2")), 12)
            )
            if end >= start:
                intervals.append((start, end))

    if intervals:
        months = _merged_month_span(intervals)
        return round(months / 12, 1)

    stated = STATED_YEARS_RE.search(text)
    return float(stated.group("years")) if stated else 0.0


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _merged_month_span(intervals: list[tuple[int, int]]) -> int:
    """Total months covered by possibly overlapping (start, end) month indices."""
    total = 0
    current_start, current_end = None, None
    for start, end in sorted(intervals):
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end + 1:  # contiguous or overlapping
            current_end = max(current_end, end)
        else:
            total += current_end - current_start + 1
            current_start, current_end = start, end
    if current_start is not None:
        total += current_end - current_start + 1
    return total
