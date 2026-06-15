"""Tests for the two-stage filter — keyword stage tested directly, LLM stage mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from jobpipe.config import CandidateProfile
from jobpipe.filter import (
    _truncate_jd,
    passes_keyword_filter,
    run_filter,
    score_posting,
    upsert_match,
)
from jobpipe.models import Company, Match, MatchResult, MatchStatus, Posting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_posting(
    session,
    company_name="TestCo",
    title="Senior Engineer",
    location="Seattle, WA",
    jd_text="Python, distributed systems, fintech",
    ats="greenhouse",
    candidate="engineer",
) -> Posting:
    company = session.query(Company).filter_by(name=company_name).first()
    if company is None:
        company = Company(
            name=company_name,
            candidate=candidate,
            careers_url="https://testco.com",
            ats=ats,
            board_token="testco",
            active=True,
            ats_resolved=True,
        )
        session.add(company)
        session.flush()

    now = datetime.now(timezone.utc)
    posting = Posting(
        company_id=company.id,
        ats_job_id=f"job-{id(company_name)}",
        title=title,
        location=location,
        jd_text=jd_text,
        url="https://testco.com/jobs/1",
        first_seen=now,
        last_seen=now,
    )
    session.add(posting)
    session.flush()
    return posting


def _engineer_profile() -> CandidateProfile:
    return CandidateProfile(
        name="Engineer",
        locations=["Seattle, WA", "remote"],
        must_have_keywords=["python", "backend"],
        nice_to_have_keywords=["kubernetes"],
        exclude_keywords=["ios", "android", "mobile"],
        summary="Senior backend engineer with Python expertise.",
        formatting_preferences=[],
    )


# ---------------------------------------------------------------------------
# Stage 1: keyword + location filter
# ---------------------------------------------------------------------------


class TestKeywordFilter:
    def test_passes_seattle_location(self):
        profile = _engineer_profile()
        posting = MagicMock()
        posting.id = 1
        posting.title = "Backend Engineer"
        posting.location = "Seattle, WA"
        posting.jd_text = "Python backend systems"
        assert passes_keyword_filter(posting, profile) is True

    def test_passes_remote_location(self):
        profile = _engineer_profile()
        posting = MagicMock()
        posting.id = 2
        posting.title = "Backend Engineer"
        posting.location = "Remote"
        posting.jd_text = "Python distributed systems"
        assert passes_keyword_filter(posting, profile) is True

    def test_filters_non_matching_location(self):
        profile = _engineer_profile()
        posting = MagicMock()
        posting.id = 3
        posting.title = "Backend Engineer"
        posting.location = "New York, NY"
        posting.jd_text = "Python backend"
        assert passes_keyword_filter(posting, profile) is False

    def test_exclude_keyword_in_title(self):
        profile = _engineer_profile()
        posting = MagicMock()
        posting.id = 4
        posting.title = "iOS Mobile Engineer"
        posting.location = "Seattle, WA"
        posting.jd_text = "Build iOS mobile apps"
        assert passes_keyword_filter(posting, profile) is False

    def test_exclude_keyword_in_jd(self):
        profile = _engineer_profile()
        posting = MagicMock()
        posting.id = 5
        posting.title = "Software Engineer"
        posting.location = "Seattle, WA"
        posting.jd_text = "We need Android mobile developers"
        assert passes_keyword_filter(posting, profile) is False

    def test_passes_with_remote_in_jd(self):
        profile = _engineer_profile()
        posting = MagicMock()
        posting.id = 6
        posting.title = "Backend Engineer"
        posting.location = "US"
        posting.jd_text = "remote work allowed, Python, distributed systems"
        assert passes_keyword_filter(posting, profile) is True

    def test_no_location_fails(self):
        profile = _engineer_profile()
        posting = MagicMock()
        posting.id = 7
        posting.title = "Engineer"
        posting.location = None
        posting.jd_text = "Python backend"
        # No location info => location_ok stays False unless "remote" in jd
        assert passes_keyword_filter(posting, profile) is False


# ---------------------------------------------------------------------------
# JD truncation
# ---------------------------------------------------------------------------


def test_truncate_jd_none():
    assert _truncate_jd(None) == "(no job description available)"


def test_truncate_jd_short():
    assert _truncate_jd("hello") == "hello"


def test_truncate_jd_long():
    long = "x" * 7000
    result = _truncate_jd(long)
    assert len(result) < 7000
    assert "truncated" in result


# ---------------------------------------------------------------------------
# Stage 2: LLM scoring (mocked)
# ---------------------------------------------------------------------------


def _mock_anthropic(score: int = 85, reason: str = "Great match") -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=f'{{"score": {score}, "reason": "{reason}"}}')]
    mock_client.messages.create.return_value = mock_response
    return mock_client


def test_score_posting_happy_path():
    posting = MagicMock()
    posting.id = 1
    posting.title = "Senior Engineer"
    posting.jd_text = "Python, distributed systems"
    profile = _engineer_profile()

    client = _mock_anthropic(score=88, reason="Strong Python match")
    result = score_posting(posting, "engineer", profile, client)

    assert result.score == 88
    assert "Python" in result.reason


def test_score_posting_json_in_markdown_fence():
    posting = MagicMock()
    posting.id = 2
    posting.title = "Backend SWE"
    posting.jd_text = "Python"
    profile = _engineer_profile()

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='```json\n{"score": 75, "reason": "Decent"}\n```')]
    mock_client.messages.create.return_value = mock_response

    result = score_posting(posting, "engineer", profile, mock_client)
    assert result.score == 75


def test_score_posting_bad_json_returns_zero():
    posting = MagicMock()
    posting.id = 3
    posting.title = "SWE"
    posting.jd_text = "Python"
    profile = _engineer_profile()

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Sorry, I cannot help with that.")]
    mock_client.messages.create.return_value = mock_response

    result = score_posting(posting, "engineer", profile, mock_client)
    assert result.score == 0


def test_score_posting_score_clamped():
    posting = MagicMock()
    posting.id = 4
    posting.title = "SWE"
    posting.jd_text = "Python"
    profile = _engineer_profile()

    result = score_posting(posting, "engineer", profile, _mock_anthropic(score=150))
    assert result.score == 100


# ---------------------------------------------------------------------------
# upsert_match
# ---------------------------------------------------------------------------


def test_upsert_match_creates_new(session):
    posting = _make_posting(session)
    result = MatchResult(score=80, reason="Good")
    match = upsert_match(session, posting, "engineer", result)
    session.commit()
    assert match.id is not None
    assert match.score == 80
    assert match.status == MatchStatus.new.value


def test_upsert_match_updates_existing(session):
    posting = _make_posting(session, company_name="UpdateCo")
    result1 = MatchResult(score=60, reason="Okay")
    upsert_match(session, posting, "engineer", result1)
    session.commit()

    result2 = MatchResult(score=90, reason="Better")
    upsert_match(session, posting, "engineer", result2)
    session.commit()

    matches = session.query(Match).filter_by(posting_id=posting.id).all()
    assert len(matches) == 1
    assert matches[0].score == 90


# ---------------------------------------------------------------------------
# run_filter integration
# ---------------------------------------------------------------------------


def test_run_filter_end_to_end(session):
    posting = _make_posting(
        session,
        company_name="RunFilterCo",
        title="Senior Python Engineer",
        location="Seattle, WA",
        jd_text="Python distributed backend systems fintech",
    )
    session.commit()

    mock_client = _mock_anthropic(score=85)

    with patch("jobpipe.filter.load_all_candidates") as mock_cands:
        mock_cands.return_value = {"engineer": _engineer_profile()}
        counts = run_filter(session, client=mock_client, posting_ids=[posting.id])

    assert counts["keyword_passed"] == 1
    assert counts["llm_scored"] == 1
    assert counts["above_threshold"] == 1

    match = session.query(Match).filter_by(posting_id=posting.id).first()
    assert match is not None
    assert match.score == 85


def test_run_filter_skips_non_matching_location(session):
    posting = _make_posting(
        session,
        company_name="NewYorkCo",
        title="Senior Python Engineer",
        location="New York, NY",
        jd_text="Python distributed backend",
    )
    session.commit()

    mock_client = _mock_anthropic(score=85)

    with patch("jobpipe.filter.load_all_candidates") as mock_cands:
        mock_cands.return_value = {"engineer": _engineer_profile()}
        counts = run_filter(session, client=mock_client, posting_ids=[posting.id])

    assert counts["keyword_passed"] == 0
    assert counts["llm_scored"] == 0


def test_run_filter_does_not_rescore(session):
    posting = _make_posting(
        session,
        company_name="NoDupeCo",
        title="Senior Python Engineer",
        location="Seattle, WA",
        jd_text="Python backend",
    )
    # Pre-insert a scored match
    match = Match(
        posting_id=posting.id,
        candidate="engineer",
        score=75.0,
        reason="already scored",
        status=MatchStatus.new.value,
    )
    session.add(match)
    session.commit()

    mock_client = _mock_anthropic(score=90)

    with patch("jobpipe.filter.load_all_candidates") as mock_cands:
        mock_cands.return_value = {"engineer": _engineer_profile()}
        counts = run_filter(session, client=mock_client, posting_ids=[posting.id])

    assert counts["llm_scored"] == 0
    # Score should not have changed
    session.refresh(match)
    assert match.score == 75.0
