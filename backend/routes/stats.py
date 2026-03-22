from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from database import get_db
from config import TERNITZ_STATION_ID, WIEN_MEIDLING_STATION_ID, WIEN_WESTBAHNHOF_STATION_ID, BADEN_STATION_ID, WIENER_NEUSTADT_STATION_ID

router = APIRouter()

# product filter: "regional" = CJX train, "subway" = U6
def _product_clause(product: Optional[str]) -> str:
    if product:
        return "AND line_product = :product"
    return ""


@router.get("/stats")
def get_stats(
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    result = db.execute(
        text(f"""
            SELECT
                COUNT(*) AS total_trains,
                COUNT(*) FILTER (WHERE cancelled = TRUE) AS cancelled_count,
                ROUND(AVG(delay_seconds) FILTER (WHERE cancelled = FALSE AND delay_seconds IS NOT NULL), 1) AS avg_delay,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delay_seconds)
                    FILTER (WHERE cancelled = FALSE AND delay_seconds IS NOT NULL) AS median_delay,
                MAX(delay_seconds) FILTER (WHERE cancelled = FALSE) AS max_delay,
                COUNT(*) FILTER (WHERE cancelled = FALSE AND (delay_seconds IS NULL OR delay_seconds < 60)) AS on_time_count,
                COUNT(*) FILTER (WHERE cancelled = FALSE AND delay_seconds IS NOT NULL AND delay_seconds < 300) AS under_5min_count,
                COUNT(*) FILTER (WHERE cancelled = FALSE AND delay_seconds IS NOT NULL AND delay_seconds < 600) AS under_10min_count,
                COUNT(*) FILTER (WHERE cancelled = FALSE) AS non_cancelled_count
            FROM train_observations
            WHERE direction = :direction
              {pc}
              AND planned_time >= NOW() - MAKE_INTERVAL(days => :days)
        """),
        {"direction": direction, "days": days, "product": product},
    )
    row = result.fetchone()

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
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    result = db.execute(
        text(f"""
            SELECT
                EXTRACT(HOUR FROM planned_time) AS hour,
                ROUND(AVG(delay_seconds), 1) AS avg_delay,
                COUNT(*) AS train_count
            FROM train_observations
            WHERE direction = :direction
              {pc}
              AND cancelled = FALSE
              AND delay_seconds IS NOT NULL
              AND planned_time >= NOW() - MAKE_INTERVAL(days => :days)
            GROUP BY EXTRACT(HOUR FROM planned_time)
            ORDER BY hour
        """),
        {"direction": direction, "days": days, "product": product},
    )
    return [
        {"hour": int(r.hour), "avg_delay_seconds": float(r.avg_delay), "train_count": r.train_count}
        for r in result.fetchall()
    ]


@router.get("/delays/daily")
def get_delays_daily(
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    day_names = {0: "Sonntag", 1: "Montag", 2: "Dienstag", 3: "Mittwoch", 4: "Donnerstag", 5: "Freitag", 6: "Samstag"}
    pc = _product_clause(product)
    result = db.execute(
        text(f"""
            SELECT
                EXTRACT(DOW FROM planned_time) AS dow,
                ROUND(AVG(delay_seconds), 1) AS avg_delay,
                COUNT(*) AS train_count
            FROM train_observations
            WHERE direction = :direction
              {pc}
              AND cancelled = FALSE
              AND delay_seconds IS NOT NULL
              AND planned_time >= NOW() - MAKE_INTERVAL(days => :days)
            GROUP BY EXTRACT(DOW FROM planned_time)
            ORDER BY dow
        """),
        {"direction": direction, "days": days, "product": product},
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
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    result = db.execute(
        text(f"""
            SELECT
                DATE(planned_time) AS date,
                ROUND(AVG(delay_seconds), 1) AS avg_delay,
                COUNT(*) AS train_count,
                COUNT(*) FILTER (WHERE cancelled = TRUE) AS cancelled_count
            FROM train_observations
            WHERE direction = :direction
              {pc}
              AND planned_time >= NOW() - MAKE_INTERVAL(days => :days)
            GROUP BY DATE(planned_time)
            ORDER BY date
        """),
        {"direction": direction, "days": days, "product": product},
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
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = _product_clause(product)
    result = db.execute(
        text(f"""
            SELECT
                CASE
                    WHEN delay_seconds IS NULL OR delay_seconds < 60 THEN 'Pünktlich'
                    WHEN delay_seconds < 120 THEN '1-2 Min'
                    WHEN delay_seconds < 300 THEN '2-5 Min'
                    WHEN delay_seconds < 600 THEN '5-10 Min'
                    ELSE '10+ Min'
                END AS bucket,
                COUNT(*) AS count
            FROM train_observations
            WHERE direction = :direction
              {pc}
              AND cancelled = FALSE
              AND planned_time >= NOW() - MAKE_INTERVAL(days => :days)
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN 'Pünktlich' THEN 1
                    WHEN '1-2 Min' THEN 2
                    WHEN '2-5 Min' THEN 3
                    WHEN '5-10 Min' THEN 4
                    ELSE 5
                END
        """),
        {"direction": direction, "days": days, "product": product},
    )
    return [{"bucket": r.bucket, "count": r.count} for r in result.fetchall()]


@router.get("/delays/by-station")
def get_delays_by_station(
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Average delay per station for delay-buildup visualization."""
    if direction == "to_wien":
        stations = [
            (TERNITZ_STATION_ID, "Ternitz", "regional"),
            (WIENER_NEUSTADT_STATION_ID, "Wiener Neustadt", "regional"),
            (BADEN_STATION_ID, "Baden bei Wien", "regional"),
            (WIEN_MEIDLING_STATION_ID, "Wien Meidling (CJX)", "regional"),
            (WIEN_MEIDLING_STATION_ID, "Wien Meidling (U6)", "subway"),
            (WIEN_WESTBAHNHOF_STATION_ID, "Wien Westbahnhof", "subway"),
        ]
    else:
        stations = [
            (WIEN_WESTBAHNHOF_STATION_ID, "Wien Westbahnhof", "subway"),
            (WIEN_MEIDLING_STATION_ID, "Wien Meidling (U6)", "subway"),
            (WIEN_MEIDLING_STATION_ID, "Wien Meidling (CJX)", "regional"),
            (BADEN_STATION_ID, "Baden bei Wien", "regional"),
            (WIENER_NEUSTADT_STATION_ID, "Wiener Neustadt", "regional"),
            (TERNITZ_STATION_ID, "Ternitz", "regional"),
        ]

    result = []
    for station_id, label, product in stations:
        row = db.execute(
            text("""
                SELECT
                    ROUND(AVG(delay_seconds) FILTER (WHERE cancelled = FALSE AND delay_seconds IS NOT NULL), 1) AS avg_delay,
                    COUNT(*) FILTER (WHERE cancelled = FALSE) AS train_count
                FROM train_observations
                WHERE station_id = :sid
                  AND direction = :direction
                  AND line_product = :product
                  AND planned_time >= NOW() - MAKE_INTERVAL(days => :days)
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
