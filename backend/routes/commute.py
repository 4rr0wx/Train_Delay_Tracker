"""
Commute-specific endpoints.

Commute slots (anchor legs) are defined in the commute_slots DB table (seeded via seed.py):
  - "Morning CJX 07:11" — CJX from Ternitz to_wien at 07:11
  - "Morning CJX 07:40" — CJX from Ternitz to_wien at 07:40
  - "Evening U6 16:15"  — U6 from Wien Westbahnhof to_ternitz at 16:15

GET /api/commute/overview  — per-slot status for today (or a given date)
GET /api/commute/trips     — dynamic trip list for a date with U6 connections
GET /api/commute/earliest-date — earliest service_date in the DB
"""

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import (
    TERNITZ_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIEN_WESTBAHNHOF_STATION_ID,
    WIENER_NEUSTADT_STATION_ID,
    BADEN_STATION_ID,
)
from database import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _slot_today(db: Session, station_id: str, direction: str, line_code: str,
                target_date: str, anchor_time, tol_sec: int) -> dict:
    """Return today's delay status for one commute slot."""
    row = db.execute(
        text("""
            SELECT ts.departure_delay_seconds AS delay_seconds,
                   tr.status::text             AS status,
                   ts.last_updated_at
            FROM trip_stops ts
            JOIN trips tr ON tr.id = ts.trip_id
            JOIN lines  l ON l.id  = tr.line_id
            WHERE ts.station_id          = :station_id
              AND tr.direction::text     = :direction
              AND l.code                 = :line_code
              AND tr.service_date        = :target_date
              AND ts.planned_departure  IS NOT NULL
              AND ABS(EXTRACT(EPOCH FROM (
                  (ts.planned_departure AT TIME ZONE 'Europe/Vienna')::time - :anchor_time
              ))) <= :tol_sec
            ORDER BY ts.last_updated_at DESC
            LIMIT 1
        """),
        {
            "station_id": station_id,
            "direction": direction,
            "line_code": line_code,
            "target_date": target_date,
            "anchor_time": anchor_time,
            "tol_sec": tol_sec,
        },
    ).fetchone()

    if not row:
        return {"seen_today": False, "delay_seconds": None, "delay_minutes": None, "cancelled": None}

    delay_s = row.delay_seconds
    return {
        "seen_today": True,
        "delay_seconds": delay_s,
        "delay_minutes": round(delay_s / 60, 1) if delay_s is not None else 0,
        "cancelled": row.status == "cancelled",
        "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
    }


def _slot_history(db: Session, station_id: str, direction: str, line_code: str,
                  anchor_time, tol_sec: int) -> dict:
    """Return 30-day aggregated stats for one commute slot."""
    row = db.execute(
        text("""
            SELECT
                COUNT(*)                                                                              AS total,
                COUNT(*) FILTER (WHERE tr.status::text = 'cancelled' OR ts.cancelled_at_stop)        AS cancelled_count,
                ROUND(
                    AVG(ts.departure_delay_seconds)
                    FILTER (WHERE tr.status::text != 'cancelled' AND ts.departure_delay_seconds IS NOT NULL),
                    1
                )                                                                                     AS avg_delay,
                COUNT(*) FILTER (
                    WHERE tr.status::text != 'cancelled'
                      AND ts.cancelled_at_stop = FALSE
                      AND (ts.departure_delay_seconds IS NULL OR ts.departure_delay_seconds < 60)
                )                                                                                     AS on_time_count,
                COUNT(*) FILTER (WHERE tr.status::text != 'cancelled')                               AS non_cancelled
            FROM trip_stops ts
            JOIN trips tr ON tr.id = ts.trip_id
            JOIN lines  l ON l.id  = tr.line_id
            WHERE ts.station_id        = :station_id
              AND tr.direction::text   = :direction
              AND l.code               = :line_code
              AND tr.service_date     >= CURRENT_DATE - INTERVAL '30 days'
              AND ts.planned_departure IS NOT NULL
              AND ABS(EXTRACT(EPOCH FROM (
                  (ts.planned_departure AT TIME ZONE 'Europe/Vienna')::time - :anchor_time
              ))) <= :tol_sec
        """),
        {
            "station_id": station_id,
            "direction": direction,
            "line_code": line_code,
            "anchor_time": anchor_time,
            "tol_sec": tol_sec,
        },
    ).fetchone()

    total = row.total or 0
    nc = row.non_cancelled or 0
    return {
        "total_observed": total,
        "cancelled_count": row.cancelled_count or 0,
        "cancellation_rate_pct": round((row.cancelled_count or 0) / total * 100, 1) if total > 0 else 0,
        "avg_delay_minutes": round(float(row.avg_delay) / 60, 1) if row.avg_delay else 0,
        "on_time_pct": round((row.on_time_count or 0) / nc * 100, 1) if nc > 0 else 0,
    }


