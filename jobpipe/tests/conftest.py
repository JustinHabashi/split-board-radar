"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from jobpipe.db import create_all, drop_all, init_sessionmaker
from jobpipe.models import Base

# Point config loading at the real config directory during tests
CONFIG_DIR = str(Path(__file__).parent.parent / "config")


@pytest.fixture(autouse=True)
def set_config_dir(monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", CONFIG_DIR)
    # Clear lru_cache on config functions so each test gets a fresh load
    from jobpipe import config as cfg_mod
    cfg_mod.load_settings.cache_clear()
    cfg_mod.load_all_candidates.cache_clear()


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    create_all(eng)
    yield eng
    drop_all(eng)
    eng.dispose()


@pytest.fixture
def session(engine):
    factory = init_sessionmaker(engine)
    sess = factory()
    yield sess
    sess.close()
