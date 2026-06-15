"""Two-stage posting filter.

Stage 1 (cheap): keyword + location — no LLM.
Stage 2 (expensive): LLM relevance scoring — one Claude call per posting per candidate.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from anthropic import Anthropic
from sqlalchemy.orm import Session

from jobpipe.config import CandidateProfile, load_all_candidates, load_settings
from jobpipe.models import CandidateEnum, Match, MatchResult, MatchStatus, Posting

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage 1: keyword + location filter
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    return text.lower()


def passes_location_filter(location: str | None, profile: CandidateProfile) -> bool:
    """Return True if the location string matches the candidate's target locations.

    None/empty location is treated as a pass (could be remote/unspecified).
    """
    if not location:
        return True

    settings = load_settings()
    loc = _normalize(location)

    for alias in settings.filtering.location_aliases:
        if alias.lower() in loc:
            return True
    for pattern in settings.filtering.remote_patterns:
        if pattern.lower() in loc:
            return True
    for candidate_loc in profile.locations:
        if candidate_loc.lower() in loc:
            return True
    return False


def passes_keyword_filter(posting: Posting, profile: CandidateProfile) -> bool:
    """Return True if the posting survives the cheap keyword/location pre-filter."""
    title_loc = _normalize(f"{posting.title or ''} {posting.location or ''}")
    jd = _normalize(posting.jd_text or "")
    combined = f"{title_loc} {jd}"

    # Hard exclusions — if any match, skip immediately
    for kw in profile.exclude_keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", combined):
            logger.debug("Posting %s excluded by keyword '%s'", posting.id, kw)
            return False

    # Location check using shared function
    if not passes_location_filter(posting.location, profile):
        logger.debug(
            "Posting %s filtered out by location: '%s'", posting.id, posting.location
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Stage 2: LLM relevance scoring
# ---------------------------------------------------------------------------

_SCORE_SYSTEM = """\
You are an expert recruiting assistant. Given a job description and a candidate profile,
return ONLY valid JSON with exactly two keys: "score" (integer 0-100) and "reason" (one sentence).
Do not include any text outside the JSON object.
"""

_SCORE_PROMPT = """\
## Candidate Profile
{profile_summary}

## Job Title
{title}

## Job Description
{jd_text}

Rate how well this job matches the candidate. Respond with ONLY JSON:
{{"score": <0-100>, "reason": "<one sentence>"}}
"""

_MAX_JD_CHARS = 6000  # Truncate very long JDs to control token usage


def _truncate_jd(jd: Optional[str]) -> str:
    if not jd:
        return "(no job description available)"
    if len(jd) > _MAX_JD_CHARS:
        return jd[:_MAX_JD_CHARS] + "\n... [truncated]"
    return jd


def score_posting(
    posting: Posting,
    candidate_key: str,
    profile: CandidateProfile,
    client: Anthropic,
) -> MatchResult:
    """Call the LLM to score the posting for this candidate. Returns MatchResult."""
    settings = load_settings()
    prompt = _SCORE_PROMPT.format(
        profile_summary=profile.summary,
        title=posting.title,
        jd_text=_truncate_jd(posting.jd_text),
    )

    response = client.messages.create(
        model=settings.tailoring.model,
        max_tokens=256,
        system=_SCORE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    # Strip markdown code fences if the model wraps the JSON
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        return MatchResult.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "LLM returned non-JSON for posting %s / %s: %s — raw: %r",
            posting.id,
            candidate_key,
            e,
            raw[:200],
        )
        return MatchResult(score=0, reason=f"Parse error: {e}")


# ---------------------------------------------------------------------------
# Persist and orchestrate
# ---------------------------------------------------------------------------


def upsert_match(
    session: Session,
    posting: Posting,
    candidate_key: str,
    result: MatchResult,
) -> Match:
    """Insert or update a Match row. Returns the ORM object."""
    existing = (
        session.query(Match)
        .filter_by(posting_id=posting.id, candidate=candidate_key)
        .first()
    )
    if existing:
        existing.score = result.score
        existing.reason = result.reason
        return existing
    match = Match(
        posting_id=posting.id,
        candidate=candidate_key,
        score=result.score,
        reason=result.reason,
        status=MatchStatus.new.value,
    )
    session.add(match)
    return match


def run_filter(
    session: Session,
    client: Optional[Anthropic] = None,
    posting_ids: Optional[list[int]] = None,
) -> dict[str, int]:
    """
    Run both filter stages for all unscored postings (or a subset by id).

    Returns counts: {"keyword_passed": N, "llm_scored": N, "above_threshold": N}
    """
    settings = load_settings()
    candidates = load_all_candidates()

    if client is None:
        client = Anthropic()

    query = session.query(Posting)
    if posting_ids is not None:
        query = query.filter(Posting.id.in_(posting_ids))
    postings = query.all()

    counts = {"keyword_passed": 0, "llm_scored": 0, "above_threshold": 0}

    for posting in postings:
        company = posting.company
        if company is None:
            continue

        # Determine which candidates to score for this posting
        if company.candidate == CandidateEnum.both.value:
            candidate_keys = list(candidates.keys())
        else:
            candidate_keys = [c for c in candidates if c == company.candidate]

        for candidate_key in candidate_keys:
            profile = candidates.get(candidate_key)
            if profile is None:
                continue

            # Skip if already scored
            existing = (
                session.query(Match)
                .filter_by(posting_id=posting.id, candidate=candidate_key)
                .first()
            )
            if existing and existing.score is not None:
                continue

            # Stage 1
            if not passes_keyword_filter(posting, profile):
                continue
            counts["keyword_passed"] += 1

            # Stage 2
            result = score_posting(posting, candidate_key, profile, client)
            counts["llm_scored"] += 1
            upsert_match(session, posting, candidate_key, result)
            session.commit()  # persist each score immediately so a mid-run crash loses no progress

            if result.score >= settings.relevance_threshold:
                counts["above_threshold"] += 1
                logger.info(
                    "MATCH score=%d %s / %s — %s",
                    result.score,
                    company.name,
                    posting.title,
                    result.reason,
                )

    return counts
