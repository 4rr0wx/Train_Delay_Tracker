import logging
from datetime import datetime

import httpx
from sqlalchemy.dialects.postgresql import insert

from config import API_BASE_URL, TERNITZ_STATION_ID, WIEN_STATION_ID, POLL_DURATION_MINUTES
from database import SessionLocal
from models import TrainObservation

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0)

# Wien-bound destination keywords
WIEN_DESTINATIONS = {"wien", "vienna", "meidling", "floridsdorf", "hütteldorf", "westbahnhof"}


def _is_wien_bound(destination: str) -> bool:
    if not destination:
        return False
    dest_lower = destination.lower()
    return any(kw in dest_lower for kw in WIEN_DESTINATIONS)


def _fetch_departures(station_id: str, duration: int = POLL_DURATION_MINUTES) -> list[dict]:
    url = f"{API_BASE_URL}/stops/{station_id}/departures"
    params = {
        "duration": duration,
        "bus": "false",
        "tram": "false",
        "ferry": "false",
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("departures", data) if isinstance(data, dict) else data
    except Exception as e:
        logger.error("Failed to fetch departures for station %s: %s", station_id, e)
        return []


def _fetch_arrivals(station_id: str, duration: int = POLL_DURATION_MINUTES) -> list[dict]:
    url = f"{API_BASE_URL}/stops/{station_id}/arrivals"
    params = {
        "duration": duration,
        "bus": "false",
        "tram": "false",
        "ferry": "false",
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("arrivals", data) if isinstance(data, dict) else data
    except Exception as e:
        logger.error("Failed to fetch arrivals for station %s: %s", station_id, e)
        return []


def _parse_observation(item: dict, station_id: str, direction: str) -> dict | None:
    trip_id = item.get("tripId")
    planned_when = item.get("plannedWhen")
    if not trip_id or not planned_when:
        return None

    line = item.get("line", {}) or {}
    remarks_raw = item.get("remarks", [])
    remarks_data = [{"type": r.get("type"), "text": r.get("text")} for r in (remarks_raw or [])]

    return {
        "trip_id": trip_id,
        "station_id": station_id,
        "direction": direction,
        "line_name": line.get("name"),
        "line_product": line.get("product"),
        "destination": item.get("direction") or item.get("destination", {}).get("name"),
        "planned_time": planned_when,
        "actual_time": item.get("when"),
        "delay_seconds": item.get("delay"),
        "cancelled": item.get("cancelled", False) or False,
        "platform": item.get("platform"),
        "remarks": remarks_data if remarks_data else None,
    }


def _upsert_observations(observations: list[dict]):
    if not observations:
        return

    db = SessionLocal()
    try:
        for obs in observations:
            stmt = insert(TrainObservation).values(**obs)
            stmt = stmt.on_conflict_do_update(
                index_elements=["trip_id", "planned_time"],
                set_={
                    "actual_time": stmt.excluded.actual_time,
                    "delay_seconds": stmt.excluded.delay_seconds,
                    "cancelled": stmt.excluded.cancelled,
                    "platform": stmt.excluded.platform,
                    "remarks": stmt.excluded.remarks,
                    "last_updated_at": datetime.utcnow(),
                },
            )
            db.execute(stmt)
        db.commit()
        logger.info("Upserted %d observations", len(observations))
    except Exception as e:
        db.rollback()
        logger.error("Failed to upsert observations: %s", e)
    finally:
        db.close()


def collect_data():
    logger.info("Starting data collection...")
    observations = []

    # Ternitz departures -> Wien direction
    departures = _fetch_departures(TERNITZ_STATION_ID)
    for item in departures:
        dest = item.get("direction", "") or ""
        if _is_wien_bound(dest):
            obs = _parse_observation(item, TERNITZ_STATION_ID, "to_wien")
            if obs:
                observations.append(obs)

    # Ternitz arrivals -> from Wien direction (to_ternitz)
    arrivals = _fetch_arrivals(TERNITZ_STATION_ID)
    for item in arrivals:
        obs = _parse_observation(item, TERNITZ_STATION_ID, "to_ternitz")
        if obs:
            observations.append(obs)

    # Wien Westbahnhof departures & arrivals (U-Bahn + train)
    wien_departures = _fetch_departures(WIEN_STATION_ID)
    for item in wien_departures:
        obs = _parse_observation(item, WIEN_STATION_ID, "to_ternitz")
        if obs:
            observations.append(obs)

    wien_arrivals = _fetch_arrivals(WIEN_STATION_ID)
    for item in wien_arrivals:
        obs = _parse_observation(item, WIEN_STATION_ID, "to_wien")
        if obs:
            observations.append(obs)

    _upsert_observations(observations)
    logger.info("Collection complete: %d observations processed", len(observations))
