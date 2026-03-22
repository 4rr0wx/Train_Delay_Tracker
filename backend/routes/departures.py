from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from database import get_db

router = APIRouter()


@router.get("/departures")
def get_departures(
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    limit: int = Query(20, ge=1, le=100),
    product: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    pc = "AND line_product = :product" if product else ""

    # Status filter: on_time (<60s delay), delayed (>=60s), cancelled
    sc = ""
    if status == "on_time":
        sc = "AND cancelled = FALSE AND (delay_seconds IS NULL OR delay_seconds < 60)"
    elif status == "delayed":
        sc = "AND cancelled = FALSE AND delay_seconds IS NOT NULL AND delay_seconds >= 60"
    elif status == "cancelled":
        sc = "AND cancelled = TRUE"

    result = db.execute(
        text(f"""
            SELECT
                trip_id,
                line_name,
                line_product,
                destination,
                planned_time,
                actual_time,
                delay_seconds,
                cancelled,
                platform,
                station_id
            FROM train_observations
            WHERE direction = :direction
              {pc}
              {sc}
            ORDER BY planned_time DESC
            LIMIT :limit
        """),
        {"direction": direction, "limit": limit, "product": product},
    )

    rows = result.fetchall()
    return [
        {
            "trip_id": r.trip_id,
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
        }
        for r in rows
    ]
