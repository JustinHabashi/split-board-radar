"""Tests for pipeline orchestration and CLI."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobpipe.pipeline import STAGES, ensure_db, main


# ---------------------------------------------------------------------------
# ensure_db
# ---------------------------------------------------------------------------


def test_ensure_db_creates_tables(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        ensure_db()
        # Running twice is idempotent (create_all is safe to re-run)
        ensure_db()
    assert (tmp_path / "test.db").exists()


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage_name", list(STAGES.keys()))
def test_cli_stage_names_recognized(stage_name, tmp_path):
    """All stage names should be parseable by argparse without crashing."""
    db_url = f"sqlite:///{tmp_path}/test_cli.db"
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        with patch(f"jobpipe.pipeline.STAGES", {stage_name: lambda: None}):
            with patch("jobpipe.pipeline.ensure_db"):
                main([stage_name])


# ---------------------------------------------------------------------------
# Stage smoke tests (all external I/O mocked)
# ---------------------------------------------------------------------------


def test_stage_resolve_calls_resolve_companies(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        ensure_db()

        async def fake_resolve(session):
            return 3

        with patch("jobpipe.ingest.resolve_companies", side_effect=fake_resolve):
            from jobpipe.pipeline import stage_resolve
            result = stage_resolve()
        assert result == 3


def test_stage_filter_smoke(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        ensure_db()
        with patch("jobpipe.filter.run_filter") as mock_filter:
            mock_filter.return_value = {"keyword_passed": 0, "llm_scored": 0, "above_threshold": 0}
            from jobpipe.pipeline import stage_filter
            result = stage_filter()
        assert result["keyword_passed"] == 0


def test_stage_tailor_smoke(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        ensure_db()
        with patch("jobpipe.tailor.run_tailor") as mock_tailor:
            mock_tailor.return_value = 0
            from jobpipe.pipeline import stage_tailor
            result = stage_tailor()
        assert result == 0


def test_stage_notify_smoke(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        ensure_db()
        with patch("jobpipe.notify.run_notify") as mock_notify:
            mock_notify.return_value = {"engineer": 0, "scientist": 0}
            from jobpipe.pipeline import stage_notify
            result = stage_notify(dry_run=True)
        assert "engineer" in result


def test_full_run_calls_all_stages(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        with patch("jobpipe.pipeline.stage_resolve") as r, \
             patch("jobpipe.pipeline.stage_ingest") as i, \
             patch("jobpipe.pipeline.stage_filter") as f, \
             patch("jobpipe.pipeline.stage_tailor") as t, \
             patch("jobpipe.pipeline.stage_notify") as n, \
             patch("jobpipe.pipeline.ensure_db"):
            r.return_value = 0
            i.return_value = {}
            f.return_value = {"keyword_passed": 0, "llm_scored": 0, "above_threshold": 0}
            t.return_value = 0
            n.return_value = {}

            from jobpipe.pipeline import run
            run()

        r.assert_called_once()
        i.assert_called_once()
        f.assert_called_once()
        t.assert_called_once()
        n.assert_called_once()
