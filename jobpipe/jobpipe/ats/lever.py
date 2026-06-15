"""Lever ATS adapter.

Public API: GET https://api.lever.co/v0/postings/{token}?mode=json
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from jobpipe.ats.base import ATSAdapter
from jobpipe.models import JobPosting

logger = logging.getLogger(__name__)

_API_BASE = "https://api.lever.co/v0/postings/{token}"


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


def _parse_ms_timestamp(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class LeverAdapter(ATSAdapter):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, board_token: str) -> list[JobPosting]:
        url = _API_BASE.format(token=board_token)
        try:
            resp = await self._client.get(url, params={"mode": "json"})
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("Lever %s HTTP %s", board_token, e.response.status_code)
            return []
        except httpx.RequestError as e:
            logger.warning("Lever %s request error: %s", board_token, e)
            return []

        jobs = resp.json()
        if not isinstance(jobs, list):
            logger.warning("Lever %s: unexpected response shape", board_token)
            return []

        postings: list[JobPosting] = []
        for job in jobs:
            # descriptionBody can be a dict with nested sections OR a raw HTML string
            desc_body = job.get("descriptionBody")
            jd_html = ""
            if isinstance(desc_body, dict):
                for section in desc_body.get("descriptionBody", []):
                    if isinstance(section, dict):
                        jd_html += section.get("content", "")
            elif isinstance(desc_body, str):
                jd_html = desc_body

            jd_text = (
                job.get("descriptionPlain")
                or (_strip_html(jd_html) if jd_html else None)
                or _strip_html(job.get("description", ""))
                or None
            )

            postings.append(
                JobPosting(
                    ats_job_id=job["id"],
                    title=job.get("text", ""),
                    location=_extract_location(job),
                    department=_extract_team(job),
                    url=job.get("hostedUrl", ""),
                    jd_text=jd_text,
                    posted_at=_parse_ms_timestamp(job.get("createdAt")),
                    raw=job,
                )
            )
        logger.info("Lever %s: fetched %d postings", board_token, len(postings))
        return postings


def _extract_location(job: dict) -> str | None:
    cats = job.get("categories", {})
    return cats.get("location") or cats.get("commitment") or None


def _extract_team(job: dict) -> str | None:
    cats = job.get("categories", {})
    return cats.get("team") or cats.get("department") or None
