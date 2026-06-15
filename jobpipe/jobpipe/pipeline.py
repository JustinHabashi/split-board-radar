"""Pipeline orchestration.

Primary command:
  python -m jobpipe.pipeline digest [--output-dir PATH] [--candidate KEY]

  Runs resolve -> ingest -> filter, then writes an HTML digest file per candidate
  to data/digests/ (or --output-dir). No email, no draft generation.

Individual stages are also runnable for debugging:
  python -m jobpipe.pipeline [resolve|ingest|filter|tailor|notify|run|seed]
"""

from __future__ import annotations

import argparse
import logging
import sys

from jobpipe.db import build_engine, create_all, init_sessionmaker, session_scope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage functions (each creates its own session scope)
# ---------------------------------------------------------------------------


def stage_resolve() -> int:
    """Resolve ATS for unresolved companies. Returns count resolved."""
    import asyncio
    from jobpipe.ingest import resolve_companies

    with session_scope() as session:
        count = asyncio.run(resolve_companies(session))
    logger.info("resolve: %d companies resolved", count)
    return count


def stage_ingest() -> dict[str, tuple[int, int]]:
    """Poll all active ATS-resolved companies. Returns {company: (new, updated)}."""
    from jobpipe.ingest import run_ingest

    with session_scope() as session:
        results = run_ingest(session)
    total_new = sum(n for n, _ in results.values())
    logger.info("ingest: %d new postings across %d companies", total_new, len(results))
    return results


def stage_filter() -> dict[str, int]:
    """Run two-stage filter on unscored postings. Returns count dict."""
    from jobpipe.filter import run_filter

    with session_scope() as session:
        counts = run_filter(session)
    logger.info(
        "filter: keyword_passed=%d llm_scored=%d above_threshold=%d",
        counts["keyword_passed"],
        counts["llm_scored"],
        counts["above_threshold"],
    )
    return counts


def stage_tailor() -> int:
    """Generate drafts for new high-scoring matches. Returns count drafted."""
    from jobpipe.tailor import run_tailor

    with session_scope() as session:
        count = run_tailor(session)
    logger.info("tailor: %d drafts generated", count)
    return count


def stage_notify(dry_run: bool = False) -> dict[str, int]:
    """Send email digests per candidate. Returns {candidate: match_count}."""
    from jobpipe.notify import run_notify

    with session_scope() as session:
        sent = run_notify(session, dry_run=dry_run)
    for candidate, count in sent.items():
        logger.info("notify: %s — %d matches sent", candidate, count)
    return sent


def stage_digest(
    output_dir: str | None = None,
    candidate: str | None = None,
) -> dict[str, str]:
    """Primary MVP command: resolve -> ingest -> filter -> write HTML digest files.

    Returns {candidate_key: output_path_str} for each file written.
    """
    from pathlib import Path
    from jobpipe.notify import write_digest_files

    logger.info("=== Digest start ===")
    stage_resolve()
    stage_ingest()
    stage_filter()

    out_dir = Path(output_dir) if output_dir else None

    # If a specific candidate was requested, temporarily restrict load_all_candidates
    if candidate:
        from jobpipe.config import load_all_candidates
        all_candidates = load_all_candidates()
        if candidate not in all_candidates:
            raise ValueError(
                f"Unknown candidate '{candidate}'. "
                f"Available: {', '.join(all_candidates)}"
            )

    with session_scope() as session:
        written = write_digest_files(session, output_dir=out_dir)

    if candidate:
        written = {k: v for k, v in written.items() if k == candidate}

    if written:
        for key, path in written.items():
            print(f"[{key}] digest written -> {path}")
    else:
        print("No matches above threshold — no digest files written.")

    logger.info("=== Digest complete ===")
    return {k: str(v) for k, v in written.items()}


# ---------------------------------------------------------------------------
# Full pipeline run (includes tailor + email — advanced use)
# ---------------------------------------------------------------------------


def run(dry_run_notify: bool = False) -> None:
    """Execute the full pipeline including tailoring and email notification."""
    logger.info("=== Pipeline start ===")
    stage_resolve()
    stage_ingest()
    stage_filter()
    stage_tailor()
    stage_notify(dry_run=dry_run_notify)
    logger.info("=== Pipeline complete ===")


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------


def ensure_db() -> None:
    """Create tables and seed companies if needed."""
    from jobpipe.ingest import seed_companies

    engine = build_engine()
    create_all(engine)
    init_sessionmaker(engine)
    with session_scope() as session:
        count = seed_companies(session)
    if count:
        logger.info("Seeded %d companies into DB", count)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


STAGES = {
    "resolve": stage_resolve,
    "ingest": stage_ingest,
    "filter": stage_filter,
    "tailor": stage_tailor,
    "notify": lambda: stage_notify(dry_run=False),
    "notify-dry": lambda: stage_notify(dry_run=True),
    "run": run,
    "seed": lambda: ensure_db() or 0,
}


def main(argv: list[str] | None = None) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="JobPipe — poll job boards and produce a scored HTML digest.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # Primary command
    digest_parser = subparsers.add_parser(
        "digest",
        help="Poll boards, score against threshold, write HTML digest (default command)",
    )
    digest_parser.add_argument(
        "--output-dir",
        metavar="PATH",
        default=None,
        help="Directory to write digest files (default: data/digests/)",
    )
    digest_parser.add_argument(
        "--candidate",
        metavar="KEY",
        default=None,
        help="Restrict to one candidate profile, e.g. engineer or scientist",
    )

    # Individual stage sub-commands (for debugging / partial runs)
    for name in STAGES:
        subparsers.add_parser(name, help=f"Run only the '{name}' stage")

    args = parser.parse_args(argv)

    # Default to `digest` when invoked with no sub-command
    if args.command is None:
        args.command = "digest"

    ensure_db()

    if args.command == "digest":
        stage_digest(
            output_dir=getattr(args, "output_dir", None),
            candidate=getattr(args, "candidate", None),
        )
    else:
        STAGES[args.command]()


if __name__ == "__main__":
    main()
