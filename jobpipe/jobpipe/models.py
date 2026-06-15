"""SQLAlchemy ORM models and Pydantic validation schemas."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CandidateEnum(str, enum.Enum):
    engineer = "engineer"
    scientist = "scientist"
    both = "both"


class MatchStatus(str, enum.Enum):
    new = "new"
    drafted = "drafted"
    reviewed = "reviewed"
    applied = "applied"
    skipped = "skipped"


class ATSType(str, enum.Enum):
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    workday = "workday"
    fallback = "fallback"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# SQLAlchemy ORM
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    candidate: Mapped[str] = mapped_column(
        Enum(CandidateEnum), nullable=False, default=CandidateEnum.both
    )
    sector: Mapped[Optional[str]] = mapped_column(String(128))
    careers_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    ats: Mapped[Optional[str]] = mapped_column(Enum(ATSType))
    board_token: Mapped[Optional[str]] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ats_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    postings: Mapped[list[Posting]] = relationship(
        "Posting", back_populates="company", cascade="all, delete-orphan"
    )


class Posting(Base):
    __tablename__ = "posting"
    __table_args__ = (UniqueConstraint("company_id", "ats_job_id", name="uq_company_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), nullable=False)
    ats_job_id: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(512))
    department: Mapped[Optional[str]] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    jd_text: Mapped[Optional[str]] = mapped_column(Text)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))

    company: Mapped[Company] = relationship("Company", back_populates="postings")
    matches: Mapped[list[Match]] = relationship(
        "Match", back_populates="posting", cascade="all, delete-orphan"
    )


class Match(Base):
    __tablename__ = "match"
    __table_args__ = (
        UniqueConstraint("posting_id", "candidate", name="uq_posting_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("posting.id"), nullable=False)
    candidate: Mapped[str] = mapped_column(
        Enum(CandidateEnum), nullable=False
    )
    score: Mapped[Optional[float]] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum(MatchStatus), nullable=False, default=MatchStatus.new
    )

    posting: Mapped[Posting] = relationship("Posting", back_populates="matches")
    drafts: Mapped[list[Draft]] = relationship(
        "Draft", back_populates="match", cascade="all, delete-orphan"
    )


class Draft(Base):
    __tablename__ = "draft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match.id"), nullable=False)
    cv_path: Mapped[Optional[str]] = mapped_column(String(2048))
    cover_letter_path: Mapped[Optional[str]] = mapped_column(String(2048))
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    match: Mapped[Match] = relationship("Match", back_populates="drafts")


# ---------------------------------------------------------------------------
# Pydantic schemas (for ATS normalization and API boundaries)
# ---------------------------------------------------------------------------


class JobPosting(BaseModel):
    """Normalized job posting from any ATS adapter."""

    model_config = ConfigDict(populate_by_name=True)

    ats_job_id: str
    title: str
    location: Optional[str] = None
    department: Optional[str] = None
    url: str
    jd_text: Optional[str] = None
    posted_at: Optional[datetime] = None
    raw: Optional[dict] = None

    @field_validator("ats_job_id", "title", "url", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class CompanyRow(BaseModel):
    """Row parsed from companies.csv."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    candidate: CandidateEnum
    sector: Optional[str] = None
    careers_url: str
    ats: Optional[ATSType] = None
    board_token: Optional[str] = None
    active: bool = True

    @field_validator("ats", mode="before")
    @classmethod
    def coerce_ats(cls, v: object) -> Optional[ATSType]:
        if v in (None, "", "?"):
            return None
        if isinstance(v, str):
            try:
                return ATSType(v.strip().lower())
            except ValueError:
                return ATSType.unknown
        return v

    @field_validator("board_token", mode="before")
    @classmethod
    def coerce_token(cls, v: object) -> Optional[str]:
        if v in (None, "", "?"):
            return None
        return str(v).strip()

    @field_validator("active", mode="before")
    @classmethod
    def coerce_bool(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class MatchResult(BaseModel):
    """LLM relevance scoring output (strict JSON)."""

    score: int
    reason: str

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        return max(0, min(100, v))
