"""Ingest: load companies from DB, poll ATS adapters, diff and persist new postings."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from jobpipe.config import load_companies_csv
from jobpipe.models import ATSType, Company, CompanyRow, JobPosting, Posting

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Company seeding
# ---------------------------------------------------------------------------


def seed_companies(session: Session) -> int:
    """Upsert companies from companies.csv into the database. Returns count inserted."""
    rows = load_companies_csv()
    inserted = 0
    for row in rows:
        existing = session.query(Company).filter_by(name=row.name).first()
        if existing is None:
            company = _company_from_row(row)
            session.add(company)
            inserted += 1
            logger.debug("Inserted company: %s", row.name)
        else:
            # CSV is always authoritative for ATS type and token.
            # ats_resolved tracks whether the live resolver has confirmed/corrected
            # the value; re-seeding from CSV resets that so the resolver won't re-run
            # on companies whose values we just explicitly set.
            existing.sector = row.sector
            existing.careers_url = row.careers_url
            existing.active = row.active
            existing.ats = row.ats.value if row.ats else None
            existing.board_token = row.board_token
            # Mark as resolved when CSV provides a known ATS; leave unresolved for ?/unknown
            has_known_ats = row.ats is not None and row.ats.value not in ("unknown",)
            existing.ats_resolved = has_known_ats
    return inserted


def _company_from_row(row: CompanyRow) -> Company:
    return Company(
        name=row.name,
        candidate=row.candidate.value,
        sector=row.sector,
        careers_url=row.careers_url,
        ats=row.ats.value if row.ats else None,
        board_token=row.board_token,
        active=row.active,
        ats_resolved=False,
    )


# ---------------------------------------------------------------------------
# Posting upsert
# ---------------------------------------------------------------------------


def content_hash(posting: JobPosting) -> str:
    blob = f"{posting.title}|{posting.location}|{posting.jd_text or ''}"
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def upsert_posting(
    session: Session,
    company: Company,
    posting: JobPosting,
) -> tuple[Posting, bool]:
    """Insert or update a posting. Returns (orm_posting, is_new)."""
    now = datetime.now(timezone.utc)
    existing = (
        session.query(Posting)
        .filter_by(company_id=company.id, ats_job_id=posting.ats_job_id)
        .first()
    )
    chash = content_hash(posting)
    if existing is None:
        orm = Posting(
            company_id=company.id,
            ats_job_id=posting.ats_job_id,
            title=posting.title,
            location=posting.location,
            department=posting.department,
            url=posting.url,
            jd_text=posting.jd_text,
            posted_at=posting.posted_at,
            first_seen=now,
            last_seen=now,
            content_hash=chash,
        )
        session.add(orm)
        return orm, True
    else:
        existing.last_seen = now
        existing.content_hash = chash
        existing.title = posting.title
        existing.location = posting.location
        existing.jd_text = posting.jd_text
        return existing, False


# ---------------------------------------------------------------------------
# ATS adapter factory
# ---------------------------------------------------------------------------


def _make_http_client() -> httpx.AsyncClient:
    from jobpipe.config import load_settings
    settings = load_settings()
    return httpx.AsyncClient(
        headers={"User-Agent": settings.http.user_agent},
        timeout=settings.http.timeout_seconds,
        follow_redirects=True,
    )


def _get_adapter(ats: Optional[str], client: httpx.AsyncClient):
    """Return the appropriate ATSAdapter for the given ats string, or None."""
    if ats == ATSType.greenhouse.value:
        from jobpipe.ats.greenhouse import GreenhouseAdapter
        return GreenhouseAdapter(client)
    if ats == ATSType.lever.value:
        from jobpipe.ats.lever import LeverAdapter
        return LeverAdapter(client)
    if ats == ATSType.ashby.value:
        from jobpipe.ats.ashby import AshbyAdapter
        return AshbyAdapter(client)
    if ats == ATSType.workday.value:
        from jobpipe.ats.workday import WorkdayAdapter
        return WorkdayAdapter(client)
    return None


# ---------------------------------------------------------------------------
# Resolve unresolved companies
# ---------------------------------------------------------------------------


async def resolve_companies(session: Session) -> int:
    """Run the resolver on companies that have not been resolved yet. Returns count resolved."""
    from jobpipe.ats.resolver import resolve_careers_url

    unresolved = (
        session.query(Company)
        .filter_by(ats_resolved=False, active=True)
        .all()
    )
    if not unresolved:
        return 0

    resolved_count = 0
    async with _make_http_client() as client:
        for company in unresolved:
            ats, token = await resolve_careers_url(company.careers_url, client)
            if ats != ATSType.unknown:
                company.ats = ats.value
                company.board_token = token
                company.ats_resolved = True
                resolved_count += 1
                logger.info(
                    "Resolved %s -> ats=%s token=%s", company.name, ats.value, token
                )
            else:
                # Mark resolved even on failure so we don't retry daily
                company.ats_resolved = True
                logger.info("Could not resolve ATS for %s", company.name)
    return resolved_count


# ---------------------------------------------------------------------------
# Poll all active companies
# ---------------------------------------------------------------------------


async def poll_company(
    company: Company, client: httpx.AsyncClient, session: Session
) -> tuple[int, int]:
    """Poll one company and upsert postings. Returns (new, updated)."""
    if not company.board_token or not company.ats:
        logger.debug("Skipping %s: no board_token/ats", company.name)
        return 0, 0

    adapter = _get_adapter(company.ats, client)
    if adapter is None:
        logger.debug("No adapter for ats=%s (%s)", company.ats, company.name)
        return 0, 0

    postings = await adapter.fetch(company.board_token)

    # Location pre-filter: drop jobs whose location is explicitly outside target areas.
    # Jobs with no location listed pass through (assumed remote/unspecified).
    postings = _filter_by_location(postings, company)
    if not postings:
        logger.debug("%s: all postings filtered out by location", company.name)
        return 0, 0

    new_count = updated_count = 0
    for p in postings:
        _, is_new = upsert_posting(session, company, p)
        if is_new:
            new_count += 1
        else:
            updated_count += 1
    return new_count, updated_count


def _filter_by_location(postings: list, company: Company) -> list:
    """Keep only postings whose location matches any relevant candidate's targets."""
    from jobpipe.config import load_all_candidates
    from jobpipe.filter import passes_location_filter

    candidates = load_all_candidates()
    if company.candidate == ATSType.unknown.value:
        profiles = list(candidates.values())
    elif company.candidate == "both":
        profiles = list(candidates.values())
    else:
        profiles = [candidates[company.candidate]] if company.candidate in candidates else list(candidates.values())

    kept = [p for p in postings if any(passes_location_filter(p.location, prof) for prof in profiles)]
    dropped = len(postings) - len(kept)
    if dropped:
        logger.info("Location filter: kept %d / %d postings for %s", len(kept), len(postings), company.name)
    return kept


async def poll_all(session: Session) -> dict[str, tuple[int, int]]:
    """Poll all active companies with a resolved ATS. Returns {company_name: (new, updated)}."""
    from jobpipe.config import load_settings
    settings = load_settings()

    companies = (
        session.query(Company)
        .filter_by(active=True, ats_resolved=True)
        .all()
    )

    results: dict[str, tuple[int, int]] = {}
    delay = 1.0 / max(settings.rate_limits.requests_per_second, 0.1)

    async with _make_http_client() as client:
        for company in companies:
            new, updated = await poll_company(company, client, session)
            results[company.name] = (new, updated)
            if new or updated:
                logger.info("%s: %d new, %d updated postings", company.name, new, updated)
            await asyncio.sleep(delay)

    return results


def run_ingest(session: Session) -> dict[str, tuple[int, int]]:
    """Synchronous entry point for the ingest stage."""
    return asyncio.run(poll_all(session))
