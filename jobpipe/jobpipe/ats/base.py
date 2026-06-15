"""Abstract base class for ATS adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jobpipe.models import JobPosting


class ATSAdapter(ABC):
    """Fetch job postings from a specific ATS, normalized to JobPosting."""

    @abstractmethod
    async def fetch(self, board_token: str) -> list[JobPosting]:
        """Return all active postings for the given board token."""
        ...
