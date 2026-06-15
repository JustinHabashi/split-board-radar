"""Tests for the tailoring module — all LLM calls are mocked."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobpipe.config import CandidateProfile
from jobpipe.models import Company, Draft, Match, MatchStatus, Posting
from jobpipe.tailor import (
    _format_prefs,
    _truncate_jd,
    draft_output_dir,
    generate_cover_letter,
    generate_cv,
    run_tailor,
    save_draft,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_company(session, name="TailorCo", candidate="engineer") -> Company:
    c = Company(
        name=name,
        candidate=candidate,
        careers_url="https://tailorco.com",
        ats="greenhouse",
        board_token="tailorco",
        active=True,
        ats_resolved=True,
    )
    session.add(c)
    session.flush()
    return c


def _make_match(session, score=85, candidate="engineer", company_name="TailorCo") -> Match:
    company = session.query(Company).filter_by(name=company_name).first()
    if company is None:
        company = _make_company(session, name=company_name, candidate=candidate)

    now = datetime.now(timezone.utc)
    posting = Posting(
        company_id=company.id,
        ats_job_id=f"tailor-{id(company_name)}",
        title="Senior Engineer",
        location="Seattle, WA",
        jd_text="Python distributed backend fintech",
        url="https://tailorco.com/jobs/1",
        first_seen=now,
        last_seen=now,
    )
    session.add(posting)
    session.flush()

    match = Match(
        posting_id=posting.id,
        candidate=candidate,
        score=score,
        reason="Good fit",
        status=MatchStatus.new.value,
    )
    session.add(match)
    session.flush()
    return match


def _mock_client(cv_text="# Tailored CV\n", cover_paragraphs: dict | None = None):
    if cover_paragraphs is None:
        cover_paragraphs = {
            "opening_paragraph": "I am writing to express my interest.",
            "body_paragraph_1": "My experience in Python is extensive.",
            "body_paragraph_2": "I would be a strong addition to your team.",
            "closing_paragraph": "Thank you for your consideration.",
        }

    client = MagicMock()
    call_count = 0

    def create_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        # First call = CV, second = cover letter
        if call_count == 1:
            resp.content = [MagicMock(text=cv_text)]
        else:
            resp.content = [MagicMock(text=json.dumps(cover_paragraphs))]
        return resp

    client.messages.create.side_effect = create_side_effect
    return client


def _engineer_profile() -> CandidateProfile:
    return CandidateProfile(
        name="Engineer",
        locations=["Seattle, WA"],
        must_have_keywords=["python"],
        nice_to_have_keywords=[],
        exclude_keywords=[],
        summary="Senior backend engineer with Python expertise.",
        master_cv_path="master_cv/engineer_cv.md",
        cover_letter_template_path="templates/engineer_cover_letter.md.j2",
        formatting_preferences=["no em dashes", "formal tone"],
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_format_prefs():
    profile = _engineer_profile()
    result = _format_prefs(profile)
    assert "no em dashes" in result
    assert result.startswith("- ")


def test_truncate_jd_short():
    assert _truncate_jd("short text") == "short text"


def test_truncate_jd_long():
    long = "x" * 6000
    result = _truncate_jd(long, max_chars=5000)
    assert "truncated" in result
    assert len(result) < 6000


def test_generate_cv_calls_api():
    posting = MagicMock()
    posting.title = "Senior Engineer"
    posting.jd_text = "Python backend"
    posting.company.name = "TailorCo"
    profile = _engineer_profile()

    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="# Tailored CV\n")]
    )

    result = generate_cv(posting, profile, client)
    assert "# Tailored CV" in result
    assert client.messages.create.called


def test_generate_cover_letter_renders_template(tmp_path):
    posting = MagicMock()
    posting.title = "Senior Engineer"
    posting.jd_text = "Python backend"
    posting.company.name = "TailorCo"

    # Write a minimal template
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir()
    (tmpl_dir / "engineer_cover_letter.md.j2").write_text(
        "{{ date }}\n{{ company_name }}\n{{ opening_paragraph }}\n"
    )

    profile = _engineer_profile()
    profile = profile.model_copy(
        update={"cover_letter_template_path": "templates/engineer_cover_letter.md.j2"}
    )

    paragraphs = {
        "opening_paragraph": "I am excited to apply.",
        "body_paragraph_1": "Background here.",
        "body_paragraph_2": "More background.",
        "closing_paragraph": "Thank you.",
    }
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(paragraphs))]
    )

    with patch("jobpipe.tailor._DATA_DIR", tmp_path):
        result = generate_cover_letter(posting, profile, client)

    assert "TailorCo" in result
    assert "I am excited to apply." in result


def test_generate_cover_letter_fallback_on_bad_json():
    posting = MagicMock()
    posting.title = "Senior Engineer"
    posting.jd_text = "Python"
    posting.company.name = "TailorCo"
    profile = _engineer_profile()

    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Not valid JSON at all")]
    )

    with patch("jobpipe.tailor._DATA_DIR", Path("/nonexistent")):
        result = generate_cover_letter(posting, profile, client)
    # Should not raise; returns something
    assert result is not None


# ---------------------------------------------------------------------------
# save_draft
# ---------------------------------------------------------------------------


def test_save_draft_writes_files(session, tmp_path):
    match = _make_match(session)
    session.commit()

    with patch("jobpipe.tailor._DATA_DIR", tmp_path):
        draft = save_draft(session, match, "# CV Content", "Cover letter content")
        session.commit()

    assert draft.id is not None
    assert draft.cv_path is not None
    assert Path(draft.cv_path).read_text() == "# CV Content"
    assert Path(draft.cover_letter_path).read_text() == "Cover letter content"
    assert match.status == MatchStatus.drafted.value


# ---------------------------------------------------------------------------
# run_tailor
# ---------------------------------------------------------------------------


def test_run_tailor_creates_drafts(session, tmp_path):
    match = _make_match(session, score=85, company_name="RunTailorCo")
    session.commit()

    client = _mock_client()

    with patch("jobpipe.tailor.load_all_candidates") as mock_cands, \
         patch("jobpipe.tailor._DATA_DIR", tmp_path):
        mock_cands.return_value = {"engineer": _engineer_profile()}
        count = run_tailor(session, client=client, match_ids=[match.id])

    assert count == 1
    session.refresh(match)
    assert match.status == MatchStatus.drafted.value

    draft = session.query(Draft).filter_by(match_id=match.id).first()
    assert draft is not None
    assert Path(draft.cv_path).exists()
    assert Path(draft.cover_letter_path).exists()


def test_run_tailor_skips_below_threshold(session, tmp_path):
    match = _make_match(session, score=50, company_name="LowScoreCo")
    session.commit()

    client = _mock_client()

    with patch("jobpipe.tailor.load_all_candidates") as mock_cands, \
         patch("jobpipe.tailor._DATA_DIR", tmp_path):
        mock_cands.return_value = {"engineer": _engineer_profile()}
        count = run_tailor(session, client=client, match_ids=[match.id])

    assert count == 0


def test_run_tailor_skips_already_drafted(session, tmp_path):
    match = _make_match(session, score=85, company_name="AlreadyDraftedCo")
    match.status = MatchStatus.drafted.value
    session.commit()

    client = _mock_client()

    with patch("jobpipe.tailor.load_all_candidates") as mock_cands, \
         patch("jobpipe.tailor._DATA_DIR", tmp_path):
        mock_cands.return_value = {"engineer": _engineer_profile()}
        count = run_tailor(session, client=client, match_ids=[match.id])

    assert count == 0
