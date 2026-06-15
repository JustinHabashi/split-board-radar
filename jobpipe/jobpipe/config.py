"""Load and validate all configuration: settings.yaml, candidates/*.yaml, companies.csv."""

from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from jobpipe.models import ATSType, CandidateEnum, CompanyRow

# Default config root: the config/ directory inside the package root.
# Override with CONFIG_DIR env var.
_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent / "config"


def _config_dir() -> Path:
    return Path(os.environ.get("CONFIG_DIR", str(_DEFAULT_CONFIG_DIR)))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class RateLimitSettings(BaseModel):
    requests_per_second: float = 2.0
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    backoff_multiplier: float = 2.0


class HttpSettings(BaseModel):
    timeout_seconds: int = 30
    user_agent: str = "JobPipe/1.0"


class FilteringSettings(BaseModel):
    location_aliases: list[str] = Field(default_factory=list)
    remote_patterns: list[str] = Field(default_factory=list)


class TailoringSettings(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    temperature: float = 0.3


class EmailSettings(BaseModel):
    recipients: dict[str, str] = Field(default_factory=dict)
    from_address: str = ""
    subject_prefix: str = "[JobPipe]"


class ScheduleSettings(BaseModel):
    cron: str = "0 7 * * *"


class Settings(BaseModel):
    relevance_threshold: int = 70
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    rate_limits: RateLimitSettings = Field(default_factory=RateLimitSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    filtering: FilteringSettings = Field(default_factory=FilteringSettings)
    tailoring: TailoringSettings = Field(default_factory=TailoringSettings)


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    path = _config_dir() / "settings.yaml"
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open() as f:
            raw = yaml.safe_load(f) or {}
    return Settings.model_validate(raw)


# ---------------------------------------------------------------------------
# Candidate profile
# ---------------------------------------------------------------------------


class CandidateProfile(BaseModel):
    name: str
    target_levels: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    must_have_keywords: list[str] = Field(default_factory=list)
    nice_to_have_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    master_cv_path: str = ""
    cover_letter_template_path: str = ""
    summary: str = ""
    formatting_preferences: list[str] = Field(default_factory=list)


def load_candidate(name: str) -> CandidateProfile:
    """Load a candidate profile by filename stem (engineer / scientist)."""
    path = _config_dir() / "candidates" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Candidate config not found: {path}")
    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    return CandidateProfile.model_validate(raw)


@lru_cache(maxsize=1)
def load_all_candidates() -> dict[str, CandidateProfile]:
    candidates_dir = _config_dir() / "candidates"
    result: dict[str, CandidateProfile] = {}
    for yaml_file in sorted(candidates_dir.glob("*.yaml")):
        result[yaml_file.stem] = load_candidate(yaml_file.stem)
    return result


# ---------------------------------------------------------------------------
# Companies CSV
# ---------------------------------------------------------------------------


def load_companies_csv() -> list[CompanyRow]:
    path = _config_dir() / "companies.csv"
    if not path.exists():
        raise FileNotFoundError(f"companies.csv not found at {path}")
    rows: list[CompanyRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            rows.append(CompanyRow.model_validate(raw_row))
    return rows


def candidates_for_company(row: CompanyRow) -> list[str]:
    """Return the list of candidate keys that should process a company row."""
    if row.candidate == CandidateEnum.both:
        return ["engineer", "scientist"]
    return [row.candidate.value]
