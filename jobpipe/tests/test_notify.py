"""Tests for the notify module."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobpipe.models import Company, Draft, Match, MatchStatus, Posting
from jobpipe.notify import MatchRow, build_digest, run_notify, write_digest_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_match(session, score=85, candidate="engineer", company_name="NotifyCo") -> Match:
    company = Company(
        name=company_name,
        candidate=candidate,
        careers_url="https://notifyco.com",
        active=True,
        ats_resolved=True,
    )
    session.add(company)
    session.flush()

    now = datetime.now(timezone.utc)
    posting = Posting(
        company_id=company.id,
        ats_job_id=f"n-{id(company_name)}",
        title="Senior Engineer",
        location="Seattle, WA",
        jd_text="Python",
        url="https://notifyco.com/jobs/1",
        first_seen=now,
        last_seen=now,
    )
    session.add(posting)
    session.flush()

    match = Match(
        posting_id=posting.id,
        candidate=candidate,
        score=float(score),
        reason="Good match",
        status=MatchStatus.new.value,
    )
    session.add(match)
    session.flush()
    return match


# ---------------------------------------------------------------------------
# build_digest
# ---------------------------------------------------------------------------


def test_build_digest_renders_matches():
    rows = [
        MatchRow(
            score=90,
            company="Stripe",
            title="Senior Engineer",
            location="Seattle, WA",
            reason="Strong Python match",
            jd_url="https://stripe.com/jobs/1",
            draft_path="/tmp/drafts/stripe-1",
        )
    ]
    html = build_digest(rows, "Engineer Candidate")
    assert "Stripe" in html
    assert "Senior Engineer" in html
    assert "Strong Python match" in html
    assert "90" in html


def test_build_digest_sorted_by_score():
    rows = [
        MatchRow(score=70, company="B", title="T", location=None, reason="ok", jd_url="", draft_path=None),
        MatchRow(score=95, company="A", title="T", location=None, reason="great", jd_url="", draft_path=None),
        MatchRow(score=80, company="C", title="T", location=None, reason="good", jd_url="", draft_path=None),
    ]
    html = build_digest(rows, "Candidate")
    pos_a = html.index(">A<")
    pos_b = html.index(">B<")
    pos_c = html.index(">C<")
    assert pos_a < pos_c < pos_b  # sorted 95, 80, 70


def test_build_digest_empty():
    html = build_digest([], "Candidate")
    assert "0 new matches" in html or "0 match" in html


# ---------------------------------------------------------------------------
# run_notify
# ---------------------------------------------------------------------------


def test_run_notify_dry_run_no_smtp(session):
    match = _setup_match(session, score=85, candidate="engineer", company_name="DryRunCo")
    session.commit()

    with patch("jobpipe.notify.load_all_candidates") as mock_cands, \
         patch("jobpipe.notify.load_settings") as mock_settings, \
         patch("jobpipe.notify.send_email") as mock_send:

        from jobpipe.config import CandidateProfile, EmailSettings, Settings
        profile = CandidateProfile(
            name="Engineer",
            locations=[],
            summary="",
            master_cv_path="",
            cover_letter_template_path="",
        )
        settings = MagicMock()
        settings.relevance_threshold = 70
        settings.email.recipients = {"engineer": "eng@example.com"}
        settings.email.from_address = "jobpipe@example.com"
        settings.email.subject_prefix = "[JobPipe]"
        mock_cands.return_value = {"engineer": profile}
        mock_settings.return_value = settings

        result = run_notify(session, dry_run=True)

    mock_send.assert_not_called()
    assert result.get("engineer", 0) > 0


def test_run_notify_skips_empty_candidates(session):
    # No matches in DB
    with patch("jobpipe.notify.load_all_candidates") as mock_cands, \
         patch("jobpipe.notify.load_settings") as mock_settings, \
         patch("jobpipe.notify.send_email") as mock_send:

        from jobpipe.config import CandidateProfile
        profile = CandidateProfile(name="Engineer", locations=[], summary="",
                                   master_cv_path="", cover_letter_template_path="")
        settings = MagicMock()
        settings.relevance_threshold = 70
        settings.email.recipients = {"engineer": "eng@example.com"}
        settings.email.from_address = "noreply@x.com"
        settings.email.subject_prefix = "[JP]"
        mock_cands.return_value = {"engineer": profile}
        mock_settings.return_value = settings

        result = run_notify(session, dry_run=False)

    mock_send.assert_not_called()
    assert result["engineer"] == 0


def test_write_digest_files_creates_html(session, tmp_path):
    match = _setup_match(session, score=88, company_name="FileCo")
    session.commit()

    with patch("jobpipe.notify.load_all_candidates") as mock_cands, \
         patch("jobpipe.notify.load_settings") as mock_settings, \
         patch("jobpipe.notify._DATA_DIR", tmp_path):

        from jobpipe.config import CandidateProfile
        profile = CandidateProfile(name="Engineer", locations=[], summary="",
                                   master_cv_path="", cover_letter_template_path="")
        settings = MagicMock()
        settings.relevance_threshold = 70
        mock_cands.return_value = {"engineer": profile}
        mock_settings.return_value = settings

        # Write templates dir so Jinja can find the template
        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "digest_email.html.j2").write_text(
            "{{ candidate_name }}: {% for m in matches %}{{ m.company }}{% endfor %}"
        )

        written = write_digest_files(session, output_dir=tmp_path / "digests")

    assert "engineer" in written
    html = written["engineer"].read_text()
    assert "FileCo" in html


def test_write_digest_files_skips_zero_matches(session, tmp_path):
    # No matches in DB
    with patch("jobpipe.notify.load_all_candidates") as mock_cands, \
         patch("jobpipe.notify.load_settings") as mock_settings:

        from jobpipe.config import CandidateProfile
        profile = CandidateProfile(name="Engineer", locations=[], summary="",
                                   master_cv_path="", cover_letter_template_path="")
        settings = MagicMock()
        settings.relevance_threshold = 70
        mock_cands.return_value = {"engineer": profile}
        mock_settings.return_value = settings

        written = write_digest_files(session, output_dir=tmp_path / "digests")

    assert written == {}


def test_run_notify_sends_email(session):
    match = _setup_match(session, score=88, company_name="SendCo")
    session.commit()

    with patch("jobpipe.notify.load_all_candidates") as mock_cands, \
         patch("jobpipe.notify.load_settings") as mock_settings, \
         patch("jobpipe.notify.send_email") as mock_send:

        from jobpipe.config import CandidateProfile
        profile = CandidateProfile(name="Engineer", locations=[], summary="",
                                   master_cv_path="", cover_letter_template_path="")
        settings = MagicMock()
        settings.relevance_threshold = 70
        settings.email.recipients = {"engineer": "eng@example.com"}
        settings.email.from_address = "noreply@x.com"
        settings.email.subject_prefix = "[JP]"
        mock_cands.return_value = {"engineer": profile}
        mock_settings.return_value = settings

        result = run_notify(session, dry_run=False)

    mock_send.assert_called_once()
    call_args = mock_send.call_args
    assert call_args[0][0] == "eng@example.com"
    assert "[JP]" in call_args[0][1]
    assert result["engineer"] == 1
