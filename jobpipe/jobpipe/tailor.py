"""Tailoring module: generate review-ready CV + cover letter drafts for high-scoring matches.

Key constraints (enforced via prompt instructions):
- Do NOT fabricate experience. Only re-emphasize and reorder existing CV content.
- No em dashes (engineer profile preference).
- Formal tone; no contractions in cover letters.
- Output Markdown.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from sqlalchemy.orm import Session

from jobpipe.config import CandidateProfile, load_all_candidates, load_settings
from jobpipe.models import Draft, Match, MatchStatus, Posting

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_CV_SYSTEM = """\
You are an expert resume writer assisting with a job application. Your task is to produce a
tailored version of the candidate's CV that emphasizes the most relevant experience and skills
for the given job description.

STRICT RULES:
1. Do NOT fabricate, invent, or embellish any experience, skills, project, or metric.
   Only reorder, rephrase, or emphasize content that already exists in the master CV.
2. Do not remove any role or position.
3. Output valid Markdown.
4. Apply these formatting preferences exactly:
{formatting_prefs}
"""

_CV_PROMPT = """\
## Job Title
{title}

## Company
{company}

## Job Description
{jd_text}

## Master CV (source of truth — use only this content)
{master_cv}

Produce a tailored CV in Markdown. Reorder bullet points and sections to lead with the most
relevant experience for this specific role. Rephrase bullets to use keywords from the JD where
accurate. Do not add anything not in the master CV.
"""

_COVER_LETTER_SYSTEM = """\
You are an expert cover letter writer. Your task is to write a compelling, tailored cover letter
using the candidate's actual background. Follow these rules:

1. Formal tone. No contractions.
2. No em dashes (use commas or semicolons instead).
3. Three body paragraphs: (1) why this company/role, (2) most relevant experience, (3) fit/close.
4. Be specific and concrete; reference actual experience from the candidate profile.
5. Do not fabricate experience.
6. Output the cover letter content as structured JSON with these keys:
   opening_paragraph, body_paragraph_1, body_paragraph_2, closing_paragraph
   Return ONLY the JSON object, no additional text.
"""

_COVER_LETTER_PROMPT = """\
## Job Title
{title}

## Company
{company}

## Job Description
{jd_text}

## Candidate Profile Summary
{profile_summary}

## Candidate's Formatting Preferences
{formatting_prefs}

