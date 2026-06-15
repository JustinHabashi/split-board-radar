"""Tests for config loading."""

from __future__ import annotations

from jobpipe.config import (
    load_all_candidates,
    load_companies_csv,
    load_settings,
    candidates_for_company,
)
from jobpipe.models import ATSType, CandidateEnum


class TestSettings:
    def test_loads_default_threshold(self):
        s = load_settings()
        assert s.relevance_threshold == 70

    def test_schedule_cron(self):
        s = load_settings()
        assert "7" in s.schedule.cron

    def test_tailoring_model(self):
        s = load_settings()
        assert "claude" in s.tailoring.model


class TestCandidates:
    def test_loads_engineer(self):
        candidates = load_all_candidates()
        assert "engineer" in candidates
        eng = candidates["engineer"]
        assert eng.name
        assert len(eng.must_have_keywords) > 0
        assert eng.master_cv_path != ""

    def test_loads_scientist(self):
        candidates = load_all_candidates()
        assert "scientist" in candidates
        sci = candidates["scientist"]
        assert "immunology" in sci.must_have_keywords or any(
            "immunol" in kw.lower() for kw in sci.must_have_keywords
        )

    def test_formatting_preferences_engineer(self):
        candidates = load_all_candidates()
        eng = candidates["engineer"]
        prefs_lower = [p.lower() for p in eng.formatting_preferences]
        assert any("em dash" in p for p in prefs_lower)


class TestCompaniesCSV:
    def test_loads_rows(self):
        rows = load_companies_csv()
        assert len(rows) > 5

    def test_stripe_is_greenhouse(self):
        rows = load_companies_csv()
        stripe = next((r for r in rows if r.name == "Stripe"), None)
        assert stripe is not None
        assert stripe.ats == ATSType.greenhouse
        assert stripe.board_token == "stripe"

    def test_all_active_flags_are_bool(self):
        rows = load_companies_csv()
        for row in rows:
            assert isinstance(row.active, bool)

    def test_candidates_for_both(self):
        rows = load_companies_csv()
        microsoft = next((r for r in rows if r.name == "Microsoft"), None)
        assert microsoft is not None
        assert microsoft.candidate == CandidateEnum.both
        cands = candidates_for_company(microsoft)
        assert set(cands) == {"engineer", "scientist"}

    def test_candidates_for_engineer_only(self):
        rows = load_companies_csv()
        stripe = next((r for r in rows if r.name == "Stripe"), None)
        assert stripe is not None
        cands = candidates_for_company(stripe)
        assert cands == ["engineer"]


class TestIngestSeed:
    def test_seed_companies(self, session):
        from jobpipe.ingest import seed_companies
        from jobpipe.models import Company

        count = seed_companies(session)
        session.commit()
        assert count > 0

        total = session.query(Company).count()
        assert total == count

    def test_seed_is_idempotent(self, session):
        from jobpipe.ingest import seed_companies
        from jobpipe.models import Company

        first = seed_companies(session)
        session.commit()
        second = seed_companies(session)
        session.commit()

        assert second == 0  # no new insertions on second run
        assert session.query(Company).count() == first
