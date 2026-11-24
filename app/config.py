"""Application settings, overridable by environment variable or a .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Every knob the app has. Prefix env vars with ``SRT_`` (``SRT_DATABASE_URL``)."""

    model_config = SettingsConfigDict(env_prefix="SRT_", env_file=".env", extra="ignore")

    app_name: str = "Smart Resume Tracker"
    version: str = "1.0.0"

    # SQLite by default so the app runs with no external services.
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'tracker.db'}"

    # Upload guards
    max_upload_bytes: int = 5 * 1024 * 1024       # 5 MB per resume
    max_screening_files: int = 50                  # per screening run

    # Scoring weights (must sum to 1.0; any unusable signal is redistributed)
    weight_skills: float = 0.55
    weight_keywords: float = 0.30
    weight_experience: float = 0.15

    @property
    def weights(self) -> dict[str, float]:
        return {
            "skills": self.weight_skills,
            "keywords": self.weight_keywords,
            "experience": self.weight_experience,
        }


settings = Settings()

# SQLite needs the parent directory to exist before it will open the file.
if settings.database_url.startswith("sqlite:///"):
    Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
