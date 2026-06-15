"""Database engine, session factory, and schema creation."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from jobpipe.models import Base


def get_db_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./data/jobpipe.db")


def build_engine(db_url: str | None = None) -> Engine:
    url = db_url or get_db_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, echo=False)
    if url.startswith("sqlite"):
        _enable_wal(engine)
    return engine


def _enable_wal(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_all(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    Base.metadata.drop_all(engine)


_SessionLocal: sessionmaker | None = None


def init_sessionmaker(engine: Engine) -> sessionmaker:
    global _SessionLocal
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


def get_session() -> sessionmaker:
    if _SessionLocal is None:
        raise RuntimeError("Call init_sessionmaker() before get_session()")
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional session scope."""
    factory = get_session()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
