"""Entry point for the daily recycling reminder.

Runs once a day at 2pm UK time from a cron job on a Raspberry Pi, inside a
Docker container. Reports collections planned for the next day, and flags any
collection scheduled for today that appears to have been missed (no completion
timestamp and a non-healthy, non-in-progress state).

`main()` is the container entry point with cron-friendly exit codes (0 = ran,
1 = failed). This module only wires config, fetching, and sending together;
the pure report-building logic lives in `report.py`.

The app notifies when collections are scheduled for tomorrow, when tomorrow is
the user's usual collection day but nothing is scheduled (a possible
skip/bank holiday), or when a collection looks missed or needs attention. On a
non-usual day with nothing scheduled it stays quiet — that outcome is expected
and shouldn't ping.
"""

import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from notifiers import PushoverNotifier
from report import DEFAULT_USUAL_DAY, Report, build_report, parse_weekday
from scraper import fetch_collections

LONDON = ZoneInfo("Europe/London")
NOTIFICATION_TITLE = "Recycling Notifier"

logger = logging.getLogger(__name__)


def main() -> None:
    """Container entry point. Exit code 0 = ran (with or without a notification),
    1 = failure, so cron records errors in the host log."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        report = run()
        if report is None:
            logger.info("Nothing to report; skipping notification.")
            return
        _send(report)
    except Exception:
        logger.exception("recycling-notifier run failed")
        raise SystemExit(1)


def run() -> Report | None:
    """Fetch collections for the UPRN and build today's report; no sending."""
    today = _today()
    uprn = os.environ["UPRN"]
    usual_day = parse_weekday(os.environ.get("USUAL_COLLECTION_DAY", DEFAULT_USUAL_DAY))
    collections = fetch_collections(uprn)
    if not collections:
        logger.warning("API returned no records for UPRN %s; is the API/field mapping still valid?", uprn)

    return build_report(collections, today, usual_day)


def _send(report: Report) -> None:
    logger.info("Sending report: %s", report.title)
    notifier = PushoverNotifier(
        token=os.environ["PUSHOVER_TOKEN"],
        user_key=os.environ["PUSHOVER_USER_KEY"],
    )
    notifier.send(NOTIFICATION_TITLE, report.body)


def _today() -> date:
    return datetime.now(LONDON).date()


if __name__ == "__main__":
    main()
