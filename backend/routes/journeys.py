"""
Journey-level endpoints: track delay buildup across stations for each CJX/U6 trip.

to_wien journey (CJX): anchored on Ternitz departures.
  Stations tracked: Ternitz → Wiener Neustadt → Baden → Wien Meidling

to_ternitz journey (CJX): anchored on Wien Meidling CJX departures.
  Stations tracked: Wien Meidling → Baden → Wiener Neustadt → Ternitz

Diversion detection: trips.is_diverted flag (set by the collector).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import (
    TERNITZ_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIENER_NEUSTADT_STATION_ID,
    BADEN_STATION_ID,
)
from database import get_db

router = APIRouter()


def _parse_days(days_of_week: Optional[str]) -> list[int] | None:
    """Parse '1,2,3,4,5' → [1,2,3,4,5]. PostgreSQL DOW: 0=Sun … 6=Sat."""
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


def _fmt(ts) -> str | None:
    return ts.isoformat() if ts else None


def _delay_min(s) -> float | None:
    return round(s / 60, 1) if s is not None else None


# ---------------------------------------------------------------------------
# GET /api/journeys
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
    tol = 2  # minutes

    dow_clause = ""
    if dow_list:
        dow_clause = (
            "AND EXTRACT(DOW FROM anchor_ts.planned_departure AT TIME ZONE 'Europe/Vienna')"
            " = ANY(:dow_list)"
        )

    time_clause = ""
    time_list_expanded: list[int] = []
    if time_list:
        for t in time_list:
            for off in range(-tol, tol + 1):
                time_list_expanded.append(t + off)
        time_clause = """
        AND (
            EXTRACT(HOUR   FROM anchor_ts.planned_departure AT TIME ZONE 'Europe/Vienna') * 60
            + EXTRACT(MINUTE FROM anchor_ts.planned_departure AT TIME ZONE 'Europe/Vienna')
        ) = ANY(:time_list_expanded)
        """

    if direction == "to_wien":
        # Anchor: Ternitz departure
        # Route: Ternitz(dep) → WienerNeustadt(dep) → Baden(dep) → WienMeidling(arr)
        query = text(f"""
            SELECT
                tr.api_trip_id,
                l.code                                                                AS line_name,
                tr.is_diverted                                                        AS was_diverted,
                -- Ternitz
                anchor_ts.planned_departure                                           AS dep_ternitz_planned,
                anchor_ts.actual_departure                                            AS dep_ternitz_actual,
                anchor_ts.departure_delay_seconds                                     AS dep_ternitz_delay,
                (tr.status::text = 'cancelled' OR anchor_ts.cancelled_at_stop)       AS dep_ternitz_cancelled,
                anchor_ts.platform                                                    AS dep_ternitz_platform,
                -- Wiener Neustadt
                ts_wn.planned_departure                                               AS dep_wn_planned,
                ts_wn.actual_departure                                                AS dep_wn_actual,
                ts_wn.departure_delay_seconds                                         AS dep_wn_delay,
                ts_wn.cancelled_at_stop                                               AS dep_wn_cancelled,
                -- Baden
                ts_b.planned_departure                                                AS dep_baden_planned,
                ts_b.actual_departure                                                 AS dep_baden_actual,
                ts_b.departure_delay_seconds                                          AS dep_baden_delay,
                ts_b.cancelled_at_stop                                                AS dep_baden_cancelled,
                -- Wien Meidling (arrival)
                ts_m.planned_arrival                                                  AS arr_meidling_planned,
                ts_m.actual_arrival                                                   AS arr_meidling_actual,
                ts_m.arrival_delay_seconds                                            AS arr_meidling_delay,
                ts_m.cancelled_at_stop                                                AS arr_meidling_cancelled
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops anchor_ts ON anchor_ts.trip_id = tr.id
                                     AND anchor_ts.station_id = :ternitz_station
            LEFT JOIN trip_stops ts_wn ON ts_wn.trip_id = tr.id AND ts_wn.station_id = :wn_station
            LEFT JOIN trip_stops ts_b  ON ts_b.trip_id  = tr.id AND ts_b.station_id  = :baden_station
            LEFT JOIN trip_stops ts_m  ON ts_m.trip_id  = tr.id AND ts_m.station_id  = :meidling_station
            WHERE tr.direction::text = 'to_wien'
              AND l.product_type = 'regional'
              AND anchor_ts.planned_departure BETWEEN :date_from AND :date_to
              {dow_clause}
              {time_clause}
            ORDER BY anchor_ts.planned_departure DESC
            LIMIT :lim OFFSET :off
        """)
    else:
        # Anchor: Wien Meidling CJX departure
        # Route: WienMeidling(dep) → Baden(arr) → WienerNeustadt(arr) → Ternitz(arr)
        query = text(f"""
            SELECT
                tr.api_trip_id,
                l.code                                                                AS line_name,
                tr.is_diverted                                                        AS was_diverted,
                -- Wien Meidling
                anchor_ts.planned_departure                                           AS dep_meidling_planned,
                anchor_ts.actual_departure                                            AS dep_meidling_actual,
                anchor_ts.departure_delay_seconds                                     AS dep_meidling_delay,
                (tr.status::text = 'cancelled' OR anchor_ts.cancelled_at_stop)       AS dep_meidling_cancelled,
                anchor_ts.platform                                                    AS dep_meidling_platform,
                -- Baden (arrival)
                ts_b.planned_arrival                                                  AS arr_baden_planned,
                ts_b.actual_arrival                                                   AS arr_baden_actual,
                ts_b.arrival_delay_seconds                                            AS arr_baden_delay,
                ts_b.cancelled_at_stop                                                AS arr_baden_cancelled,
                -- Wiener Neustadt (arrival)
                ts_wn.planned_arrival                                                 AS arr_wn_planned,
                ts_wn.actual_arrival                                                  AS arr_wn_actual,
                ts_wn.arrival_delay_seconds                                           AS arr_wn_delay,
                ts_wn.cancelled_at_stop                                               AS arr_wn_cancelled,
                -- Ternitz (arrival)
                ts_t.planned_arrival                                                  AS arr_ternitz_planned,
                ts_t.actual_arrival                                                   AS arr_ternitz_actual,
                ts_t.arrival_delay_seconds                                            AS arr_ternitz_delay,
                ts_t.cancelled_at_stop                                                AS arr_ternitz_cancelled
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops anchor_ts ON anchor_ts.trip_id = tr.id
                                      AND anchor_ts.station_id = :meidling_station
            LEFT JOIN trip_stops ts_b  ON ts_b.trip_id  = tr.id AND ts_b.station_id  = :baden_station
            LEFT JOIN trip_stops ts_wn ON ts_wn.trip_id = tr.id AND ts_wn.station_id = :wn_station
            LEFT JOIN trip_stops ts_t  ON ts_t.trip_id  = tr.id AND ts_t.station_id  = :ternitz_station
            WHERE tr.direction::text = 'to_ternitz'
              AND l.product_type = 'regional'
              AND anchor_ts.planned_departure BETWEEN :date_from AND :date_to
              {dow_clause}
              {time_clause}
            ORDER BY anchor_ts.planned_departure DESC
            LIMIT :lim OFFSET :off
        """)

    anchor_station_col = ":ternitz_station" if direction == "to_wien" else ":meidling_station"
    anchor_dir = "to_wien" if direction == "to_wien" else "to_ternitz"
    count_query = text(f"""
        SELECT COUNT(*)
        FROM trips tr
        JOIN lines l ON l.id = tr.line_id
        JOIN trip_stops anchor_ts ON anchor_ts.trip_id = tr.id
                                 AND anchor_ts.station_id = {anchor_station_col}
        WHERE tr.direction::text = '{anchor_dir}'
          AND l.product_type = 'regional'
          AND anchor_ts.planned_departure BETWEEN :date_from AND :date_to
          {dow_clause}
          {time_clause}
    """)

    count_params: dict = {
        "ternitz_station": TERNITZ_STATION_ID,
        "meidling_station": WIEN_MEIDLING_STATION_ID,
        "date_from": df,
        "date_to": dt,
    }
    if dow_list:
        count_params["dow_list"] = dow_list
    if time_list_expanded:
        count_params["time_list_expanded"] = time_list_expanded

    total_count = db.execute(count_query, count_params).scalar() or 0

    params: dict = {
        "ternitz_station": TERNITZ_STATION_ID,
        "wn_station": WIENER_NEUSTADT_STATION_ID,
        "baden_station": BADEN_STATION_ID,
        "meidling_station": WIEN_MEIDLING_STATION_ID,
        "date_from": df,
        "date_to": dt,
        "lim": limit,
        "off": offset,
    }
    if dow_list:
        params["dow_list"] = dow_list
    if time_list_expanded:
        params["time_list_expanded"] = time_list_expanded

    rows = db.execute(query, params).fetchall()
    result = []

    for r in rows:
        if direction == "to_wien":
            result.append({
                "trip_id": r.api_trip_id,
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
                "trip_id": r.api_trip_id,
                "line_name": r.line_name,
                "direction": "to_ternitz",
                "was_diverted": bool(r.was_diverted),
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
                        "planned": _fmt(r.arr_baden_planned),
                        "actual": _fmt(r.arr_baden_actual),
                        "delay_seconds": r.arr_baden_delay,
                        "delay_minutes": _delay_min(r.arr_baden_delay),
                        "cancelled": bool(r.arr_baden_cancelled) if r.arr_baden_cancelled is not None else None,
                        "observed": r.arr_baden_planned is not None,
                    },
                    "wiener_neustadt": {
                        "planned": _fmt(r.arr_wn_planned),
                        "actual": _fmt(r.arr_wn_actual),
                        "delay_seconds": r.arr_wn_delay,
                        "delay_minutes": _delay_min(r.arr_wn_delay),
                        "cancelled": bool(r.arr_wn_cancelled) if r.arr_wn_cancelled is not None else None,
                        "observed": r.arr_wn_planned is not None,
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

    return {"total": total_count, "offset": offset, "limit": limit, "journeys": result}


# ---------------------------------------------------------------------------
# GET /api/journeys/stats
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
    tol = 2

    dow_clause = ""
    if dow_list:
        dow_clause = (
            "AND EXTRACT(DOW FROM anchor_ts.planned_departure AT TIME ZONE 'Europe/Vienna')"
            " = ANY(:dow_list)"
        )

    time_clause = ""
    time_list_expanded: list[int] = []
    if time_list:
        for t in time_list:
            for off in range(-tol, tol + 1):
                time_list_expanded.append(t + off)
        time_clause = """
        AND (
            EXTRACT(HOUR   FROM anchor_ts.planned_departure AT TIME ZONE 'Europe/Vienna') * 60
            + EXTRACT(MINUTE FROM anchor_ts.planned_departure AT TIME ZONE 'Europe/Vienna')
        ) = ANY(:time_list_expanded)
        """

    anchor_station = TERNITZ_STATION_ID if direction == "to_wien" else WIEN_MEIDLING_STATION_ID
    delay_field_anchor = "anchor_ts.departure_delay_seconds"
    delay_field_meidling = (
        "ts_m.arrival_delay_seconds" if direction == "to_wien" else "ts_m.departure_delay_seconds"
    )

    row = db.execute(
        text(f"""
            WITH anchor AS (
                SELECT tr.id AS trip_id,
                       {delay_field_anchor}               AS delay_anchor,
                       (tr.status::text = 'cancelled')    AS cancelled,
                       tr.is_diverted
                FROM trips tr
                JOIN lines l ON l.id = tr.line_id
                JOIN trip_stops anchor_ts ON anchor_ts.trip_id = tr.id
                                         AND anchor_ts.station_id = :anchor_station
                WHERE tr.direction::text = :direction
                  AND l.product_type = 'regional'
                  AND anchor_ts.planned_departure BETWEEN :date_from AND :date_to
                  {dow_clause}
                  {time_clause}
            ),
            meidling AS (
                SELECT trip_id, {delay_field_meidling} AS delay_m
                FROM trip_stops ts_m
                WHERE ts_m.station_id = :meidling_station
            )
            SELECT
                COUNT(DISTINCT anchor.trip_id)                                              AS total_journeys,
                COUNT(DISTINCT anchor.trip_id) FILTER (WHERE anchor.cancelled)              AS cancelled_count,
                ROUND(
                    AVG(anchor.delay_anchor)
                    FILTER (WHERE NOT anchor.cancelled AND anchor.delay_anchor IS NOT NULL),
                    1
                )                                                                           AS avg_delay_anchor,
                ROUND(AVG(m.delay_m) FILTER (WHERE m.delay_m IS NOT NULL), 1)              AS avg_delay_meidling,
                COUNT(DISTINCT anchor.trip_id) FILTER (
                    WHERE NOT anchor.cancelled
                      AND (anchor.delay_anchor IS NULL OR anchor.delay_anchor < 60)
                )                                                                           AS on_time_count,
                COUNT(DISTINCT anchor.trip_id) FILTER (WHERE anchor.is_diverted)           AS diversion_count
            FROM anchor
            LEFT JOIN meidling m ON m.trip_id = anchor.trip_id
        """),
        {
            "anchor_station": anchor_station,
            "meidling_station": WIEN_MEIDLING_STATION_ID,
            "direction": direction,
            "date_from": df,
            "date_to": dt,
            **({"dow_list": dow_list} if dow_list else {}),
            **({"time_list_expanded": time_list_expanded} if time_list_expanded else {}),
        },
    ).fetchone()

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
# GET /api/diversions
# ---------------------------------------------------------------------------

@router.get("/diversions")
def get_diversions(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """List CJX trips that were diverted (skipped Baden bei Wien).

    Uses the is_diverted flag set by the collector — no CTE needed in V2.
    """
    result = db.execute(
        text("""
            SELECT
                tr.api_trip_id                          AS trip_id,
                l.code                                  AS line_name,
                ts_t.planned_departure,
                ts_t.departure_delay_seconds            AS ternitz_delay,
                ts_m.arrival_delay_seconds              AS meidling_delay
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops ts_t ON ts_t.trip_id = tr.id AND ts_t.station_id = :ternitz_station
            LEFT JOIN trip_stops ts_m ON ts_m.trip_id = tr.id AND ts_m.station_id = :meidling_station
            WHERE tr.is_diverted = TRUE
              AND tr.direction::text = 'to_wien'
              AND tr.service_date >= CURRENT_DATE - MAKE_INTERVAL(days => :days)
            ORDER BY ts_t.planned_departure DESC
        """),
        {
            "ternitz_station": TERNITZ_STATION_ID,
            "meidling_station": WIEN_MEIDLING_STATION_ID,
            "days": days,
        },
    ).fetchall()

    diversions = [
        {
            "trip_id": r.trip_id,
            "line_name": r.line_name,
            "date": r.planned_departure.date().isoformat() if r.planned_departure else None,
            "planned_departure": r.planned_departure.strftime("%H:%M") if r.planned_departure else None,
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
