import logging

from apscheduler.schedulers.background import BackgroundScheduler

from collector import collect_data
from config import POLL_INTERVAL_MINUTES

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
