"""Skill taxonomy used by the parser and the matching engine.

A single source of truth mapping a *canonical* skill name to the surface
forms that appear in real resumes and job descriptions ("js" -> "JavaScript",
"spring-boot" -> "Spring Boot").  Keeping aliases here means the matcher never
has to guess, and adding a skill is a one-line change.
"""

from __future__ import annotations

import re
from functools import lru_cache

# ---------------------------------------------------------------------------
# Taxonomy: category -> canonical name -> aliases
# ---------------------------------------------------------------------------

TAXONOMY: dict[str, dict[str, list[str]]] = {
    "languages": {
        "Python": ["python", "python3", "py"],
        "Java": ["java", "core java", "java se", "java8", "java 8", "java 17"],
        "JavaScript": ["javascript", "js", "es6", "ecmascript", "vanilla js"],
        "TypeScript": ["typescript", "ts"],
        "C": ["c language", "ansi c"],
        "C++": ["c++", "cpp", "cplusplus"],
        "C#": ["c#", "csharp", "c sharp"],
        "Go": ["golang", "go lang"],
        "Rust": ["rust", "rustlang"],
        "Kotlin": ["kotlin"],
        "Swift": ["swift"],
        "PHP": ["php"],
        "Ruby": ["ruby"],
        "Scala": ["scala"],
        "R": ["r language", "rstats"],
        "SQL": ["sql", "ansi sql", "t-sql", "tsql", "pl/sql", "plsql"],
        "Bash": ["bash", "shell scripting", "shell script", "sh scripting"],
        "PowerShell": ["powershell", "power shell"],
    },
    "frontend": {
        "React": ["react", "react.js", "reactjs"],
        "Next.js": ["next.js", "nextjs", "next js"],
        "Angular": ["angular", "angularjs", "angular 2+"],
        "Vue.js": ["vue", "vue.js", "vuejs"],
        "HTML": ["html", "html5"],
        "CSS": ["css", "css3"],
        "Sass": ["sass", "scss"],
        "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"],
        "Bootstrap": ["bootstrap"],
        "Redux": ["redux", "redux toolkit"],
        "jQuery": ["jquery"],
    },
    "backend": {
        "Spring Boot": ["spring boot", "springboot", "spring-boot"],
        "Spring": ["spring framework", "spring mvc", "spring core"],
        "Hibernate": ["hibernate", "jpa", "spring data jpa"],
        "FastAPI": ["fastapi", "fast api"],
        "Django": ["django", "django rest framework", "drf"],
        "Flask": ["flask"],
        "Node.js": ["node", "node.js", "nodejs"],
        "Express.js": ["express", "express.js", "expressjs"],
        ".NET": [".net", "dotnet", "asp.net", "asp.net core"],
        "GraphQL": ["graphql", "graph ql"],
        "REST API": ["rest", "rest api", "restful", "restful api", "rest apis"],
        "gRPC": ["grpc"],
        "Microservices": ["microservices", "microservice", "micro services"],
        "Celery": ["celery"],
        "Maven": ["maven", "apache maven"],
        "Gradle": ["gradle"],
    },
    "databases": {
        "MySQL": ["mysql", "my sql"],
        "PostgreSQL": ["postgresql", "postgres", "psql"],
        "MongoDB": ["mongodb", "mongo", "mongo db"],
        "SQLite": ["sqlite", "sqlite3"],
        "Oracle": ["oracle db", "oracle database", "oracle 11g", "oracle 12c"],
        "Microsoft SQL Server": ["sql server", "mssql", "ms sql"],
        "Redis": ["redis"],
        "Elasticsearch": ["elasticsearch", "elastic search", "opensearch"],
        "Cassandra": ["cassandra", "apache cassandra"],
        "DynamoDB": ["dynamodb", "dynamo db"],
        "Snowflake": ["snowflake"],
    },
    "cloud_devops": {
        "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda", "cloudformation"],
        "Azure": ["azure", "microsoft azure", "azure devops"],
        "Google Cloud": ["gcp", "google cloud", "google cloud platform"],
        "Docker": ["docker", "dockerize", "containerization"],
        "Kubernetes": ["kubernetes", "k8s", "eks", "gke", "aks"],
        "Terraform": ["terraform", "iac", "infrastructure as code"],
        "Ansible": ["ansible"],
        "Jenkins": ["jenkins"],
        "GitHub Actions": ["github actions", "gh actions"],
        "GitLab CI": ["gitlab ci", "gitlab-ci", "gitlab runner"],
        "CI/CD": ["ci/cd", "cicd", "ci cd", "continuous integration", "continuous delivery"],
        "Linux": ["linux", "unix", "ubuntu", "centos", "rhel"],
        "Nginx": ["nginx"],
        "Prometheus": ["prometheus"],
        "Grafana": ["grafana"],
        "Kafka": ["kafka", "apache kafka"],
        "RabbitMQ": ["rabbitmq", "rabbit mq"],
        "Git": ["git", "version control"],
    },
    "data_ml": {
        "Pandas": ["pandas"],
        "NumPy": ["numpy"],
        "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
        "TensorFlow": ["tensorflow", "tensor flow"],
        "PyTorch": ["pytorch", "torch"],
        "Machine Learning": ["machine learning", "ml models", "supervised learning"],
        "Deep Learning": ["deep learning", "neural networks", "cnn", "rnn", "lstm"],
        "NLP": ["nlp", "natural language processing"],
        "Computer Vision": ["computer vision", "opencv", "image processing"],
        "Power BI": ["power bi", "powerbi"],
        "Tableau": ["tableau"],
        "Apache Spark": ["spark", "pyspark", "apache spark"],
        "Airflow": ["airflow", "apache airflow"],
        "ETL": ["etl", "elt", "data pipeline", "data pipelines"],
    },
    "testing": {
        "JUnit": ["junit", "junit5"],
        "pytest": ["pytest", "py.test"],
        "Selenium": ["selenium", "selenium webdriver"],
        "Cypress": ["cypress"],
        "Playwright": ["playwright"],
        "Postman": ["postman"],
        "Mockito": ["mockito"],
        "Jest": ["jest"],
        "TestNG": ["testng"],
        "Unit Testing": ["unit testing", "unit tests", "unit test"],
        "Automation Testing": ["automation testing", "test automation", "qa automation"],
    },
    "practices": {
        "Agile": ["agile", "scrum", "sprint planning", "kanban"],
        "System Design": ["system design", "high level design", "low level design", "hld", "lld"],
        "Data Structures": ["data structures", "dsa", "algorithms"],
        "OOP": ["oop", "object oriented programming", "object-oriented design"],
        "Design Patterns": ["design patterns", "solid principles"],
        "Code Review": ["code review", "peer review"],
        "Debugging": ["debugging", "troubleshooting", "root cause analysis"],
        "Documentation": ["technical documentation", "api documentation"],
    },
    "soft": {
        "Communication": ["communication skills", "verbal communication", "written communication"],
        "Teamwork": ["teamwork", "team player", "collaboration", "cross-functional"],
        "Problem Solving": ["problem solving", "problem-solving", "analytical skills"],
        "Leadership": ["leadership", "team lead", "mentoring", "mentorship"],
        "Time Management": ["time management", "prioritization"],
        "Stakeholder Management": ["stakeholder management", "client interaction", "client facing"],
    },
}

