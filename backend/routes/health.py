from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db

router = APIRouter()


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        return {"status": "error", "database": str(e)}

    last_run = db.execute(
        text("""
            SELECT started_at, completed_at, status::text AS status,
                   duration_ms, trips_new, trips_updated,
                   trip_stops_new, trip_stops_updated,
                   api_calls_made, api_calls_failed
            FROM collection_runs
            ORDER BY started_at DESC
            LIMIT 1
        """)
    ).fetchone()

    collection = None
    if last_run:
        collection = {
            "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
            "last_collection_at": last_run.completed_at.isoformat() if last_run.completed_at else None,
            "last_collection_status": last_run.status,
            "duration_ms": last_run.duration_ms,
            "trips_new": last_run.trips_new,
            "trips_updated": last_run.trips_updated,
            "trip_stops_new": last_run.trip_stops_new,
            "trip_stops_updated": last_run.trip_stops_updated,
            "api_calls_made": last_run.api_calls_made,
            "api_calls_failed": last_run.api_calls_failed,
        }

    return {"status": "ok", "database": "connected", "last_collection": collection}
