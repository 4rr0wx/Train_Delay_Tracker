import logging

from apscheduler.schedulers.background import BackgroundScheduler

from collector import collect_data
from config import POLL_INTERVAL_MINUTES
from database import SessionLocal

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Poll every N minutes during operating hours (05:00-23:00)
scheduler.add_job(
    collect_data,
    "cron",
    minute=f"*/{POLL_INTERVAL_MINUTES}",
    hour="5-23",
    id="collect_operating_hours",
)

# Poll every 30 minutes overnight
scheduler.add_job(
    collect_data,
    "cron",
    minute="*/30",
    hour="0-4",
    id="collect_overnight",
)


def _daily_station_check() -> None:
    from station_health import check_and_update_station_ids
    with SessionLocal() as db:
        check_and_update_station_ids(db)


# Re-validate station IDs once a day at 03:00
scheduler.add_job(
    _daily_station_check,
    "cron",
    hour=3,
    minute=0,
    id="station_health_check",
)
