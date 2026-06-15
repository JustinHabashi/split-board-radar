"""Tests for Lever, Ashby, and Workday adapters — no real network calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from jobpipe.ats.lever import LeverAdapter
from jobpipe.ats.ashby import AshbyAdapter
from jobpipe.ats.workday import WorkdayAdapter


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

_LEVER_JOB = {
    "id": "abc-123",
    "text": "Staff Engineer",
    "hostedUrl": "https://jobs.lever.co/acme/abc-123",
    "categories": {
        "location": "Seattle, WA",
        "team": "Platform",
    },
    "descriptionPlain": "We are looking for a Staff Engineer.",
    "createdAt": 1700000000000,  # ms epoch
}


def _lever_transport(jobs: list[dict]):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jobs, request=req)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_lever_fetch_parses_jobs():
    async with httpx.AsyncClient(transport=_lever_transport([_LEVER_JOB])) as client:
        adapter = LeverAdapter(client)
        postings = await adapter.fetch("acme")

    assert len(postings) == 1
    p = postings[0]
    assert p.ats_job_id == "abc-123"
    assert p.title == "Staff Engineer"
    assert p.location == "Seattle, WA"
    assert p.department == "Platform"
    assert "Staff Engineer" in (p.jd_text or "")
    assert p.posted_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_lever_fetch_empty():
    async with httpx.AsyncClient(transport=_lever_transport([])) as client:
        postings = await LeverAdapter(client).fetch("empty")
    assert postings == []


@pytest.mark.asyncio
async def test_lever_fetch_handles_404():
    def handler(req):
        return httpx.Response(404, request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        postings = await LeverAdapter(client).fetch("gone")
    assert postings == []


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------

_ASHBY_BOARD_RESPONSE = {
    "jobs": [
        {
            "id": "job-xyz",
            "title": "Scientist I",
            "locationName": "South San Francisco, CA",
            "departmentName": "Research",
            "jobUrl": "https://jobs.ashbyhq.com/acme/job-xyz",
            "publishedAt": "2026-01-10T09:00:00.000Z",
        }
    ]
}

_ASHBY_DETAIL_RESPONSE = {
    "descriptionHtml": "<p>Join our research team.</p>",
}


def _ashby_transport():
    def handler(req: httpx.Request) -> httpx.Response:
        if "/job/" in str(req.url):
            return httpx.Response(200, json=_ASHBY_DETAIL_RESPONSE, request=req)
        return httpx.Response(200, json=_ASHBY_BOARD_RESPONSE, request=req)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ashby_fetch_parses_jobs():
    async with httpx.AsyncClient(transport=_ashby_transport()) as client:
        postings = await AshbyAdapter(client).fetch("acme")

    assert len(postings) == 1
    p = postings[0]
    assert p.ats_job_id == "job-xyz"
    assert p.title == "Scientist I"
    assert p.location == "South San Francisco, CA"
    assert p.department == "Research"
    assert "research team" in (p.jd_text or "")
    assert p.posted_at == datetime(2026, 1, 10, 9, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_ashby_fetch_handles_board_error():
    def handler(req):
        return httpx.Response(503, request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        postings = await AshbyAdapter(client).fetch("down")
    assert postings == []


# ---------------------------------------------------------------------------
# Workday
# ---------------------------------------------------------------------------

_WORKDAY_PAGE_1 = {
    "total": 2,
    "jobPostings": [
        {
            "title": "Data Engineer",
            "externalPath": "/job/Seattle/Data-Engineer_JR-001",
            "locationsText": "Seattle, WA",
            "jobFamilyGroup": "Engineering",
            "postedOn": "01/05/2026",
            "bulletFields": ["JR-001"],
        }
    ],
}

_WORKDAY_PAGE_2 = {
    "total": 2,
    "jobPostings": [
        {
            "title": "ML Engineer",
            "externalPath": "/job/Remote/ML-Engineer_JR-002",
            "locationsText": "Remote",
            "jobFamilyGroup": "Engineering",
            "postedOn": "01/06/2026",
            "bulletFields": ["JR-002"],
        }
    ],
}


def _workday_transport():
    call_count = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        body = json.loads(req.content)
        offset = body.get("offset", 0)
        limit = body.get("limit", 20)

        # First call might be the suffix probe (limit=1)
        if limit == 1:
            return httpx.Response(200, json={"total": 2, "jobPostings": []}, request=req)
        if offset == 0:
            return httpx.Response(200, json=_WORKDAY_PAGE_1, request=req)
        return httpx.Response(200, json=_WORKDAY_PAGE_2, request=req)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_workday_fetch_paginates():
    async with httpx.AsyncClient(transport=_workday_transport()) as client:
        postings = await WorkdayAdapter(client).fetch("acme/careers")

    assert len(postings) == 2
    titles = {p.title for p in postings}
    assert "Data Engineer" in titles
    assert "ML Engineer" in titles


@pytest.mark.asyncio
async def test_workday_invalid_token():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404, request=r))) as client:
        postings = await WorkdayAdapter(client).fetch("badtoken")
    assert postings == []


@pytest.mark.asyncio
async def test_workday_all_suffixes_fail():
    def handler(req):
        return httpx.Response(404, request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        postings = await WorkdayAdapter(client).fetch("tenant/site")
    assert postings == []