# ---------------------------------------------------------------------------
# GET /api/commute/earliest-date
# ---------------------------------------------------------------------------

@router.get("/commute/earliest-date")
def get_earliest_date(db: Session = Depends(get_db)):
    """Return the earliest service_date in the DB — used for back-navigation boundary."""
    row = db.execute(text("SELECT MIN(service_date) AS earliest FROM service_days")).fetchone()
    return {"earliest_date": row.earliest.isoformat() if row and row.earliest else None}


# ---------------------------------------------------------------------------
# GET /api/commute/overview
# ---------------------------------------------------------------------------

@router.get("/commute/overview")
def get_commute_overview(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: Session = Depends(get_db),
):
    """Per-slot status for today (or a given date), read from commute_slots table."""
    target_date = date or date_type.today().isoformat()

    slots = db.execute(
        text("""
            SELECT cs.name,
                   cs.direction::text      AS direction,
                   cs.anchor_station_id,
                   cs.anchor_time_local,
                   cs.time_tolerance_minutes,
                   l.code                  AS line_code,
                   l.product_type,
                   s.name                  AS station_name
            FROM commute_slots cs
            JOIN routes    r ON r.id  = cs.route_id
            JOIN lines     l ON l.id  = r.line_id
            JOIN stations  s ON s.id  = cs.anchor_station_id
            WHERE cs.is_active = TRUE
            ORDER BY cs.anchor_time_local
        """)
    ).fetchall()

    result = []
    for slot in slots:
        tol_sec = slot.time_tolerance_minutes * 60
        anchor_time = slot.anchor_time_local
        anchor_time_str = str(anchor_time)[:5]  # 'HH:MM'

        result.append({
            "name": slot.name,
            "direction": slot.direction,
            "line": slot.line_code,
            "product": slot.product_type,
            "anchor_time_local": anchor_time_str,
            "anchor_station": slot.station_name,
            "planned_departure": anchor_time_str,
            "today": _slot_today(
                db, slot.anchor_station_id, slot.direction, slot.line_code,
                target_date, anchor_time, tol_sec,
            ),
            "history_30d": _slot_history(
                db, slot.anchor_station_id, slot.direction, slot.line_code,
                anchor_time, tol_sec,
            ),
        })

    return {"slots": result, "viewed_date": target_date}


# ---------------------------------------------------------------------------
# GET /api/commute/trips
# ---------------------------------------------------------------------------

