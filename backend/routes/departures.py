from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from database import get_db
from config import TERNITZ_STATION_ID, WIEN_WESTBAHNHOF_STATION_ID, WIEN_MEIDLING_STATION_ID

router = APIRouter()


@router.get("/departures")
def get_departures(
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    limit: int = Query(20, ge=1, le=100),
    product: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = "AND t.line_product = :product" if product else ""

    # Status filter: on_time (<60s delay), delayed (>=60s), cancelled
    sc = ""
    if status == "on_time":
        sc = "AND t.cancelled = FALSE AND (t.delay_seconds IS NULL OR t.delay_seconds < 60)"
    elif status == "delayed":
        sc = "AND t.cancelled = FALSE AND t.delay_seconds IS NOT NULL AND t.delay_seconds >= 60"
    elif status == "cancelled":
        sc = "AND t.cancelled = TRUE"

    # Show only origin-station observations to avoid counting intermediate stops.
    # to_wien:    CJX origin = Ternitz
    # to_ternitz: U6 origin = Westbahnhof, CJX origin = Wien Meidling
    if direction == "to_wien":
        origin_stations = [TERNITZ_STATION_ID]
    else:
        origin_stations = [WIEN_WESTBAHNHOF_STATION_ID, WIEN_MEIDLING_STATION_ID]

    # DISTINCT ON deduplicates: if the same trip has both an arrival and a departure
    # row at the same station (legacy data), keep only the departure (latest planned_time).
    # Wrapped in subquery so we can re-sort by planned_time and apply LIMIT.
    result = db.execute(
        text(f"""
            SELECT * FROM (
                SELECT DISTINCT ON (t.trip_id)
                    t.trip_id,
                    t.train_number,
                    t.line_name,
                    t.line_product,
                    t.destination,
                    t.planned_time,
                    t.actual_time,
                    t.delay_seconds,
                    t.cancelled,
                    t.platform,
                    t.station_id,
                    s.name AS station_name
                FROM train_observations t
                LEFT JOIN stations s ON s.id = t.station_id
                WHERE t.direction = :direction
                  AND t.station_id = ANY(:origin_stations)
                  {pc}
                  {sc}
                ORDER BY t.trip_id, t.planned_time DESC
            ) sub
            ORDER BY planned_time DESC
            LIMIT :limit
        """),
        {"direction": direction, "limit": limit, "product": product,
         "origin_stations": origin_stations},
    )

    rows = result.fetchall()
    return [
        {
            "trip_id": r.trip_id,
            "train_number": r.train_number,
            "line_name": r.line_name,
            "line_product": r.line_product,
            "destination": r.destination,
            "planned_time": r.planned_time.isoformat() if r.planned_time else None,
            "actual_time": r.actual_time.isoformat() if r.actual_time else None,
            "delay_seconds": r.delay_seconds,
            "delay_minutes": round(r.delay_seconds / 60, 1) if r.delay_seconds else 0,
            "cancelled": r.cancelled,
            "platform": r.platform,
            "station_id": r.station_id,
            "station_name": r.station_name,
        }
        for r in rows
    ]
