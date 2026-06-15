"""Ashby ATS adapter.

Public API:
  GET https://api.ashbyhq.com/posting-api/job-board/{token}
  GET https://api.ashbyhq.com/posting-api/job-board/{token}/job/{job_id}  (for full JD)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from jobpipe.ats.base import ATSAdapter
from jobpipe.models import JobPosting

logger = logging.getLogger(__name__)

_BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def _strip_html(html: str) -> str:
    class _S(HTMLParser):
        def __init__(self):
            super().__init__()
            self._chunks: list[str] = []

        def handle_data(self, data: str) -> None:
            self._chunks.append(data)

        def text(self) -> str:
            return " ".join(c.strip() for c in self._chunks if c.strip())

    p = _S()
    p.feed(html)
    return p.text()


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class AshbyAdapter(ATSAdapter):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, board_token: str) -> list[JobPosting]:
        url = _BOARD_URL.format(token=board_token)
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("Ashby %s HTTP %s", board_token, e.response.status_code)
            return []
        except httpx.RequestError as e:
            logger.warning("Ashby %s request error: %s", board_token, e)
            return []

        data = resp.json()
        jobs = data.get("jobs", [])

        result = [self._normalize(job) for job in jobs]
        logger.info("Ashby %s: fetched %d postings", board_token, len(result))
        return result

    def _normalize(self, job: dict) -> JobPosting:
        jd_raw = job.get("descriptionHtml") or job.get("descriptionSafeHtml") or None
        jd_text = _strip_html(jd_raw) if jd_raw else None
        return JobPosting(
            ats_job_id=job.get("id", ""),
            title=job.get("title", ""),
            location=job.get("locationName") or job.get("location"),
            department=job.get("departmentName") or job.get("department"),
            url=job.get("jobUrl", ""),
            jd_text=jd_text,
            posted_at=_parse_date(job.get("publishedAt")),
            raw=job,
        )