# Canonical names that should never be auto-matched by a bare substring because
# they are short and collide with ordinary English ("R", "C", "Go").
_SHORT_TOKENS = {"C", "R", "Go", "C#", "C++", "SQL", "AWS", "ETL", "OOP", "NLP"}


def all_skills() -> list[str]:
    """Every canonical skill name, sorted."""
    return sorted({skill for group in TAXONOMY.values() for skill in group})


def category_of(skill: str) -> str | None:
    """The taxonomy category a canonical skill belongs to."""
    for category, group in TAXONOMY.items():
        if skill in group:
            return category
    return None


def categories_for(skills: list[str]) -> dict[str, list[str]]:
    """Group a list of canonical skills by category, preserving order."""
    grouped: dict[str, list[str]] = {}
    for skill in skills:
        grouped.setdefault(category_of(skill) or "other", []).append(skill)
    return grouped


def _alias_pattern(alias: str) -> str:
    r"""Regex source for one alias, where a space also matches a hyphen.

    Built by splitting on whitespace *before* escaping: ``re.escape`` turns a
    space into ``"\ "`` (for re.VERBOSE), so substituting afterwards would
    corrupt the pattern.
    """
    return r"[\s\-]+".join(re.escape(part) for part in alias.split())


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    r"""Compile one regex per canonical skill, matching any of its aliases.

    The boundaries are hand-tuned for resume punctuation:

    * ``(?<![\w#+])``  - "java" must not match inside "javascript".
    * ``(?<!\w\.)``    - but "sql" may not match inside "my.sql" either.
    * ``(?![\w#+])``    - "go" must not match inside "going".
    * ``(?!\.\w)``      - "node" must not match the "node" of "node.js",
      while ``AWS.`` and ``C++.`` at the end of a sentence still match.
    """
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for group in TAXONOMY.values():
        for canonical, aliases in group.items():
            surface_forms = {canonical.lower(), *(a.lower() for a in aliases)}
            parts = sorted(surface_forms, key=len, reverse=True)
            alternation = "|".join(_alias_pattern(p) for p in parts)
            pattern = re.compile(
                rf"(?<![\w#+])(?<!\w\.)(?:{alternation})(?![\w#+])(?!\.\w)",
                re.IGNORECASE,
            )
            compiled.append((canonical, pattern))
    return compiled


