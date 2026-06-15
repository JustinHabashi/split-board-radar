"""APScheduler entry point: runs the full pipeline daily on the configured cron schedule."""

from __future__ import annotations

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from jobpipe.config import load_settings
from jobpipe.pipeline import ensure_db, run

logger = logging.getLogger(__name__)


def _run_pipeline() -> None:
    try:
        run()
    except Exception as e:
        logger.exception("Pipeline run failed: %s", e)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    settings = load_settings()
    ensure_db()

    scheduler = BlockingScheduler(timezone="America/Los_Angeles")
    cron_parts = settings.schedule.cron.split()
    if len(cron_parts) == 5:
        minute, hour, day, month, day_of_week = cron_parts
    else:
        minute, hour, day, month, day_of_week = "0", "7", "*", "*", "*"

    scheduler.add_job(
        _run_pipeline,
        "cron",
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        id="daily_pipeline",
        replace_existing=True,
    )

    def _shutdown(sig, frame):
        logger.info("Shutting down scheduler (signal %s)", sig)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "Scheduler started — daily pipeline at cron '%s' (America/Los_Angeles)",
        settings.schedule.cron,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
