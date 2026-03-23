from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import TERNITZ_STATION_ID, WIEN_WESTBAHNHOF_STATION_ID, WIEN_MEIDLING_STATION_ID
from database import get_db

router = APIRouter()


@router.get("/departures")
def get_departures(
    direction: str = Query("to_wien", pattern="^(to_wien|to_ternitz)$"),
    limit: int = Query(20, ge=1, le=100),
    product: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = "AND l.product_type = :product" if product else ""

    # Status filter — maps V1 semantics onto V2 columns
    sc = ""
    if status == "on_time":
        sc = (
            "AND tr.status::text != 'cancelled'"
            " AND ts.cancelled_at_stop = FALSE"
            " AND (ts.departure_delay_seconds IS NULL OR ts.departure_delay_seconds < 60)"
        )
    elif status == "delayed":
        sc = (
            "AND tr.status::text != 'cancelled'"
            " AND ts.cancelled_at_stop = FALSE"
            " AND ts.departure_delay_seconds >= 60"
        )
    elif status == "cancelled":
        sc = "AND (tr.status::text = 'cancelled' OR ts.cancelled_at_stop = TRUE)"

    # Show origin-station observations only to avoid inflating per-trip counts
    # to_wien:    CJX origin = Ternitz
    # to_ternitz: U6 origin  = Westbahnhof, CJX origin = Wien Meidling
    if direction == "to_wien":
        origin_stations = [TERNITZ_STATION_ID]
    else:
        origin_stations = [WIEN_WESTBAHNHOF_STATION_ID, WIEN_MEIDLING_STATION_ID]

    result = db.execute(
        text(f"""
            SELECT * FROM (
                SELECT DISTINCT ON (tr.api_trip_id)
                    tr.api_trip_id                                              AS trip_id,
                    tr.train_number,
                    l.code                                                      AS line_name,
                    l.product_type                                              AS line_product,
                    tr.destination_name                                         AS destination,
                    ts.planned_departure                                        AS planned_time,
                    ts.actual_departure                                         AS actual_time,
                    ts.departure_delay_seconds                                  AS delay_seconds,
                    (tr.status::text = 'cancelled' OR ts.cancelled_at_stop)    AS cancelled,
                    ts.platform,
                    ts.station_id,
                    s.name                                                      AS station_name
                FROM trip_stops ts
                JOIN trips    tr ON tr.id  = ts.trip_id
                JOIN lines     l ON l.id   = tr.line_id
                JOIN stations  s ON s.id   = ts.station_id
                WHERE tr.direction::text = :direction
                  AND ts.station_id = ANY(:origin_stations)
                  AND ts.planned_departure IS NOT NULL
                  {pc}
                  {sc}
                ORDER BY tr.api_trip_id, ts.planned_departure DESC
            ) sub
            ORDER BY planned_time DESC
            LIMIT :limit
        """),
        {
            "direction": direction,
            "limit": limit,
            "product": product,
            "origin_stations": origin_stations,
        },
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