def _spans(text: str) -> list[tuple[str, int, int]]:
    """Every (canonical skill, start, end) match in ``text``."""
    hits: list[tuple[str, int, int]] = []
    for canonical, pattern in _patterns():
        for match in pattern.finditer(text):
            hits.append((canonical, match.start(), match.end()))
    return hits


def _drop_shadowed(hits: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Remove matches swallowed by a longer match at the same place.

    "Spring Boot" should register as Spring Boot only - not as Spring as well -
    but a standalone "Spring MVC" elsewhere in the same document still counts.
    """
    kept: list[tuple[str, int, int]] = []
    for canonical, start, end in hits:
        shadowed = any(
            other != canonical
            and other_start <= start
            and end <= other_end
            and (other_end - other_start) > (end - start)
            for other, other_start, other_end in hits
        )
        if not shadowed:
            kept.append((canonical, start, end))
    return kept


def extract_skills(text: str) -> list[str]:
    """Canonical skills mentioned in ``text``, in taxonomy order.

    >>> extract_skills("Built REST APIs with Spring Boot and MySQL")
    ['Spring Boot', 'REST API', 'MySQL']
    """
    if not text:
        return []
    present = {canonical for canonical, _, _ in _drop_shadowed(_spans(text))}
    # Return in taxonomy order so output is stable and reads by category.
    return [skill for skill in _ordered_skills() if skill in present]


def skill_counts(text: str) -> dict[str, int]:
    """How many times each canonical skill is mentioned - a crude importance signal."""
    if not text:
        return {}
    counts: dict[str, int] = {}
    for canonical, _, _ in _drop_shadowed(_spans(text)):
        counts[canonical] = counts.get(canonical, 0) + 1
    return counts


@lru_cache(maxsize=1)
def _ordered_skills() -> list[str]:
    """Canonical names in declaration order (languages first, soft skills last)."""
    return [skill for group in TAXONOMY.values() for skill in group]
