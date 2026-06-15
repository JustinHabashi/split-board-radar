"""FastAPI server exposing JobPipe pipeline operations to the React frontend."""

from __future__ import annotations

import csv
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="JobPipe API", version="0.1.0")

_cors_origins = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Digest background state
# ---------------------------------------------------------------------------

_digest_lock = threading.Lock()
_digest_status: dict = {"status": "idle", "started_at": None, "completed_at": None, "error": None}


def _run_digest_background() -> None:
    global _digest_status
    with _digest_lock:
        _digest_status = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error": None,
        }
    try:
        from jobpipe.pipeline import ensure_db, stage_digest
        ensure_db()
        stage_digest()
        with _digest_lock:
            _digest_status["status"] = "idle"
            _digest_status["completed_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        logger.exception("Digest failed")
        with _digest_lock:
            _digest_status["status"] = "error"
            _digest_status["error"] = str(exc)
            _digest_status["completed_at"] = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CompanyIn(BaseModel):
    name: str
    candidate: str          # engineer | scientist | both
    sector: Optional[str] = ""
    careers_url: str
    ats: Optional[str] = "?"
    board_token: Optional[str] = ""
    active: bool = True


class DigestStatusOut(BaseModel):
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/matches")
def get_matches(candidate: Optional[str] = None, threshold: int = 70):
    """Return scored matches at or above threshold, optionally filtered by candidate."""
    import sqlite3
    from jobpipe.db import get_db_url

    db_path = get_db_url().replace("sqlite:///", "")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    query = """
        SELECT c.name AS company, p.location, p.title AS job_title,
               m.score, m.candidate, m.reason, p.url
        FROM match m
        JOIN posting p ON p.id = m.posting_id
        JOIN company c ON c.id = p.company_id
        WHERE m.score >= ?
    """
    params: list = [threshold]
    if candidate:
        query += " AND m.candidate = ?"
        params.append(candidate)
    query += " ORDER BY m.score DESC, c.name, p.title"

    rows = [dict(r) for r in con.execute(query, params).fetchall()]
    con.close()
    return {"matches": rows, "count": len(rows)}


@app.get("/api/companies")
def get_companies():
    """Return all rows from companies.csv."""
    csv_path = Path(__file__).parent.parent / "config" / "companies.csv"
    companies = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            companies.append(row)
    return {"companies": companies}


@app.post("/api/companies", status_code=201)
def add_company(company: CompanyIn):
    """Append a company to companies.csv and re-seed the database."""
    csv_path = Path(__file__).parent.parent / "config" / "companies.csv"

    # Check for duplicate name
    with open(csv_path, newline="", encoding="utf-8") as f:
        existing = [r["name"].lower() for r in csv.DictReader(f)]
    if company.name.lower() in existing:
        raise HTTPException(status_code=409, detail=f"Company '{company.name}' already exists.")

    # Append row
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            company.name,
            company.candidate,
            company.sector or "",
            company.careers_url,
            company.ats or "?",
            company.board_token or "",
            str(company.active).lower(),
        ])

    # Re-seed DB so the new company is immediately available
    try:
        from jobpipe.pipeline import ensure_db
        ensure_db()
    except Exception as exc:
        logger.exception("Seed failed after adding company")
        raise HTTPException(status_code=500, detail=f"Company saved but seed failed: {exc}")

    return {"ok": True, "name": company.name}


@app.post("/api/digest")
def trigger_digest():
    """Start the digest pipeline in a background thread. Returns immediately."""
    with _digest_lock:
        if _digest_status["status"] == "running":
            raise HTTPException(status_code=409, detail="Digest is already running.")

    thread = threading.Thread(target=_run_digest_background, daemon=True)
    thread.start()
    return {"ok": True, "message": "Digest started."}


@app.get("/api/digest/status", response_model=DigestStatusOut)
def digest_status():
    with _digest_lock:
        return DigestStatusOut(**_digest_status)
