from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db

router = APIRouter()


@router.get("/departures")
def get_departures(
    direction: str = Query("to_wien", regex="^(to_wien|to_ternitz)$"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = db.execute(
        text("""
            SELECT
                trip_id,
                line_name,
                line_product,
                destination,
                planned_time,
                actual_time,
                delay_seconds,
                cancelled,
                platform
            FROM train_observations
            WHERE direction = :direction
            ORDER BY planned_time DESC
            LIMIT :limit
        """),
        {"direction": direction, "limit": limit},
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
        }
        for r in rows
    ]