Write the cover letter paragraphs as JSON.
"""


# ---------------------------------------------------------------------------
# Draft generation
# ---------------------------------------------------------------------------


def _load_master_cv(profile: CandidateProfile) -> str:
    cv_path = _DATA_DIR / profile.master_cv_path
    if not cv_path.exists():
        logger.warning("Master CV not found at %s", cv_path)
        return "(master CV not available — please add it to data/master_cv/)"
    return cv_path.read_text(encoding="utf-8")


def _format_prefs(profile: CandidateProfile) -> str:
    if not profile.formatting_preferences:
        return "- No specific preferences"
    return "\n".join(f"- {p}" for p in profile.formatting_preferences)


def _truncate_jd(jd: Optional[str], max_chars: int = 5000) -> str:
    if not jd:
        return "(no job description provided)"
    return jd[:max_chars] + "\n... [truncated]" if len(jd) > max_chars else jd


def generate_cv(
    posting: Posting,
    profile: CandidateProfile,
    client: Anthropic,
) -> str:
    """Return tailored CV as a Markdown string."""
    settings = load_settings()
    master_cv = _load_master_cv(profile)
    system = _CV_SYSTEM.format(formatting_prefs=_format_prefs(profile))
    prompt = _CV_PROMPT.format(
        title=posting.title,
        company=posting.company.name if posting.company else "the company",
        jd_text=_truncate_jd(posting.jd_text),
        master_cv=master_cv,
    )
    response = client.messages.create(
        model=settings.tailoring.model,
        max_tokens=settings.tailoring.max_tokens,
        temperature=settings.tailoring.temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def generate_cover_letter(
    posting: Posting,
    profile: CandidateProfile,
    client: Anthropic,
) -> str:
    """Return a Markdown cover letter rendered via the Jinja template."""
    import json
    import re

    settings = load_settings()
    system = _COVER_LETTER_SYSTEM
    prompt = _COVER_LETTER_PROMPT.format(
        title=posting.title,
        company=posting.company.name if posting.company else "the company",
        jd_text=_truncate_jd(posting.jd_text),
        profile_summary=profile.summary,
        formatting_prefs=_format_prefs(profile),
    )
    response = client.messages.create(
        model=settings.tailoring.model,
        max_tokens=settings.tailoring.max_tokens,
        temperature=settings.tailoring.temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        paragraphs = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Cover letter LLM returned non-JSON; using raw output as closing paragraph")
        paragraphs = {
            "opening_paragraph": "",
            "body_paragraph_1": "",
            "body_paragraph_2": "",
            "closing_paragraph": raw,
        }

    template_path = _DATA_DIR / profile.cover_letter_template_path
    if template_path.exists():
        env = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            undefined=StrictUndefined,
        )
        tmpl = env.get_template(template_path.name)
        return tmpl.render(
            date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
            company_name=posting.company.name if posting.company else "the company",
            job_title=posting.title,
            **paragraphs,
        )

    # Fallback: plain markdown if template file is missing
    lines = [
        f"# Cover Letter: {posting.title} at {posting.company.name if posting.company else ''}",
        "",
        paragraphs.get("opening_paragraph", ""),
        "",
        paragraphs.get("body_paragraph_1", ""),
        "",
        paragraphs.get("body_paragraph_2", ""),
        "",
        paragraphs.get("closing_paragraph", ""),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persist drafts
# ---------------------------------------------------------------------------


def draft_output_dir(match: Match) -> Path:
    posting = match.posting
    company_name = posting.company.name if posting.company else "unknown"
    safe_company = "".join(c if c.isalnum() or c in "-_" else "_" for c in company_name)
    return _DATA_DIR / "drafts" / match.candidate / f"{safe_company}-{posting.id}"


def save_draft(
    session: Session,
    match: Match,
    cv_text: str,
    cover_letter_text: str,
) -> Draft:
    out_dir = draft_output_dir(match)
    out_dir.mkdir(parents=True, exist_ok=True)

    cv_path = out_dir / "cv.md"
    cl_path = out_dir / "cover_letter.md"
    cv_path.write_text(cv_text, encoding="utf-8")
    cl_path.write_text(cover_letter_text, encoding="utf-8")

    draft = Draft(
        match_id=match.id,
        cv_path=str(cv_path),
        cover_letter_path=str(cl_path),
        generated_at=datetime.now(timezone.utc),
    )
    session.add(draft)
    match.status = MatchStatus.drafted.value
    return draft


# ---------------------------------------------------------------------------
# Orchestrate
# ---------------------------------------------------------------------------


def run_tailor(
    session: Session,
    client: Optional[Anthropic] = None,
    match_ids: Optional[list[int]] = None,
) -> int:
    """Generate drafts for all new high-scoring matches. Returns count of drafts created."""
    settings = load_settings()
    candidates = load_all_candidates()

    if client is None:
        client = Anthropic()

    query = (
        session.query(Match)
        .filter(
            Match.status == MatchStatus.new.value,
            Match.score >= settings.relevance_threshold,
        )
    )
    if match_ids is not None:
        query = query.filter(Match.id.in_(match_ids))

    matches = query.all()
    drafted = 0

    for match in matches:
        profile = candidates.get(match.candidate)
        if profile is None:
            logger.warning("No profile for candidate key '%s'", match.candidate)
            continue

        posting = match.posting
        try:
            cv_text = generate_cv(posting, profile, client)
            cl_text = generate_cover_letter(posting, profile, client)
            save_draft(session, match, cv_text, cl_text)
            drafted += 1
            logger.info(
                "Drafted: %s / %s (%s)",
                posting.company.name if posting.company else "?",
                posting.title,
                match.candidate,
            )
        except Exception as e:
            logger.error("Failed to draft match %s: %s", match.id, e)

    session.commit()
    return drafted
