"""Workday ATS adapter.

Workday uses per-tenant REST endpoints. board_token is "{tenant}/{site}".

Discovery endpoint (paginated POST):
  POST https://{tenant}.wd5.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  Body: {"searchText": "", "limit": 20, "offset": 0}

The WD number suffix (wd1, wd5, wd12, etc.) varies by tenant and cannot be
reliably inferred — we try a small set of common suffixes in order.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from jobpipe.ats.base import ATSAdapter
from jobpipe.models import JobPosting

logger = logging.getLogger(__name__)

_WD_SUFFIXES = ("wd5", "wd1", "wd3", "wd12", "wd8", "wd2")
_PAGE_SIZE = 20


def _parse_date(raw: str | None) -> Optional[datetime]:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class WorkdayAdapter(ATSAdapter):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, board_token: str) -> list[JobPosting]:
        """board_token is '{tenant}/{site}'."""
        parts = board_token.split("/", 1)
        if len(parts) != 2:
            logger.warning("Workday: invalid board_token format '%s'", board_token)
            return []
        tenant, site = parts

        base_url = await self._find_base_url(tenant, site)
        if base_url is None:
            logger.warning("Workday: could not find working endpoint for %s/%s", tenant, site)
            return []

        return await self._fetch_all_pages(base_url, tenant, site)

    async def _find_base_url(self, tenant: str, site: str) -> Optional[str]:
        """Try each WD suffix until we get a 200."""
        for suffix in _WD_SUFFIXES:
            url = f"https://{tenant}.{suffix}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            try:
                resp = await self._client.post(
                    url,
                    json={"searchText": "", "limit": 1, "offset": 0, "appliedFacets": {}},
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return url
            except httpx.RequestError:
                continue
        return None

    async def _fetch_all_pages(self, url: str, tenant: str, site: str) -> list[JobPosting]:
        postings: list[JobPosting] = []
        offset = 0
        while True:
            try:
                resp = await self._client.post(
                    url,
                    json={"searchText": "", "limit": _PAGE_SIZE, "offset": offset, "appliedFacets": {}},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning("Workday %s/%s page error: %s", tenant, site, e)
                break

            data = resp.json()
            jobs = data.get("jobPostings", [])
            if not jobs:
                break

            for job in jobs:
                postings.append(_normalize(job, tenant, site))

            total = data.get("total", 0)
            offset += len(jobs)
            if offset >= total:
                break

        logger.info("Workday %s/%s: fetched %d postings", tenant, site, len(postings))
        return postings


def _normalize(job: dict, tenant: str, site: str) -> JobPosting:
    job_id = job.get("bulletFields", [None])[0] or job.get("externalPath", "").strip("/")
    external_path = job.get("externalPath", "")
    url = (
        f"https://{tenant}.wd5.myworkdayjobs.com/{site}{external_path}"
        if external_path
        else ""
    )
    return JobPosting(
        ats_job_id=job_id or external_path,
        title=job.get("title", ""),
        location=job.get("locationsText") or job.get("primaryLocation"),
        department=job.get("jobFamilyGroup") or job.get("jobCategory"),
        url=url,
        jd_text=None,  # Workday detail pages require JS rendering; JD fetched separately
        posted_at=_parse_date(job.get("postedOn")),
        raw=job,
    )
