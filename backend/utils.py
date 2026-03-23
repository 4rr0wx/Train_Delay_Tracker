"""
Utility functions for Train Delay Tracker V2.

Key functions:
  - compute_service_day  : Convert a UTC datetime to a Vienna service date
                           (04:00 local cutoff — night trains belong to the previous day).
  - ensure_service_day   : Insert-or-get a ServiceDay row, computing holiday metadata.
  - get_line_by_code     : Cached DB lookup for a Line by its short code (e.g. "CJX", "U6").
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import holidays
from sqlalchemy.orm import Session

from models import Line, ServiceDay

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIENNA_TZ = ZoneInfo("Europe/Vienna")

# Trains departing before 04:00 local time belong to the *previous* service day.
_SERVICE_DAY_CUTOFF_HOUR = 4

# ---------------------------------------------------------------------------
# Module-level line cache (avoids repeated DB round-trips in the collector)
# ---------------------------------------------------------------------------

_line_cache: dict[str, Line] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_service_day(planned_utc: datetime) -> date:
    """Return the Vienna service day for a given UTC datetime.

    The service day changes at 04:00 local Vienna time, not at midnight.
    Any train with a local departure/arrival before 04:00 is considered
    to belong to the previous calendar day.

    Args:
        planned_utc: A timezone-aware or naive UTC datetime.
                     If naive, it is assumed to be UTC.

    Returns:
        The service date as a ``datetime.date``.
    """
    if planned_utc.tzinfo is None:
        # Treat naive datetimes as UTC.
        from datetime import timezone
        planned_utc = planned_utc.replace(tzinfo=timezone.utc)

    local_dt = planned_utc.astimezone(VIENNA_TZ)

    if local_dt.hour < _SERVICE_DAY_CUTOFF_HOUR:
        return (local_dt - timedelta(days=1)).date()

    return local_dt.date()


def ensure_service_day(db: Session, service_date: date) -> ServiceDay:
    """Return the ServiceDay row for *service_date*, creating it if necessary.

    Holiday information is computed via the ``holidays`` library using the
    Austrian federal-level calendar.

    The function uses ``db.flush()`` (not ``db.commit()``) so the caller
    remains in control of the transaction.

    Args:
        db:           An active SQLAlchemy session.
        service_date: The service date to look up or create.

    Returns:
        The existing or newly-inserted :class:`ServiceDay` instance.
    """
    sd = db.get(ServiceDay, service_date)
    if sd is not None:
        return sd

    at_holidays = holidays.Austria(years=service_date.year)
    holiday_name: str | None = at_holidays.get(service_date)

    dow = service_date.weekday()  # 0 = Monday … 6 = Sunday (ISO)

    sd = ServiceDay(
        service_date=service_date,
        day_of_week=dow,
        is_weekday=dow < 5,
        is_austrian_holiday=holiday_name is not None,
        holiday_name=holiday_name,
    )
    db.add(sd)
    db.flush()
    return sd


def get_line_by_code(db: Session, code: str) -> Line:
    """Return the Line with the given short code (e.g. ``"CJX"`` or ``"U6"``).

    Results are cached in a module-level dict to avoid repeated DB lookups
    during a single collector run.

    Args:
        db:   An active SQLAlchemy session.
        code: The line code to look up (case-sensitive).

    Returns:
        The :class:`Line` instance.

    Raises:
        ValueError: If no line with that code exists in the database.
    """
    if code not in _line_cache:
        line = db.query(Line).filter_by(code=code).one_or_none()
        if line is None:
            raise ValueError(f"Line with code {code!r} not found in database")
        _line_cache[code] = line

    return _line_cache[code]
