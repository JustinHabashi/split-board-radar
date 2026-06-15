"""Digest: build an HTML match report and write it to disk (or optionally send via SMTP)."""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from sqlalchemy.orm import Session

from jobpipe.config import load_all_candidates, load_settings
from jobpipe.models import Draft, Match, MatchStatus

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_TEMPLATE_NAME = "digest_email.html.j2"


@dataclass
class MatchRow:
    score: int
    company: str
    title: str
    location: Optional[str]
    reason: str
    jd_url: str
    draft_path: Optional[str]


# ---------------------------------------------------------------------------
# Build digest
# ---------------------------------------------------------------------------


def build_digest(matches: list[MatchRow], candidate_name: str) -> str:
    """Render the HTML digest from a list of MatchRow objects."""
    env = Environment(
        loader=FileSystemLoader(str(_DATA_DIR / "templates")),
        undefined=StrictUndefined,
        autoescape=True,
    )
    tmpl = env.get_template(_TEMPLATE_NAME)
    return tmpl.render(
        matches=sorted(matches, key=lambda m: m.score, reverse=True),
        candidate_name=candidate_name,
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


def _collect_new_matches(session: Session, candidate_key: str) -> list[MatchRow]:
    """Gather all new/drafted matches for a candidate with score >= threshold."""
    settings = load_settings()
    rows = (
        session.query(Match)
        .filter(
            Match.candidate == candidate_key,
            Match.score >= settings.relevance_threshold,
            Match.status.in_([MatchStatus.new.value, MatchStatus.drafted.value]),
        )
        .all()
    )

    result: list[MatchRow] = []
    for m in rows:
        posting = m.posting
        if posting is None:
            continue
        draft = (
            session.query(Draft).filter_by(match_id=m.id).first()
        )
        draft_path = str(Path(draft.cv_path).parent) if draft and draft.cv_path else None
        result.append(
            MatchRow(
                score=int(m.score or 0),
                company=posting.company.name if posting.company else "?",
                title=posting.title,
                location=posting.location,
                reason=m.reason or "",
                jd_url=posting.url,
                draft_path=draft_path,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Write HTML digest files to disk (primary MVP output)
# ---------------------------------------------------------------------------


def write_digest_files(
    session: Session,
    output_dir: Optional[Path] = None,
) -> dict[str, Path]:
    """Write one HTML digest file per candidate to output_dir.

    Skips candidates that have zero matches above threshold.
    Returns {candidate_key: output_path} for each file written.
    """
    if output_dir is None:
        output_dir = _DATA_DIR / "digests"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = load_all_candidates()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    written: dict[str, Path] = {}

    for candidate_key, profile in candidates.items():
        matches = _collect_new_matches(session, candidate_key)
        if not matches:
            logger.info("No matches above threshold for %s — skipping digest", candidate_key)
            continue

        html = build_digest(matches, profile.name)
        out_path = output_dir / f"digest_{candidate_key}_{date_str}.html"
        out_path.write_text(html, encoding="utf-8")
        written[candidate_key] = out_path
        logger.info(
            "Wrote digest for %s (%d matches) -> %s", candidate_key, len(matches), out_path
        )

    return written


# ---------------------------------------------------------------------------
# Send email (optional — not part of the MVP flow)
# ---------------------------------------------------------------------------


def _smtp_config() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", "localhost"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
    }


def send_email(to_address: str, subject: str, html_body: str) -> None:
    cfg = _smtp_config()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = load_settings().email.from_address
    msg["To"] = to_address
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(cfg["host"], cfg["port"]) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        if cfg["user"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.sendmail(msg["From"], [to_address], msg.as_string())
    logger.info("Sent digest to %s", to_address)


# ---------------------------------------------------------------------------
# Orchestrate
# ---------------------------------------------------------------------------


def run_notify(session: Session, dry_run: bool = False) -> dict[str, int]:
    """Send a digest email per candidate. Returns {candidate_key: match_count}."""
    settings = load_settings()
    candidates = load_all_candidates()
    sent: dict[str, int] = {}

    for candidate_key, profile in candidates.items():
        matches = _collect_new_matches(session, candidate_key)
        if not matches:
            logger.info("No new matches for %s — skipping email", candidate_key)
            sent[candidate_key] = 0
            continue

        html = build_digest(matches, profile.name)
        recipient = settings.email.recipients.get(candidate_key, "")
        if not recipient:
            logger.warning("No email recipient configured for %s", candidate_key)
            sent[candidate_key] = len(matches)
            continue

        subject = (
            f"{settings.email.subject_prefix} {len(matches)} new match"
            f"{'es' if len(matches) != 1 else ''} for {profile.name}"
        )

        if dry_run:
            logger.info(
                "[DRY RUN] Would send %d match digest to %s", len(matches), recipient
            )
        else:
            try:
                send_email(recipient, subject, html)
            except Exception as e:
                logger.error("Failed to send email to %s: %s", recipient, e)

        sent[candidate_key] = len(matches)

    return sent
