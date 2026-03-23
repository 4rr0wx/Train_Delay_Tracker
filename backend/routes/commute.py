"""
Overview endpoint for the user's specific commute trains.

Morning journeys:
  CJX 07:11 ab Ternitz → Wien Meidling, dann U6 08:01 → Wien Westbahnhof
  CJX 07:40 ab Ternitz → Wien Meidling, dann U6 08:30 → Wien Westbahnhof

Evening journey:
  U6 16:15 ab Wien Westbahnhof → Wien Meidling, dann CJX 16:35 → Ternitz
"""

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from config import (
    MORNING_JOURNEYS, EVENING_JOURNEY, COMMUTE_TIME_TOLERANCE_MINUTES,
    TERNITZ_STATION_ID, WIEN_MEIDLING_STATION_ID, WIEN_WESTBAHNHOF_STATION_ID,
    WIENER_NEUSTADT_STATION_ID, BADEN_STATION_ID,
)

router = APIRouter()


def _parse_hhmm(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


def _today_status(
    db: Session,
    direction: str,
    product: str,
    hour: int,
    minute: int,
    target_date: str | None = None,
    station_id: str | None = None,
) -> dict:
    """Get the latest observation for a specific scheduled departure on the given date (default: today)."""
    tol = COMMUTE_TIME_TOLERANCE_MINUTES
    station_clause = "AND station_id = :station_id" if station_id else ""
    date_clause = (
        "AND DATE(planned_time AT TIME ZONE 'Europe/Vienna') = :target_date"
        if target_date else
        "AND DATE(planned_time AT TIME ZONE 'Europe/Vienna') = CURRENT_DATE"
    )
    params: dict = {
        "dir": direction,
        "product": product,
        "hour": hour,
        "minute": minute,
        "tol": tol,
        "station_id": station_id,
    }
    if target_date:
        params["target_date"] = target_date

    result = db.execute(
        text(f"""
            SELECT delay_seconds, cancelled, last_updated_at
            FROM train_observations
            WHERE direction = :dir
              AND line_product = :product
              {station_clause}
              {date_clause}
              AND (
                EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna') * 60 +
                EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
              ) BETWEEN (:hour * 60 + :minute - :tol) AND (:hour * 60 + :minute + :tol)
            ORDER BY last_updated_at DESC
            LIMIT 1
        """),
        params,
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


def _get_trip_id(
    db: Session, direction: str, product: str, station_id: str,
    hour: int, minute: int, target_date: str,
) -> str | None:
    """Return the trip_id of the train matching a departure slot on a given date."""
    tol = COMMUTE_TIME_TOLERANCE_MINUTES
    row = db.execute(
        text("""
            SELECT trip_id FROM train_observations
            WHERE direction = :dir AND line_product = :product
              AND station_id = :sid
              AND DATE(planned_time AT TIME ZONE 'Europe/Vienna') = :date
              AND (
                EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna') * 60 +
                EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
              ) BETWEEN :t - :tol AND :t + :tol
            ORDER BY last_updated_at DESC LIMIT 1
        """),
        {"dir": direction, "product": product, "sid": station_id,
         "date": target_date, "t": hour * 60 + minute, "tol": tol},
    ).fetchone()
    return row.trip_id if row else None


def _trip_station(db: Session, trip_id: str | None, station_id: str, direction: str) -> dict:
    """Return delay status for a specific trip (by trip_id) at an intermediate station."""
    _empty = {"seen": False, "delay_seconds": None, "delay_minutes": None,
              "cancelled": None, "planned_time_local": None}
    if not trip_id:
        return _empty
    row = db.execute(
        text("""
            SELECT delay_seconds, cancelled,
                   TO_CHAR(planned_time AT TIME ZONE 'Europe/Vienna', 'HH24:MI') AS planned_time_local
            FROM train_observations
            WHERE trip_id = :tid AND station_id = :sid AND direction = :dir
              AND line_product = 'regional'
            ORDER BY last_updated_at DESC LIMIT 1
        """),
        {"tid": trip_id, "sid": station_id, "dir": direction},
    ).fetchone()
    if not row:
        return _empty
    ds = row.delay_seconds
    return {
        "seen": True,
        "delay_seconds": ds,
        "delay_minutes": round(ds / 60, 1) if ds is not None else 0,
        "cancelled": row.cancelled,
        "planned_time_local": row.planned_time_local,
    }


@router.get("/commute/earliest-date")
def get_earliest_date(db: Session = Depends(get_db)):
    """Return the earliest date for which observations exist — used for back-navigation boundary."""
    result = db.execute(text("""
        SELECT DATE(MIN(planned_time) AT TIME ZONE 'Europe/Vienna') AS earliest
        FROM train_observations
    """))
    row = result.fetchone()
    return {"earliest_date": row.earliest.isoformat() if row and row.earliest else None}


@router.get("/commute/overview")
def get_commute_overview(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: Session = Depends(get_db),
):
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
                "today": _today_status(db, "to_wien", "regional", cjx_h, cjx_m, target_date=date),
                "history_30d": _history(db, "to_wien", "regional", cjx_h, cjx_m),
            },
            "u6": {
                "planned_departure": journey["u6_dep"],
                "direction": "to_wien",
                "from_station": "Wien Meidling",
                "to_station": "Wien Westbahnhof",
                "line": "U6",
                "product": "subway",
                "today": _today_status(db, "to_wien", "subway", u6_h, u6_m, target_date=date),
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
            "today": _today_status(db, "to_ternitz", "subway", u6_h, u6_m, target_date=date),
            "history_30d": _history(db, "to_ternitz", "subway", u6_h, u6_m),
        },
        "cjx": {
            "planned_departure": EVENING_JOURNEY["cjx_dep"],
            "direction": "to_ternitz",
            "from_station": "Wien Meidling",
            "to_station": "Ternitz",
            "line": "CJX",
            "product": "regional",
            "today": _today_status(db, "to_ternitz", "regional", cjx_h, cjx_m, target_date=date),
            "history_30d": _history(db, "to_ternitz", "regional", cjx_h, cjx_m),
        },
    }

    return {
        "morning": morning,
        "evening": evening,
        "viewed_date": date or date_type.today().isoformat(),
    }