@router.get("/commute/trips")
def get_commute_trips(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: Session = Depends(get_db),
):
    """
    All CJX trips observed on a given date, in both directions, each
    paired with the nearest U6 connection at Wien Meidling.
    """
    target_date = date or date_type.today().isoformat()

    # ── MORNING: CJX to_wien, anchored at Ternitz ────────────────────────
    morning_rows = db.execute(
        text("""
            SELECT
                tr.api_trip_id,
                tr.status::text                                                               AS status,
                TO_CHAR(ts_t.planned_departure AT TIME ZONE 'Europe/Vienna', 'HH24:MI')      AS dep_time,
                EXTRACT(HOUR   FROM ts_t.planned_departure AT TIME ZONE 'Europe/Vienna')::int AS dep_hour,
                EXTRACT(MINUTE FROM ts_t.planned_departure AT TIME ZONE 'Europe/Vienna')::int AS dep_minute,
                ts_t.departure_delay_seconds                                                  AS delay_t,
                ts_wn.planned_departure                                                       AS dep_wn,
                ts_wn.departure_delay_seconds                                                 AS delay_wn,
                ts_b.planned_departure                                                        AS dep_b,
                ts_b.departure_delay_seconds                                                  AS delay_b,
                ts_m.planned_arrival                                                          AS arr_m,
                ts_m.arrival_delay_seconds                                                    AS delay_m
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops ts_t ON ts_t.trip_id = tr.id AND ts_t.station_id = :ternitz
            LEFT JOIN trip_stops ts_wn ON ts_wn.trip_id = tr.id AND ts_wn.station_id = :wn
            LEFT JOIN trip_stops ts_b  ON ts_b.trip_id  = tr.id AND ts_b.station_id  = :baden
            LEFT JOIN trip_stops ts_m  ON ts_m.trip_id  = tr.id AND ts_m.station_id  = :meidling
            WHERE l.code = 'CJX'
              AND tr.direction::text = 'to_wien'
              AND tr.service_date    = :target_date
              AND ts_t.planned_departure IS NOT NULL
            ORDER BY ts_t.planned_departure
        """),
        {
            "ternitz": TERNITZ_STATION_ID,
            "wn": WIENER_NEUSTADT_STATION_ID,
            "baden": BADEN_STATION_ID,
            "meidling": WIEN_MEIDLING_STATION_ID,
            "target_date": target_date,
        },
    ).fetchall()

    morning = []
    for r in morning_rows:
        cjx_dep_min = r.dep_hour * 60 + r.dep_minute
        # U6 from Meidling: roughly 40–80 min after CJX departs Ternitz
        u6 = db.execute(
            text("""
                SELECT
                    TO_CHAR(ts.planned_departure AT TIME ZONE 'Europe/Vienna', 'HH24:MI') AS dep_time,
                    ts.departure_delay_seconds                                             AS delay,
                    tr.status::text                                                        AS status
                FROM trip_stops ts
                JOIN trips tr ON tr.id = ts.trip_id
                JOIN lines  l ON l.id  = tr.line_id
                WHERE l.code = 'U6'
                  AND tr.direction::text = 'to_wien'
                  AND tr.service_date    = :target_date
                  AND ts.station_id      = :meidling
                  AND ts.planned_departure IS NOT NULL
                  AND (
                    EXTRACT(HOUR   FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna') * 60
                    + EXTRACT(MINUTE FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna')
                  ) BETWEEN :min_start AND :min_end
                ORDER BY ts.planned_departure
                LIMIT 1
            """),
            {
                "target_date": target_date,
                "meidling": WIEN_MEIDLING_STATION_ID,
                "min_start": cjx_dep_min + 40,
                "min_end": cjx_dep_min + 80,
            },
        ).fetchone()

        trip: dict = {
            "cjx_dep": r.dep_time,
            "cjx": {
                "planned_departure": r.dep_time,
                "direction": "to_wien",
                "from_station": "Ternitz",
                "to_station": "Wien Meidling",
                "line": "CJX",
                "product": "regional",
                "today": {
                    "seen_today": True,
                    "delay_seconds": r.delay_t,
                    "delay_minutes": round(r.delay_t / 60, 1) if r.delay_t is not None else 0,
                    "cancelled": r.status == "cancelled",
                },
            },
            "wiener_neustadt": {
                "seen": r.dep_wn is not None,
                "delay_seconds": r.delay_wn,
                "planned_time_local": r.dep_wn.strftime("%H:%M") if r.dep_wn else None,
            },
            "baden": {
                "seen": r.dep_b is not None,
                "delay_seconds": r.delay_b,
            },
            "meidling_cjx": {
                "seen": r.arr_m is not None,
                "delay_seconds": r.delay_m,
            },
            "u6_dep": None,
            "u6": None,
        }
        if u6:
            trip["u6_dep"] = u6.dep_time
            trip["u6"] = {
                "planned_departure": u6.dep_time,
                "direction": "to_wien",
                "from_station": "Wien Meidling",
                "to_station": "Wien Westbahnhof",
                "line": "U6",
                "product": "subway",
                "today": {
                    "seen_today": True,
                    "delay_seconds": u6.delay,
                    "delay_minutes": round(u6.delay / 60, 1) if u6.delay is not None else 0,
                    "cancelled": u6.status == "cancelled",
                },
            }
        morning.append(trip)

    # ── EVENING: CJX to_ternitz, anchored at Wien Meidling ───────────────
    evening_rows = db.execute(
        text("""
            SELECT
                tr.api_trip_id,
                tr.status::text                                                               AS status,
                TO_CHAR(ts_m.planned_departure AT TIME ZONE 'Europe/Vienna', 'HH24:MI')      AS dep_time,
                EXTRACT(HOUR   FROM ts_m.planned_departure AT TIME ZONE 'Europe/Vienna')::int AS dep_hour,
                EXTRACT(MINUTE FROM ts_m.planned_departure AT TIME ZONE 'Europe/Vienna')::int AS dep_minute,
                ts_m.departure_delay_seconds                                                  AS delay_m,
                ts_b.planned_arrival                                                          AS arr_b,
                ts_b.arrival_delay_seconds                                                    AS delay_b,
                ts_wn.planned_arrival                                                         AS arr_wn,
                ts_wn.arrival_delay_seconds                                                   AS delay_wn,
                ts_t.planned_arrival                                                          AS arr_t,
                ts_t.arrival_delay_seconds                                                    AS delay_t
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops ts_m ON ts_m.trip_id = tr.id AND ts_m.station_id = :meidling
            LEFT JOIN trip_stops ts_b  ON ts_b.trip_id  = tr.id AND ts_b.station_id  = :baden
            LEFT JOIN trip_stops ts_wn ON ts_wn.trip_id = tr.id AND ts_wn.station_id = :wn
            LEFT JOIN trip_stops ts_t  ON ts_t.trip_id  = tr.id AND ts_t.station_id  = :ternitz
            WHERE l.code = 'CJX'
              AND tr.direction::text = 'to_ternitz'
              AND tr.service_date    = :target_date
              AND ts_m.planned_departure IS NOT NULL
            ORDER BY ts_m.planned_departure
        """),
        {
            "meidling": WIEN_MEIDLING_STATION_ID,
            "wn": WIENER_NEUSTADT_STATION_ID,
            "baden": BADEN_STATION_ID,
            "ternitz": TERNITZ_STATION_ID,
            "target_date": target_date,
        },
    ).fetchall()

    evening = []
    for r in evening_rows:
        cjx_dep_min = r.dep_hour * 60 + r.dep_minute
        # U6 from Westbahnhof: 5–30 min BEFORE CJX departs Meidling
        u6 = db.execute(
            text("""
                SELECT
                    TO_CHAR(ts.planned_departure AT TIME ZONE 'Europe/Vienna', 'HH24:MI') AS dep_time,
                    ts.departure_delay_seconds                                             AS delay,
                    tr.status::text                                                        AS status
                FROM trip_stops ts
                JOIN trips tr ON tr.id = ts.trip_id
                JOIN lines  l ON l.id  = tr.line_id
                WHERE l.code = 'U6'
                  AND tr.direction::text = 'to_ternitz'
                  AND tr.service_date    = :target_date
                  AND ts.station_id      = :westbahnhof
                  AND ts.planned_departure IS NOT NULL
                  AND (
                    EXTRACT(HOUR   FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna') * 60
                    + EXTRACT(MINUTE FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna')
                  ) BETWEEN :min_start AND :min_end
                ORDER BY ts.planned_departure
                LIMIT 1
            """),
            {
                "target_date": target_date,
                "westbahnhof": WIEN_WESTBAHNHOF_STATION_ID,
                "min_start": cjx_dep_min - 30,
                "min_end": cjx_dep_min - 5,
            },
        ).fetchone()

        trip = {
            "cjx_dep": r.dep_time,
            "cjx": {
                "planned_departure": r.dep_time,
                "direction": "to_ternitz",
                "from_station": "Wien Meidling",
                "to_station": "Ternitz",
                "line": "CJX",
                "product": "regional",
                "today": {
                    "seen_today": True,
                    "delay_seconds": r.delay_m,
                    "delay_minutes": round(r.delay_m / 60, 1) if r.delay_m is not None else 0,
                    "cancelled": r.status == "cancelled",
                },
            },
            "wiener_neustadt": {
                "seen": r.arr_wn is not None,
                "delay_seconds": r.delay_wn,
                "planned_time_local": r.arr_wn.strftime("%H:%M") if r.arr_wn else None,
            },
            "baden": {
                "seen": r.arr_b is not None,
                "delay_seconds": r.delay_b,
            },
            "ternitz": {
                "seen": r.arr_t is not None,
                "delay_seconds": r.delay_t,
            },
            "u6_dep": None,
            "u6": None,
        }
        if u6:
            trip["u6_dep"] = u6.dep_time
            trip["u6"] = {
                "planned_departure": u6.dep_time,
                "direction": "to_ternitz",
                "from_station": "Wien Westbahnhof",
                "to_station": "Wien Meidling",
                "line": "U6",
                "product": "subway",
                "today": {
                    "seen_today": True,
                    "delay_seconds": u6.delay,
                    "delay_minutes": round(u6.delay / 60, 1) if u6.delay is not None else 0,
                    "cancelled": u6.status == "cancelled",
                },
            }
        evening.append(trip)

    return {
        "morning": morning,
        "evening": evening,
        "viewed_date": target_date,
    }
