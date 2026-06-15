"""Tests for Pydantic models and SQLAlchemy ORM."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobpipe.models import (
    ATSType,
    CandidateEnum,
    Company,
    CompanyRow,
    Draft,
    JobPosting,
    Match,
    MatchResult,
    MatchStatus,
    Posting,
)


class TestCompanyRow:
    def test_valid_row(self):
        row = CompanyRow(
            name="Stripe",
            candidate="engineer",
            careers_url="https://stripe.com/jobs",
            ats="greenhouse",
            board_token="stripe",
            active=True,
        )
        assert row.candidate == CandidateEnum.engineer
        assert row.ats == ATSType.greenhouse

    def test_unknown_ats_coerced(self):
        row = CompanyRow(
            name="Acme",
            candidate="both",
            careers_url="https://acme.com/careers",
            ats="someweirdats",
            active=True,
        )
        assert row.ats == ATSType.unknown

    def test_question_mark_ats_becomes_none(self):
        row = CompanyRow(
            name="Acme",
            candidate="scientist",
            careers_url="https://acme.com",
            ats="?",
            active=True,
        )
        assert row.ats is None

    def test_active_bool_coercion(self):
        row = CompanyRow(
            name="X",
            candidate="engineer",
            careers_url="https://x.com",
            active="true",
        )
        assert row.active is True

        row2 = CompanyRow(
            name="Y",
            candidate="engineer",
            careers_url="https://y.com",
            active="false",
        )
        assert row2.active is False


class TestJobPosting:
    def test_strips_whitespace(self):
        p = JobPosting(
            ats_job_id="  123  ",
            title="  Engineer  ",
            url="  https://example.com/jobs/123  ",
        )
        assert p.ats_job_id == "123"
        assert p.title == "Engineer"
        assert p.url == "https://example.com/jobs/123"

    def test_optional_fields_default_none(self):
        p = JobPosting(ats_job_id="1", title="Dev", url="https://x.com")
        assert p.location is None
        assert p.jd_text is None
        assert p.posted_at is None


class TestMatchResult:
    def test_score_clamped(self):
        r = MatchResult(score=150, reason="test")
        assert r.score == 100

        r2 = MatchResult(score=-10, reason="test")
        assert r2.score == 0

    def test_normal_score(self):
        r = MatchResult(score=85, reason="good match")
        assert r.score == 85


class TestORM:
    def test_create_company(self, session):
        c = Company(
            name="TestCo",
            candidate=CandidateEnum.engineer.value,
            careers_url="https://testco.com/careers",
        )
        session.add(c)
        session.commit()
        assert c.id is not None

        fetched = session.query(Company).filter_by(name="TestCo").one()
        assert fetched.active is True
        assert fetched.ats_resolved is False

    def test_posting_unique_constraint(self, session):
        from sqlalchemy.exc import IntegrityError

        c = Company(
            name="DupeCo",
            candidate="engineer",
            careers_url="https://dupeco.com",
        )
        session.add(c)
        session.commit()

        now = datetime.now(timezone.utc)
        p1 = Posting(
            company_id=c.id,
            ats_job_id="job-1",
            title="SWE",
            url="https://dupeco.com/jobs/1",
            first_seen=now,
            last_seen=now,
        )
        p2 = Posting(
            company_id=c.id,
            ats_job_id="job-1",
            title="SWE duplicate",
            url="https://dupeco.com/jobs/1",
            first_seen=now,
            last_seen=now,
        )
        session.add(p1)
        session.commit()
        session.add(p2)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_match_cascade(self, session):
        now = datetime.now(timezone.utc)
        c = Company(name="CasCo", candidate="both", careers_url="https://casco.com")
        session.add(c)
        session.commit()

        p = Posting(
            company_id=c.id,
            ats_job_id="j1",
            title="Role",
            url="https://casco.com/jobs/1",
            first_seen=now,
            last_seen=now,
        )
        session.add(p)
        session.commit()

        m = Match(
            posting_id=p.id,
            candidate=CandidateEnum.engineer.value,
            score=80.0,
            reason="good",
            status=MatchStatus.new.value,
        )
        session.add(m)
        session.commit()

        d = Draft(match_id=m.id, cv_path="/tmp/cv.md", generated_at=now)
        session.add(d)
        session.commit()

        # Cascade delete
        session.delete(c)
        session.commit()
        assert session.query(Posting).count() == 0
        assert session.query(Match).count() == 0
        assert session.query(Draft).count() == 0