@router.get("/commute/trips")
def get_commute_trips(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: Session = Depends(get_db),
):
    """
    Dynamically return all observed CJX trips for a given date in both directions,
    each paired with the nearest U6 connection.  Designed for flexible (Gleitzeit)
    commuters who may take any train, not just fixed departure slots.
    """
    target_date = date or date_type.today().isoformat()
    dc = "AND DATE(planned_time AT TIME ZONE 'Europe/Vienna') = :target_date"

    def _all_cjx(direction: str, anchor_station_id: str) -> list:
        return db.execute(
            text(f"""
                SELECT
                    TO_CHAR(MIN(planned_time) AT TIME ZONE 'Europe/Vienna', 'HH24:MI') AS dep_time,
                    EXTRACT(HOUR   FROM MIN(planned_time) AT TIME ZONE 'Europe/Vienna')::int AS dep_hour,
                    EXTRACT(MINUTE FROM MIN(planned_time) AT TIME ZONE 'Europe/Vienna')::int AS dep_minute
                FROM train_observations
                WHERE direction       = :dir
                  AND line_product    = 'regional'
                  AND station_id      = :station_id
                  {dc}
                GROUP BY
                    EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna'),
                    EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
                ORDER BY dep_hour, dep_minute
            """),
            {"target_date": target_date, "dir": direction, "station_id": anchor_station_id},
        ).fetchall()

    def _nearest_u6(direction: str, station_id: str, min_start: int, min_end: int):
        return db.execute(
            text(f"""
                SELECT
                    TO_CHAR(MIN(planned_time) AT TIME ZONE 'Europe/Vienna', 'HH24:MI') AS dep_time,
                    EXTRACT(HOUR   FROM MIN(planned_time) AT TIME ZONE 'Europe/Vienna')::int AS dep_hour,
                    EXTRACT(MINUTE FROM MIN(planned_time) AT TIME ZONE 'Europe/Vienna')::int AS dep_minute
                FROM train_observations
                WHERE direction    = :dir
                  AND line_product = 'subway'
                  AND station_id   = :station_id
                  {dc}
                  AND (
                    EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna') * 60 +
                    EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
                  ) BETWEEN :min_start AND :min_end
                GROUP BY
                    EXTRACT(HOUR   FROM planned_time AT TIME ZONE 'Europe/Vienna'),
                    EXTRACT(MINUTE FROM planned_time AT TIME ZONE 'Europe/Vienna')
                ORDER BY dep_hour, dep_minute
                LIMIT 1
            """),
            {
                "target_date": target_date, "dir": direction,
                "station_id": station_id,
                "min_start": min_start, "min_end": min_end,
            },
        ).fetchone()

    # ── MORNING: CJX to_wien (anchor = Ternitz) ──────────────────────────
    morning = []
    for row in _all_cjx("to_wien", TERNITZ_STATION_ID):
        h, m = row.dep_hour, row.dep_minute
        cjx_dep_min = h * 60 + m
        # U6 from Meidling: roughly 40–80 min after CJX leaves Ternitz
        u6_row = _nearest_u6("to_wien", WIEN_MEIDLING_STATION_ID,
                              cjx_dep_min + 40, cjx_dep_min + 80)
        # Intermediate station data via trip_id
        tid = _get_trip_id(db, "to_wien", "regional", TERNITZ_STATION_ID, h, m, target_date)
        trip: dict = {
            "cjx_dep": row.dep_time,
            "cjx": {
                "planned_departure": row.dep_time,
                "direction": "to_wien",
                "from_station": "Ternitz",
                "to_station": "Wien Meidling",
                "line": "CJX",
                "product": "regional",
                "today": _today_status(db, "to_wien", "regional", h, m, target_date=target_date),
                "history_30d": _history(db, "to_wien", "regional", h, m),
            },
            "wiener_neustadt": _trip_station(db, tid, WIENER_NEUSTADT_STATION_ID, "to_wien"),
            "baden": _trip_station(db, tid, BADEN_STATION_ID, "to_wien"),
            "meidling_cjx": _trip_station(db, tid, WIEN_MEIDLING_STATION_ID, "to_wien"),
            "u6_dep": None,
            "u6": None,
        }
        if u6_row:
            u6h, u6m = u6_row.dep_hour, u6_row.dep_minute
            trip["u6_dep"] = u6_row.dep_time
            trip["u6"] = {
                "planned_departure": u6_row.dep_time,
                "direction": "to_wien",
                "from_station": "Wien Meidling",
                "to_station": "Wien Westbahnhof",
                "line": "U6",
                "product": "subway",
                "today": _today_status(db, "to_wien", "subway", u6h, u6m, target_date=target_date),
                "history_30d": _history(db, "to_wien", "subway", u6h, u6m),
            }
        morning.append(trip)

    # ── EVENING: CJX to_ternitz (anchor = Wien Meidling) ─────────────────
    evening = []
    for row in _all_cjx("to_ternitz", WIEN_MEIDLING_STATION_ID):
        h, m = row.dep_hour, row.dep_minute
        cjx_dep_min = h * 60 + m
        # U6 from Westbahnhof: roughly 5–30 min BEFORE CJX leaves Meidling
        u6_row = _nearest_u6("to_ternitz", WIEN_WESTBAHNHOF_STATION_ID,
                              cjx_dep_min - 30, cjx_dep_min - 5)
        # Intermediate station data via trip_id
        tid = _get_trip_id(db, "to_ternitz", "regional", WIEN_MEIDLING_STATION_ID, h, m, target_date)
        trip = {
            "cjx_dep": row.dep_time,
            "cjx": {
                "planned_departure": row.dep_time,
                "direction": "to_ternitz",
                "from_station": "Wien Meidling",
                "to_station": "Ternitz",
                "line": "CJX",
                "product": "regional",
                "today": _today_status(db, "to_ternitz", "regional", h, m, target_date=target_date),
                "history_30d": _history(db, "to_ternitz", "regional", h, m),
            },
            "wiener_neustadt": _trip_station(db, tid, WIENER_NEUSTADT_STATION_ID, "to_ternitz"),
            "baden": _trip_station(db, tid, BADEN_STATION_ID, "to_ternitz"),
            "ternitz": _trip_station(db, tid, TERNITZ_STATION_ID, "to_ternitz"),
            "u6_dep": None,
            "u6": None,
        }
        if u6_row:
            u6h, u6m = u6_row.dep_hour, u6_row.dep_minute
            trip["u6_dep"] = u6_row.dep_time
            trip["u6"] = {
                "planned_departure": u6_row.dep_time,
                "direction": "to_ternitz",
                "from_station": "Wien Westbahnhof",
                "to_station": "Wien Meidling",
                "line": "U6",
                "product": "subway",
                "today": _today_status(db, "to_ternitz", "subway", u6h, u6m, target_date=target_date),
                "history_30d": _history(db, "to_ternitz", "subway", u6h, u6m),
            }
        evening.append(trip)

    return {
        "morning": morning,
        "evening": evening,
        "viewed_date": target_date,
    }
