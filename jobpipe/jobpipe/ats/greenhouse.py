"""Greenhouse ATS adapter.

Public API: GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from jobpipe.ats.base import ATSAdapter
from jobpipe.models import JobPosting

logger = logging.getLogger(__name__)

_API_BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class _StripHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return " ".join(chunk.strip() for chunk in self._chunks if chunk.strip())


def _strip_html(html: str) -> str:
    parser = _StripHTML()
    parser.feed(html)
    return parser.get_text()


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


class GreenhouseAdapter(ATSAdapter):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, board_token: str) -> list[JobPosting]:
        url = _API_BASE.format(token=board_token)
        try:
            resp = await self._client.get(url, params={"content": "true"})
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("Greenhouse %s HTTP %s", board_token, e.response.status_code)
            return []
        except httpx.RequestError as e:
            logger.warning("Greenhouse %s request error: %s", board_token, e)
            return []

        data = resp.json()
        jobs = data.get("jobs", [])
        postings: list[JobPosting] = []
        for job in jobs:
            jd_html = job.get("content", "") or ""
            postings.append(
                JobPosting(
                    ats_job_id=str(job["id"]),
                    title=job.get("title", ""),
                    location=_extract_location(job),
                    department=_extract_department(job),
                    url=job.get("absolute_url", ""),
                    jd_text=_strip_html(jd_html) if jd_html else None,
                    posted_at=_parse_date(job.get("updated_at")),
                    raw=job,
                )
            )
        logger.info("Greenhouse %s: fetched %d postings", board_token, len(postings))
        return postings


def _extract_location(job: dict) -> str | None:
    loc = job.get("location", {})
    if isinstance(loc, dict):
        return loc.get("name")
    return str(loc) if loc else None


def _extract_department(job: dict) -> str | None:
    depts = job.get("departments", [])
    if depts and isinstance(depts, list):
        return depts[0].get("name")
    return None
