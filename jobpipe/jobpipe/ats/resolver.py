"""Resolve a company careers URL to (ats_type, board_token).

Detection order:
1. Check for ATS signatures in the final URL after redirects.
2. Check page source for embedded ATS script/link signatures.
3. Return (unknown, None) if nothing matched.

Resolved results are written back to the Company row in the DB so we don't re-resolve daily.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

from jobpipe.models import ATSType

logger = logging.getLogger(__name__)

# (regex_pattern, ats_type, token_extractor)
# token_extractor receives the re.Match object and returns the board token string.
_URL_SIGNATURES: list[tuple[str, ATSType, callable]] = [
    (
        r"boards\.greenhouse\.io/(?:embed/job_board\?for=|)([^/?&#]+)",
        ATSType.greenhouse,
        lambda m: m.group(1),
    ),
    (
        r"job-boards\.greenhouse\.io/([^/?&#]+)",
        ATSType.greenhouse,
        lambda m: m.group(1),
    ),
    (
        r"jobs\.lever\.co/([^/?&#]+)",
        ATSType.lever,
        lambda m: m.group(1),
    ),
    (
        r"jobs\.ashbyhq\.com/([^/?&#]+)",
        ATSType.ashby,
        lambda m: m.group(1),
    ),
    (
        # Capture the subdomain (tenant) before the first dot, skip the wd\d part
        r"([a-z0-9-]+)\.wd\d*\.myworkdayjobs\.com/(?:[^/]+/)?([^/?&#\s]+)",
        ATSType.workday,
        lambda m: f"{m.group(1)}/{m.group(2)}",
    ),
]

# Page-source HTML signatures — applied against full page HTML
_HTML_SIGNATURES: list[tuple[str, ATSType, callable]] = [
    (
        # Matches embed script: ?for=token or /board?for=token
        r'greenhouse\.io[^"\'<>]*\?for=([^"\'&\s<>]+)',
        ATSType.greenhouse,
        lambda m: m.group(1),
    ),
    (
        # Matches href/src pointing to boards.greenhouse.io/<token>
        r'boards\.greenhouse\.io/([a-zA-Z0-9_-]+)',
        ATSType.greenhouse,
        lambda m: m.group(1),
    ),
    (
        r'jobs\.lever\.co/([a-zA-Z0-9_-]+)',
        ATSType.lever,
        lambda m: m.group(1),
    ),
    (
        r'jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)',
        ATSType.ashby,
        lambda m: m.group(1),
    ),
]


def _match_url(url: str) -> tuple[ATSType, Optional[str]]:
    for pattern, ats_type, extractor in _URL_SIGNATURES:
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            return ats_type, extractor(m)
    return ATSType.unknown, None


def _match_html(html: str) -> tuple[ATSType, Optional[str]]:
    for pattern, ats_type, extractor in _HTML_SIGNATURES:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            return ats_type, extractor(m)
    return ATSType.unknown, None


async def resolve_careers_url(
    careers_url: str, client: httpx.AsyncClient
) -> tuple[ATSType, Optional[str]]:
    """Fetch careers_url and detect ATS type + board token."""
    try:
        resp = await client.get(careers_url, follow_redirects=True)
    except httpx.RequestError as e:
        logger.warning("Resolver: request error for %s: %s", careers_url, e)
        return ATSType.unknown, None

    # Check the final URL first (fastest)
    final_url = str(resp.url)
    ats, token = _match_url(final_url)
    if ats != ATSType.unknown:
        return ats, token

    # Check redirect chain URLs
    for redirect in resp.history:
        ats, token = _match_url(str(redirect.url))
        if ats != ATSType.unknown:
            return ats, token

    # Fall back to page source
    try:
        html = resp.text
        ats, token = _match_html(html)
        if ats != ATSType.unknown:
            return ats, token
    except Exception as e:
        logger.debug("Resolver: failed to read HTML for %s: %s", careers_url, e)

    logger.info("Resolver: could not detect ATS for %s", careers_url)
    return ATSType.unknown, None
