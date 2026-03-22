"""
Journey-level endpoints: track delay buildup across stations for each CJX/U6 trip.

to_wien journey (CJX): anchored on Ternitz departures.
  Stations tracked: Ternitz → Wiener Neustadt → Baden → Wien Meidling

to_ternitz journey (CJX): anchored on Wien Meidling CJX departures.
  Stations tracked: Wien Meidling → Baden → Wiener Neustadt → Ternitz

Diversion detection: a trip that has Ternitz + Meidling observations but NO
Baden observation is flagged as was_diverted.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from config import (
    TERNITZ_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIEN_WESTBAHNHOF_STATION_ID,
    WIENER_NEUSTADT_STATION_ID,
    BADEN_STATION_ID,
    COMMUTE_TIME_TOLERANCE_MINUTES,
)

router = APIRouter()


def _parse_days(days_of_week: Optional[str]) -> list[int] | None:
    """Parse '1,2,3,4,5' → [1,2,3,4,5]. PostgreSQL DOW: 0=Sun,1=Mon,...,6=Sat."""
    if not days_of_week:
        return None
    try:
        return [int(d) for d in days_of_week.split(",") if d.strip()]
    except ValueError:
        return None


def _parse_times(departure_times: Optional[str]) -> list[int] | None:
    """Parse '07:11,07:40' → [431, 460] (minutes since midnight)."""
    if not departure_times:
        return None
    result = []
    for t in departure_times.split(","):
        t = t.strip()
        if ":" in t:
            try:
                h, m = t.split(":")
                result.append(int(h) * 60 + int(m))
            except ValueError:
                pass
    return result or None


def _date_bounds(
    date_from: Optional[str],
    date_to: Optional[str],
    days: int,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if date_from:
        try:
            df = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            df = now - timedelta(days=days)
    else:
        df = now - timedelta(days=days)

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            dt = now
    else:
        dt = now
    return df, dt


# ---------------------------------------------------------------------------
# GET /api/journeys  – CJX journeys (to_wien anchor: Ternitz; to_ternitz: Westbahnhof)
# ---------------------------------------------------------------------------

@router.get("/journeys")
def get_journeys(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    days_of_week: Optional[str] = Query(None, description="Comma-sep DOW 0-6 (0=Sun)"),
    departure_times: Optional[str] = Query(None, description="Comma-sep HH:MM, ±2 min tolerance"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    df, dt = _date_bounds(date_from, date_to, days)
    dow_list = _parse_days(days_of_week)
    time_list = _parse_times(departure_times)
    tol = COMMUTE_TIME_TOLERANCE_MINUTES

    dow_clause = ""
    if dow_list:
        dow_clause = "AND EXTRACT(DOW FROM anchor.planned_time AT TIME ZONE 'Europe/Vienna') = ANY(:dow_list)"

    time_clause = ""
    if time_list:
        time_clause = """
        AND (
            EXTRACT(HOUR FROM anchor.planned_time AT TIME ZONE 'Europe/Vienna') * 60
            + EXTRACT(MINUTE FROM anchor.planned_time AT TIME ZONE 'Europe/Vienna')
        ) = ANY(:time_list_expanded)
        """

    # Expand time_list to include ±tol minutes
    time_list_expanded = []
    if time_list:
        for t in time_list:
            for offset_min in range(-tol, tol + 1):
                time_list_expanded.append(t + offset_min)

    if direction == "to_wien":
        # Anchor: CJX departures at Ternitz
        # Route: Ternitz → Wiener Neustadt → Baden → Wien Meidling
        query = text(f"""
            WITH anchor AS (
                SELECT trip_id, line_name, planned_time, actual_time, delay_seconds, cancelled, platform
                FROM train_observations
                WHERE station_id = :anchor_station
                  AND direction = 'to_wien'
                  AND line_product = 'regional'
                  AND planned_time BETWEEN :date_from AND :date_to
                  {dow_clause}
                  {time_clause}
            ),
            wiener_neustadt AS (
                SELECT trip_id, planned_time AS planned_time_wn, actual_time AS actual_time_wn,
                       delay_seconds AS delay_wn, cancelled AS cancelled_wn
                FROM train_observations
                WHERE station_id = :wn_station
                  AND direction = 'to_wien'
                  AND line_product = 'regional'
            ),
            baden AS (
                SELECT trip_id, planned_time AS planned_time_b, actual_time AS actual_time_b,
                       delay_seconds AS delay_b, cancelled AS cancelled_b
                FROM train_observations
                WHERE station_id = :baden_station
                  AND direction = 'to_wien'
                  AND line_product = 'regional'
            ),
            meidling AS (
                SELECT trip_id, planned_time AS planned_time_m, actual_time AS actual_time_m,
                       delay_seconds AS delay_m, cancelled AS cancelled_m
                FROM train_observations
                WHERE station_id = :meidling_station
                  AND direction = 'to_wien'
                  AND line_product = 'regional'
            )
            SELECT
                anchor.trip_id,
                anchor.line_name,
                anchor.planned_time  AS dep_ternitz_planned,
                anchor.actual_time   AS dep_ternitz_actual,
                anchor.delay_seconds AS dep_ternitz_delay,
                anchor.cancelled     AS dep_ternitz_cancelled,
                anchor.platform      AS dep_ternitz_platform,
                wn.planned_time_wn AS dep_wn_planned,
                wn.actual_time_wn  AS dep_wn_actual,
                wn.delay_wn        AS dep_wn_delay,
                wn.cancelled_wn    AS dep_wn_cancelled,
                b.planned_time_b AS dep_baden_planned,
                b.actual_time_b  AS dep_baden_actual,
                b.delay_b        AS dep_baden_delay,
                b.cancelled_b    AS dep_baden_cancelled,
                m.planned_time_m AS arr_meidling_planned,
                m.actual_time_m  AS arr_meidling_actual,
                m.delay_m        AS arr_meidling_delay,
                m.cancelled_m    AS arr_meidling_cancelled,
                (b.trip_id IS NULL AND m.trip_id IS NOT NULL) AS was_diverted
            FROM anchor
            LEFT JOIN wiener_neustadt wn ON wn.trip_id = anchor.trip_id
            LEFT JOIN baden b  ON b.trip_id = anchor.trip_id
            LEFT JOIN meidling m ON m.trip_id = anchor.trip_id
            ORDER BY anchor.planned_time DESC
            LIMIT :lim OFFSET :off
        """)
    else:
        # Anchor: CJX departures at Wien Meidling (to_ternitz direction)
        # Route: Wien Meidling → Baden → Wiener Neustadt → Ternitz
        query = text(f"""
            WITH anchor AS (
                SELECT trip_id, line_name, planned_time, actual_time, delay_seconds, cancelled, platform
                FROM train_observations
                WHERE station_id = :meidling_station
                  AND direction = 'to_ternitz'
                  AND line_product = 'regional'
                  AND planned_time BETWEEN :date_from AND :date_to
                  {dow_clause}
                  {time_clause}
            ),
            baden AS (
                SELECT trip_id, planned_time AS planned_time_b, actual_time AS actual_time_b,
                       delay_seconds AS delay_b, cancelled AS cancelled_b
                FROM train_observations
                WHERE station_id = :baden_station
                  AND direction = 'to_ternitz'
                  AND line_product = 'regional'
            ),
            wiener_neustadt AS (
                SELECT trip_id, planned_time AS planned_time_wn, actual_time AS actual_time_wn,
                       delay_seconds AS delay_wn, cancelled AS cancelled_wn
                FROM train_observations
                WHERE station_id = :wn_station
                  AND direction = 'to_ternitz'
                  AND line_product = 'regional'
            ),
            ternitz AS (
                SELECT trip_id, planned_time AS planned_time_t, actual_time AS actual_time_t,
                       delay_seconds AS delay_t, cancelled AS cancelled_t
                FROM train_observations
                WHERE station_id = :ternitz_station
                  AND direction = 'to_ternitz'
                  AND line_product = 'regional'
            )
            SELECT
                anchor.trip_id,
                anchor.line_name,
                anchor.planned_time  AS dep_meidling_planned,
                anchor.actual_time   AS dep_meidling_actual,
                anchor.delay_seconds AS dep_meidling_delay,
                anchor.cancelled     AS dep_meidling_cancelled,
                anchor.platform      AS dep_meidling_platform,
                b.planned_time_b AS dep_baden_planned,
                b.actual_time_b  AS dep_baden_actual,
                b.delay_b        AS dep_baden_delay,
                b.cancelled_b    AS dep_baden_cancelled,
                wn.planned_time_wn AS dep_wn_planned,
                wn.actual_time_wn  AS dep_wn_actual,
                wn.delay_wn        AS dep_wn_delay,
                wn.cancelled_wn    AS dep_wn_cancelled,
                t.planned_time_t AS arr_ternitz_planned,
                t.actual_time_t  AS arr_ternitz_actual,
                t.delay_t        AS arr_ternitz_delay,
                t.cancelled_t    AS arr_ternitz_cancelled,
                FALSE AS was_diverted
            FROM anchor
            LEFT JOIN baden b            ON b.trip_id  = anchor.trip_id
            LEFT JOIN wiener_neustadt wn ON wn.trip_id = anchor.trip_id
            LEFT JOIN ternitz t          ON t.trip_id  = anchor.trip_id
            ORDER BY anchor.planned_time DESC
            LIMIT :lim OFFSET :off
        """)

    params: dict = {
        "meidling_station": WIEN_MEIDLING_STATION_ID,
        "wn_station": WIENER_NEUSTADT_STATION_ID,
        "baden_station": BADEN_STATION_ID,
        "date_from": df,
        "date_to": dt,
        "lim": limit,
        "off": offset,
    }
    if direction == "to_wien":
        params["anchor_station"] = TERNITZ_STATION_ID
    else:
        params["ternitz_station"] = TERNITZ_STATION_ID

    if dow_list:
        params["dow_list"] = dow_list
    if time_list_expanded:
        params["time_list_expanded"] = time_list_expanded

    rows = db.execute(query, params).fetchall()

    def _fmt(ts) -> str | None:
        return ts.isoformat() if ts else None

    def _delay_min(s) -> float | None:
        return round(s / 60, 1) if s is not None else None

    result = []
    for r in rows:
        if direction == "to_wien":
            result.append({
                "trip_id": r.trip_id,
                "line_name": r.line_name,
                "direction": "to_wien",
                "was_diverted": bool(r.was_diverted),
                "stations": {
                    "ternitz": {
                        "planned": _fmt(r.dep_ternitz_planned),
                        "actual": _fmt(r.dep_ternitz_actual),
                        "delay_seconds": r.dep_ternitz_delay,
                        "delay_minutes": _delay_min(r.dep_ternitz_delay),
                        "cancelled": bool(r.dep_ternitz_cancelled),
                        "platform": r.dep_ternitz_platform,
                    },
                    "wiener_neustadt": {
                        "planned": _fmt(r.dep_wn_planned),
                        "actual": _fmt(r.dep_wn_actual),
                        "delay_seconds": r.dep_wn_delay,
                        "delay_minutes": _delay_min(r.dep_wn_delay),
                        "cancelled": bool(r.dep_wn_cancelled) if r.dep_wn_cancelled is not None else None,
                        "observed": r.dep_wn_planned is not None,
                    },
                    "baden": {
                        "planned": _fmt(r.dep_baden_planned),
                        "actual": _fmt(r.dep_baden_actual),
                        "delay_seconds": r.dep_baden_delay,
                        "delay_minutes": _delay_min(r.dep_baden_delay),
                        "cancelled": bool(r.dep_baden_cancelled) if r.dep_baden_cancelled is not None else None,
                        "observed": r.dep_baden_planned is not None,
                    },
                    "wien_meidling": {
                        "planned": _fmt(r.arr_meidling_planned),
                        "actual": _fmt(r.arr_meidling_actual),
                        "delay_seconds": r.arr_meidling_delay,
                        "delay_minutes": _delay_min(r.arr_meidling_delay),
                        "cancelled": bool(r.arr_meidling_cancelled) if r.arr_meidling_cancelled is not None else None,
                        "observed": r.arr_meidling_planned is not None,
                    },
                },
            })
        else:
            result.append({
                "trip_id": r.trip_id,
                "line_name": r.line_name,
                "direction": "to_ternitz",
                "was_diverted": False,
                "stations": {
                    "wien_meidling": {
                        "planned": _fmt(r.dep_meidling_planned),
                        "actual": _fmt(r.dep_meidling_actual),
                        "delay_seconds": r.dep_meidling_delay,
                        "delay_minutes": _delay_min(r.dep_meidling_delay),
                        "cancelled": bool(r.dep_meidling_cancelled),
                        "platform": r.dep_meidling_platform,
                    },
                    "baden": {
                        "planned": _fmt(r.dep_baden_planned),
                        "actual": _fmt(r.dep_baden_actual),
                        "delay_seconds": r.dep_baden_delay,
                        "delay_minutes": _delay_min(r.dep_baden_delay),
                        "cancelled": bool(r.dep_baden_cancelled) if r.dep_baden_cancelled is not None else None,
                        "observed": r.dep_baden_planned is not None,
                    },
                    "wiener_neustadt": {
                        "planned": _fmt(r.dep_wn_planned),
                        "actual": _fmt(r.dep_wn_actual),
                        "delay_seconds": r.dep_wn_delay,
                        "delay_minutes": _delay_min(r.dep_wn_delay),
                        "cancelled": bool(r.dep_wn_cancelled) if r.dep_wn_cancelled is not None else None,
                        "observed": r.dep_wn_planned is not None,
                    },
                    "ternitz": {
                        "planned": _fmt(r.arr_ternitz_planned),
                        "actual": _fmt(r.arr_ternitz_actual),
                        "delay_seconds": r.arr_ternitz_delay,
                        "delay_minutes": _delay_min(r.arr_ternitz_delay),
                        "cancelled": bool(r.arr_ternitz_cancelled) if r.arr_ternitz_cancelled is not None else None,
                        "observed": r.arr_ternitz_planned is not None,
                    },
                },
            })

    return {"total": len(result), "offset": offset, "limit": limit, "journeys": result}


# ---------------------------------------------------------------------------
# GET /api/journeys/stats  – aggregated stats for filtered journey set
# ---------------------------------------------------------------------------

@router.get("/journeys/stats")
def get_journey_stats(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    days_of_week: Optional[str] = Query(None),
    departure_times: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    df, dt = _date_bounds(date_from, date_to, days)
    dow_list = _parse_days(days_of_week)
    time_list = _parse_times(departure_times)
    tol = COMMUTE_TIME_TOLERANCE_MINUTES

    dow_clause = ""
    if dow_list:
        dow_clause = "AND EXTRACT(DOW FROM anchor.planned_time AT TIME ZONE 'Europe/Vienna') = ANY(:dow_list)"

    time_clause = ""
    time_list_expanded = []
    if time_list:
        for t in time_list:
            for offset_min in range(-tol, tol + 1):
                time_list_expanded.append(t + offset_min)
        time_clause = """
        AND (
            EXTRACT(HOUR FROM anchor.planned_time AT TIME ZONE 'Europe/Vienna') * 60
            + EXTRACT(MINUTE FROM anchor.planned_time AT TIME ZONE 'Europe/Vienna')
        ) = ANY(:time_list_expanded)
        """

    if direction == "to_wien":
        anchor_station = TERNITZ_STATION_ID
        anchor_product = "regional"
        anchor_dir = "to_wien"
    else:
        anchor_station = WIEN_WESTBAHNHOF_STATION_ID
        anchor_product = "subway"
        anchor_dir = "to_ternitz"

    query = text(f"""
        WITH anchor AS (
            SELECT trip_id, delay_seconds AS delay_anchor, cancelled
            FROM train_observations
            WHERE station_id = :anchor_station
              AND direction = :anchor_dir
              AND line_product = :anchor_product
              AND planned_time BETWEEN :date_from AND :date_to
              {dow_clause}
              {time_clause}
        ),
        meidling AS (
            SELECT trip_id, delay_seconds AS delay_m, cancelled AS cancelled_m
            FROM train_observations
            WHERE station_id = :meidling_station
              AND direction = :anchor_dir
              AND line_product = :anchor_product
        ),
        baden AS (
            SELECT trip_id
            FROM train_observations
            WHERE station_id = :baden_station
              AND direction = 'to_wien'
              AND line_product = 'regional'
        )
        SELECT
            COUNT(DISTINCT anchor.trip_id) AS total_journeys,
            COUNT(DISTINCT anchor.trip_id) FILTER (WHERE anchor.cancelled = TRUE) AS cancelled_count,
            ROUND(AVG(anchor.delay_anchor) FILTER (WHERE anchor.cancelled = FALSE AND anchor.delay_anchor IS NOT NULL), 1) AS avg_delay_anchor,
            ROUND(AVG(m.delay_m) FILTER (WHERE m.delay_m IS NOT NULL), 1) AS avg_delay_meidling,
            COUNT(DISTINCT anchor.trip_id) FILTER (
                WHERE anchor.cancelled = FALSE AND (anchor.delay_anchor IS NULL OR anchor.delay_anchor < 60)
            ) AS on_time_count,
            COUNT(DISTINCT anchor.trip_id) FILTER (
                WHERE m.trip_id IS NULL AND b.trip_id IS NOT NULL
            ) AS has_meidling_no_anchor,
            COUNT(DISTINCT anchor.trip_id) FILTER (
                WHERE :is_to_wien AND m.trip_id IS NOT NULL AND b.trip_id IS NULL
            ) AS diversion_count
        FROM anchor
        LEFT JOIN meidling m ON m.trip_id = anchor.trip_id
        LEFT JOIN baden b ON b.trip_id = anchor.trip_id
    """)

    params: dict = {
        "anchor_station": anchor_station,
        "anchor_product": anchor_product,
        "anchor_dir": anchor_dir,
        "meidling_station": WIEN_MEIDLING_STATION_ID,
        "baden_station": BADEN_STATION_ID,
        "date_from": df,
        "date_to": dt,
        "is_to_wien": direction == "to_wien",
    }
    if dow_list:
        params["dow_list"] = dow_list
    if time_list_expanded:
        params["time_list_expanded"] = time_list_expanded

    row = db.execute(query, params).fetchone()
    total = row.total_journeys or 0
    non_cancelled = total - (row.cancelled_count or 0)
    avg_anchor = float(row.avg_delay_anchor) if row.avg_delay_anchor else 0
    avg_meidling = float(row.avg_delay_meidling) if row.avg_delay_meidling else 0

    return {
        "direction": direction,
        "total_journeys": total,
        "cancelled_count": row.cancelled_count or 0,
        "cancellation_rate_pct": round((row.cancelled_count or 0) / total * 100, 1) if total > 0 else 0,
        "avg_delay_start_minutes": round(avg_anchor / 60, 1),
        "avg_delay_meidling_minutes": round(avg_meidling / 60, 1),
        "delay_added_en_route_minutes": round((avg_meidling - avg_anchor) / 60, 1),
        "diversion_count": row.diversion_count or 0,
        "diversion_rate_pct": round((row.diversion_count or 0) / total * 100, 1) if total > 0 else 0,
        "on_time_count": row.on_time_count or 0,
        "on_time_pct": round((row.on_time_count or 0) / non_cancelled * 100, 1) if non_cancelled > 0 else 0,
    }


# ---------------------------------------------------------------------------
# GET /api/diversions  – list of detected route diversions (CJX skipped Baden)
# ---------------------------------------------------------------------------

@router.get("/diversions")
def get_diversions(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    result = db.execute(
        text("""
            WITH ternitz_trips AS (
                SELECT trip_id, line_name, planned_time, delay_seconds, cancelled
                FROM train_observations
                WHERE station_id = :ternitz_station
                  AND direction = 'to_wien'
                  AND line_product = 'regional'
                  AND planned_time >= NOW() - MAKE_INTERVAL(days => :days)
            ),
            meidling_trips AS (
                SELECT DISTINCT trip_id FROM train_observations
                WHERE station_id = :meidling_station
                  AND direction = 'to_wien'
                  AND line_product = 'regional'
            ),
            baden_trips AS (
                SELECT DISTINCT trip_id FROM train_observations
                WHERE station_id = :baden_station
                  AND direction = 'to_wien'
            ),
            meidling_delay AS (
                SELECT trip_id, delay_seconds AS meidling_delay
                FROM train_observations
                WHERE station_id = :meidling_station
                  AND direction = 'to_wien'
                  AND line_product = 'regional'
            )
            SELECT
                t.trip_id,
                t.line_name,
                t.planned_time,
                t.delay_seconds AS ternitz_delay,
                md.meidling_delay
            FROM ternitz_trips t
            JOIN meidling_trips m ON m.trip_id = t.trip_id
            LEFT JOIN meidling_delay md ON md.trip_id = t.trip_id
            WHERE NOT EXISTS (
                SELECT 1 FROM baden_trips b WHERE b.trip_id = t.trip_id
            )
            ORDER BY t.planned_time DESC
        """),
        {
            "ternitz_station": TERNITZ_STATION_ID,
            "meidling_station": WIEN_MEIDLING_STATION_ID,
            "baden_station": BADEN_STATION_ID,
            "days": days,
        },
    ).fetchall()

    diversions = [
        {
            "trip_id": r.trip_id,
            "line_name": r.line_name,
            "date": r.planned_time.date().isoformat() if r.planned_time else None,
            "planned_departure": r.planned_time.strftime("%H:%M") if r.planned_time else None,
            "ternitz_delay_minutes": round(r.ternitz_delay / 60, 1) if r.ternitz_delay else 0,
            "meidling_delay_minutes": round(r.meidling_delay / 60, 1) if r.meidling_delay else None,
        }
        for r in result
    ]

    return {
        "total_diversions": len(diversions),
        "period_days": days,
        "diversions": diversions,
    }
