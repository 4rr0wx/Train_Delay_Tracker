"""
Overview endpoint for the user's specific commute trains.

Morning journeys:
  CJX 07:11 ab Ternitz → Wien Meidling, dann U6 08:01 → Wien Westbahnhof
  CJX 07:40 ab Ternitz → Wien Meidling, dann U6 08:30 → Wien Westbahnhof

Evening journey:
  U6 16:15 ab Wien Westbahnhof → Wien Meidling, dann CJX 16:35 → Ternitz
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from config import MORNING_JOURNEYS, EVENING_JOURNEY, COMMUTE_TIME_TOLERANCE_MINUTES

router = APIRouter()


def _parse_hhmm(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


def _today_status(db: Session, direction: str, product: str, hour: int, minute: int, station_id: str | None = None) -> dict:
    """Get today's latest observation for a specific scheduled departure."""
    tol = COMMUTE_TIME_TOLERANCE_MINUTES
    station_clause = "AND station_id = :station_id" if station_id else ""
    result = db.execute(
        text(f"""
            SELECT delay_seconds, cancelled, last_updated_at
            FROM train_observations
            WHERE direction = :dir
              AND line_product = :product
              {station_clause}
              AND DATE(planned_time AT TIME ZONE 'Europe/Vienna') = CURRENT_DATE
              AND (
                EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna') * 60 +
                EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
              ) BETWEEN (:hour * 60 + :minute - :tol) AND (:hour * 60 + :minute + :tol)
            ORDER BY last_updated_at DESC
            LIMIT 1
        """),
        {"dir": direction, "product": product, "hour": hour, "minute": minute,
         "tol": tol, "station_id": station_id},
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


def _history(db: Session, direction: str, product: str, hour: int, minute: int, station_id: str | None = None) -> dict:
    """Aggregate stats for a specific departure slot over the last 30 days."""
    tol = COMMUTE_TIME_TOLERANCE_MINUTES
    station_clause = "AND station_id = :station_id" if station_id else ""
    result = db.execute(
        text(f"""
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
              {station_clause}
              AND planned_time >= NOW() - INTERVAL '30 days'
              AND (
                EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna') * 60 +
                EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
              ) BETWEEN (:hour * 60 + :minute - :tol) AND (:hour * 60 + :minute + :tol)
        """),
        {"dir": direction, "product": product, "hour": hour, "minute": minute,
         "tol": tol, "station_id": station_id},
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
    for journey in MORNING_JOURNEYS:
        cjx_h, cjx_m = _parse_hhmm(journey["cjx_dep"])
        u6_h,  u6_m  = _parse_hhmm(journey["u6_dep"])
        morning.append({
            "cjx_dep": journey["cjx_dep"],
            "u6_dep": journey["u6_dep"],
            "cjx": {
                "planned_departure": journey["cjx_dep"],
                "direction": "to_wien",
                "from_station": "Ternitz",
                "to_station": "Wien Meidling",
                "line": "CJX",
                "product": "regional",
                "today": _today_status(db, "to_wien", "regional", cjx_h, cjx_m),
                "history_30d": _history(db, "to_wien", "regional", cjx_h, cjx_m),
            },
            "u6": {
                "planned_departure": journey["u6_dep"],
                "direction": "to_wien",
                "from_station": "Wien Meidling",
                "to_station": "Wien Westbahnhof",
                "line": "U6",
                "product": "subway",
                "today": _today_status(db, "to_wien", "subway", u6_h, u6_m),
                "history_30d": _history(db, "to_wien", "subway", u6_h, u6_m),
            },
        })

    u6_h,  u6_m  = _parse_hhmm(EVENING_JOURNEY["u6_dep"])
    cjx_h, cjx_m = _parse_hhmm(EVENING_JOURNEY["cjx_dep"])
    evening = {
        "u6_dep": EVENING_JOURNEY["u6_dep"],
        "cjx_dep": EVENING_JOURNEY["cjx_dep"],
        "u6": {
            "planned_departure": EVENING_JOURNEY["u6_dep"],
            "direction": "to_ternitz",
            "from_station": "Wien Westbahnhof",
            "to_station": "Wien Meidling",
            "line": "U6",
            "product": "subway",
            "today": _today_status(db, "to_ternitz", "subway", u6_h, u6_m),
            "history_30d": _history(db, "to_ternitz", "subway", u6_h, u6_m),
        },
        "cjx": {
            "planned_departure": EVENING_JOURNEY["cjx_dep"],
            "direction": "to_ternitz",
            "from_station": "Wien Meidling",
            "to_station": "Ternitz",
            "line": "CJX",
            "product": "regional",
            "today": _today_status(db, "to_ternitz", "regional", cjx_h, cjx_m),
            "history_30d": _history(db, "to_ternitz", "regional", cjx_h, cjx_m),
        },
    }

    return {"morning": morning, "evening": evening}
