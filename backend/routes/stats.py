from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import (
    TERNITZ_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIEN_WESTBAHNHOF_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIENER_NEUSTADT_STATION_ID,
    BADEN_STATION_ID,
)
from database import get_db

router = APIRouter()


def _product_clause(product: Optional[str]) -> str:
    return "AND l.product_type = :product" if product else ""


def _anchor_station(direction: str, product: Optional[str]) -> str:
    """Return the origin station used as delay anchor for a given direction+product combo."""
    if direction == "to_wien":
        return WIEN_MEIDLING_STATION_ID if product == "subway" else TERNITZ_STATION_ID
    # to_ternitz
    return WIEN_WESTBAHNHOF_STATION_ID if product == "subway" else WIEN_MEIDLING_STATION_ID


@router.get("/stats")
def get_stats(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    anchor = _anchor_station(direction, product)

    row = db.execute(
        text(f"""
            SELECT
                COUNT(*)                                                                      AS total_trains,
                COUNT(*) FILTER (WHERE tr.status::text = 'cancelled' OR ts.cancelled_at_stop) AS cancelled_count,
                ROUND(
                    AVG(ts.departure_delay_seconds)
                    FILTER (WHERE tr.status::text != 'cancelled' AND ts.departure_delay_seconds IS NOT NULL),
                    1
                )                                                                             AS avg_delay,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ts.departure_delay_seconds)
                    FILTER (WHERE tr.status::text != 'cancelled' AND ts.departure_delay_seconds IS NOT NULL)
                                                                                              AS median_delay,
                MAX(ts.departure_delay_seconds)
                    FILTER (WHERE tr.status::text != 'cancelled')                             AS max_delay,
                COUNT(*) FILTER (
                    WHERE tr.status::text != 'cancelled'
                      AND ts.cancelled_at_stop = FALSE
                      AND (ts.departure_delay_seconds IS NULL OR ts.departure_delay_seconds < 60)
                )                                                                             AS on_time_count,
                COUNT(*) FILTER (
                    WHERE tr.status::text != 'cancelled'
                      AND ts.departure_delay_seconds IS NOT NULL
                      AND ts.departure_delay_seconds < 300
                )                                                                             AS under_5min_count,
                COUNT(*) FILTER (
                    WHERE tr.status::text != 'cancelled'
                      AND ts.departure_delay_seconds IS NOT NULL
                      AND ts.departure_delay_seconds < 600
                )                                                                             AS under_10min_count,
                COUNT(*) FILTER (WHERE tr.status::text != 'cancelled')                       AS non_cancelled_count
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            LEFT JOIN trip_stops ts ON ts.trip_id = tr.id AND ts.station_id = :anchor
            WHERE tr.direction::text = :direction
              {pc}
              AND tr.service_date >= CURRENT_DATE - MAKE_INTERVAL(days => :days)
        """),
        {"direction": direction, "days": days, "product": product, "anchor": anchor},
    ).fetchone()

    total = row.total_trains or 0
    non_cancelled = row.non_cancelled_count or 0

    return {
        "direction": direction,
        "product": product,
        "period_days": days,
        "total_trains": total,
        "cancelled_count": row.cancelled_count or 0,
        "cancellation_rate_pct": round((row.cancelled_count or 0) / total * 100, 1) if total > 0 else 0,
        "delay_stats": {
            "average_seconds": float(row.avg_delay) if row.avg_delay else 0,
            "average_minutes": round(float(row.avg_delay) / 60, 1) if row.avg_delay else 0,
            "median_seconds": float(row.median_delay) if row.median_delay else 0,
            "median_minutes": round(float(row.median_delay) / 60, 1) if row.median_delay else 0,
            "max_seconds": row.max_delay or 0,
            "max_minutes": round((row.max_delay or 0) / 60, 1),
            "on_time_pct": round((row.on_time_count or 0) / non_cancelled * 100, 1) if non_cancelled > 0 else 0,
            "under_5min_pct": round((row.under_5min_count or 0) / non_cancelled * 100, 1) if non_cancelled > 0 else 0,
            "under_10min_pct": round((row.under_10min_count or 0) / non_cancelled * 100, 1) if non_cancelled > 0 else 0,
        },
    }


@router.get("/delays/hourly")
def get_delays_hourly(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    anchor = _anchor_station(direction, product)

    result = db.execute(
        text(f"""
            SELECT
                EXTRACT(HOUR FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna') AS hour,
                ROUND(AVG(ts.departure_delay_seconds), 1)                            AS avg_delay,
                COUNT(*)                                                              AS train_count
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops ts ON ts.trip_id = tr.id AND ts.station_id = :anchor
            WHERE tr.direction::text = :direction
              {pc}
              AND tr.status::text != 'cancelled'
              AND ts.departure_delay_seconds IS NOT NULL
              AND ts.planned_departure IS NOT NULL
              AND tr.service_date >= CURRENT_DATE - MAKE_INTERVAL(days => :days)
            GROUP BY EXTRACT(HOUR FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna')
            ORDER BY hour
        """),
        {"direction": direction, "days": days, "product": product, "anchor": anchor},
    )
    return [
        {"hour": int(r.hour), "avg_delay_seconds": float(r.avg_delay), "train_count": r.train_count}
        for r in result.fetchall()
    ]


@router.get("/delays/daily")
def get_delays_daily(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    # PostgreSQL DOW (0=Sun … 6=Sat) kept for frontend compatibility
    day_names = {0: "Sonntag", 1: "Montag", 2: "Dienstag", 3: "Mittwoch",
                 4: "Donnerstag", 5: "Freitag", 6: "Samstag"}
    pc = _product_clause(product)
    anchor = _anchor_station(direction, product)

    result = db.execute(
        text(f"""
            SELECT
                EXTRACT(DOW FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna') AS dow,
                ROUND(AVG(ts.departure_delay_seconds), 1)                           AS avg_delay,
                COUNT(*)                                                             AS train_count
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops ts ON ts.trip_id = tr.id AND ts.station_id = :anchor
            WHERE tr.direction::text = :direction
              {pc}
              AND tr.status::text != 'cancelled'
              AND ts.departure_delay_seconds IS NOT NULL
              AND ts.planned_departure IS NOT NULL
              AND tr.service_date >= CURRENT_DATE - MAKE_INTERVAL(days => :days)
            GROUP BY EXTRACT(DOW FROM ts.planned_departure AT TIME ZONE 'Europe/Vienna')
            ORDER BY dow
        """),
        {"direction": direction, "days": days, "product": product, "anchor": anchor},
    )
    return [
        {
            "day_of_week": int(r.dow),
            "day_name": day_names.get(int(r.dow), ""),
            "avg_delay_seconds": float(r.avg_delay),
            "train_count": r.train_count,
        }
        for r in result.fetchall()
    ]


@router.get("/delays/trend")
def get_delays_trend(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    anchor = _anchor_station(direction, product)

    result = db.execute(
        text(f"""
            SELECT
                tr.service_date                                                    AS date,
                ROUND(AVG(ts.departure_delay_seconds), 1)                         AS avg_delay,
                COUNT(*)                                                           AS train_count,
                COUNT(*) FILTER (WHERE tr.status::text = 'cancelled')             AS cancelled_count
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            LEFT JOIN trip_stops ts ON ts.trip_id = tr.id AND ts.station_id = :anchor
            WHERE tr.direction::text = :direction
              {pc}
              AND tr.service_date >= CURRENT_DATE - MAKE_INTERVAL(days => :days)
            GROUP BY tr.service_date
            ORDER BY tr.service_date
        """),
        {"direction": direction, "days": days, "product": product, "anchor": anchor},
    )
    return [
        {
            "date": r.date.isoformat(),
            "avg_delay_seconds": float(r.avg_delay) if r.avg_delay else 0,
            "train_count": r.train_count,
            "cancelled_count": r.cancelled_count,
        }
        for r in result.fetchall()
    ]


@router.get("/delays/distribution")
def get_delay_distribution(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    anchor = _anchor_station(direction, product)

    result = db.execute(
        text(f"""
            SELECT
                CASE
                    WHEN ts.departure_delay_seconds IS NULL OR ts.departure_delay_seconds < 60  THEN 'Pünktlich'
                    WHEN ts.departure_delay_seconds < 120                                       THEN '1-2 Min'
                    WHEN ts.departure_delay_seconds < 300                                       THEN '2-5 Min'
                    WHEN ts.departure_delay_seconds < 600                                       THEN '5-10 Min'
                    ELSE '10+ Min'
                END AS bucket,
                COUNT(*) AS count
            FROM trips tr
            JOIN lines l ON l.id = tr.line_id
            JOIN trip_stops ts ON ts.trip_id = tr.id AND ts.station_id = :anchor
            WHERE tr.direction::text = :direction
              {pc}
              AND tr.status::text != 'cancelled'
              AND tr.service_date >= CURRENT_DATE - MAKE_INTERVAL(days => :days)
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN 'Pünktlich' THEN 1
                    WHEN '1-2 Min'   THEN 2
                    WHEN '2-5 Min'   THEN 3
                    WHEN '5-10 Min'  THEN 4
                    ELSE 5
                END
        """),
        {"direction": direction, "days": days, "product": product, "anchor": anchor},
    )
    return [{"bucket": r.bucket, "count": r.count} for r in result.fetchall()]


@router.get("/delays/by-station")
def get_delays_by_station(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Average delay per station for delay-buildup visualisation."""
    if direction == "to_wien":
        # For CJX: departure delay; for U6 at Meidling: departure delay
        stations = [
            (TERNITZ_STATION_ID,          "Ternitz",              "regional",  "departure"),
            (WIENER_NEUSTADT_STATION_ID,  "Wiener Neustadt",      "regional",  "departure"),
            (BADEN_STATION_ID,            "Baden bei Wien",       "regional",  "departure"),
            (WIEN_MEIDLING_STATION_ID,    "Wien Meidling (CJX)",  "regional",  "arrival"),
            (WIEN_MEIDLING_STATION_ID,    "Wien Meidling (U6)",   "subway",    "departure"),
            (WIEN_WESTBAHNHOF_STATION_ID, "Wien Westbahnhof",     "subway",    "arrival"),
        ]
    else:
        stations = [
            (WIEN_WESTBAHNHOF_STATION_ID, "Wien Westbahnhof",     "subway",    "departure"),
            (WIEN_MEIDLING_STATION_ID,    "Wien Meidling (U6)",   "subway",    "arrival"),
            (WIEN_MEIDLING_STATION_ID,    "Wien Meidling (CJX)",  "regional",  "departure"),
            (BADEN_STATION_ID,            "Baden bei Wien",       "regional",  "arrival"),
            (WIENER_NEUSTADT_STATION_ID,  "Wiener Neustadt",      "regional",  "arrival"),
            (TERNITZ_STATION_ID,          "Ternitz",              "regional",  "arrival"),
        ]

    result = []
    for station_id, label, product, delay_col in stations:
        delay_field = (
            "ts.departure_delay_seconds" if delay_col == "departure" else "ts.arrival_delay_seconds"
        )
        row = db.execute(
            text(f"""
                SELECT
                    ROUND(
                        AVG({delay_field})
                        FILTER (WHERE tr.status::text != 'cancelled' AND {delay_field} IS NOT NULL),
                        1
                    ) AS avg_delay,
                    COUNT(*) FILTER (WHERE tr.status::text != 'cancelled') AS train_count
                FROM trip_stops ts
                JOIN trips tr ON tr.id = ts.trip_id
                JOIN lines  l ON l.id  = tr.line_id
                WHERE ts.station_id        = :sid
                  AND tr.direction::text   = :direction
                  AND l.product_type       = :product
                  AND tr.service_date >= CURRENT_DATE - MAKE_INTERVAL(days => :days)
            """),
            {"sid": station_id, "direction": direction, "product": product, "days": days},
        ).fetchone()
        result.append({
            "station": label,
            "station_id": station_id,
            "avg_delay_seconds": float(row.avg_delay) if row.avg_delay else 0,
            "avg_delay_minutes": round(float(row.avg_delay) / 60, 1) if row.avg_delay else 0,
            "train_count": row.train_count or 0,
        })
    return result
