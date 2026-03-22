"""
Overview endpoint for the user's specific commute trains:
  Morning:  07:11 and 07:40 CJX from Ternitz
  Evening:  16:15 U6 from Wien Westbahnhof
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from config import MORNING_TRAINS, EVENING_TRAIN, COMMUTE_TIME_TOLERANCE_MINUTES

router = APIRouter()


def _parse_hhmm(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


def _train_slot_query(hour: int, minute: int, tol: int) -> tuple[int, int, int, int]:
    """Returns (min_hour, min_minute, max_hour, max_minute) for a ±tol window."""
    total_min = hour * 60 + minute
    lo = total_min - tol
    hi = total_min + tol
    return lo // 60, lo % 60, hi // 60, hi % 60


def _today_status(db: Session, direction: str, product: str, hour: int, minute: int) -> dict:
    """Get today's latest observation for a specific scheduled departure."""
    tol = COMMUTE_TIME_TOLERANCE_MINUTES
    result = db.execute(
        text("""
            SELECT delay_seconds, cancelled, last_updated_at
            FROM train_observations
            WHERE direction = :dir
              AND line_product = :product
              AND DATE(planned_time AT TIME ZONE 'Europe/Vienna') = CURRENT_DATE
              AND (
                EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna') * 60 +
                EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
              ) BETWEEN (:hour * 60 + :minute - :tol) AND (:hour * 60 + :minute + :tol)
            ORDER BY last_updated_at DESC
            LIMIT 1
        """),
        {"dir": direction, "product": product, "hour": hour, "minute": minute, "tol": tol},
    )
    row = result.fetchone()
    if not row:
        return {"seen_today": False, "delay_seconds": None, "delay_minutes": None, "cancelled": None}

    delay_s = row.delay_seconds
    return {
        "seen_today": True,
        "delay_seconds": delay_s,
        "delay_minutes": round(delay_s / 60, 1) if delay_s is not None else 0,
        "cancelled": row.cancelled,
        "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
    }


def _history(db: Session, direction: str, product: str, hour: int, minute: int) -> dict:
    """Aggregate stats for a specific departure slot over the last 30 days."""
    tol = COMMUTE_TIME_TOLERANCE_MINUTES
    result = db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE cancelled = TRUE) AS cancelled_count,
                ROUND(AVG(delay_seconds) FILTER (WHERE cancelled = FALSE AND delay_seconds IS NOT NULL), 1) AS avg_delay,
                COUNT(*) FILTER (
                    WHERE cancelled = FALSE AND (delay_seconds IS NULL OR delay_seconds < 60)
                ) AS on_time_count,
                COUNT(*) FILTER (WHERE cancelled = FALSE) AS non_cancelled
            FROM train_observations
            WHERE direction = :dir
              AND line_product = :product
              AND planned_time >= NOW() - INTERVAL '30 days'
              AND (
                EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna') * 60 +
                EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
              ) BETWEEN (:hour * 60 + :minute - :tol) AND (:hour * 60 + :minute + :tol)
        """),
        {"dir": direction, "product": product, "hour": hour, "minute": minute, "tol": tol},
    )
    row = result.fetchone()
    total = row.total or 0
    non_cancelled = row.non_cancelled or 0

    return {
        "total_observed": total,
        "cancelled_count": row.cancelled_count or 0,
        "cancellation_rate_pct": round((row.cancelled_count or 0) / total * 100, 1) if total > 0 else 0,
        "avg_delay_minutes": round(float(row.avg_delay) / 60, 1) if row.avg_delay else 0,
        "on_time_pct": round((row.on_time_count or 0) / non_cancelled * 100, 1) if non_cancelled > 0 else 0,
    }


@router.get("/commute/overview")
def get_commute_overview(db: Session = Depends(get_db)):
    morning = []
    for time_str in MORNING_TRAINS:
        h, m = _parse_hhmm(time_str)
        morning.append({
            "planned_departure": time_str,
            "direction": "to_wien",
            "from_station": "Ternitz",
            "to_station": "Wien Meidling",
            "line": "CJX",
            "product": "regional",
            "today": _today_status(db, "to_wien", "regional", h, m),
            "history_30d": _history(db, "to_wien", "regional", h, m),
        })

    h, m = _parse_hhmm(EVENING_TRAIN)
    evening = [{
        "planned_departure": EVENING_TRAIN,
        "direction": "to_ternitz",
        "from_station": "Wien Westbahnhof",
        "to_station": "Wien Meidling",
        "line": "U6",
        "product": "subway",
        "today": _today_status(db, "to_ternitz", "subway", h, m),
        "history_30d": _history(db, "to_ternitz", "subway", h, m),
    }]

    return {"morning": morning, "evening": evening}
