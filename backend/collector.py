"""
Data collector for the commute route: Ternitz <-> Wien Westbahnhof

Commute legs:
  to_wien:    Ternitz --[CJX]--> Wien Meidling --[U6]--> Wien Westbahnhof (U6)
  to_ternitz: Wien Westbahnhof (U6) --[U6]--> Wien Meidling --[CJX]--> Ternitz

Only CJX trains and U6 subway trains are collected.
"""

import logging
from datetime import datetime

import httpx
from sqlalchemy.dialects.postgresql import insert

from config import (
    API_BASE_URL,
    TERNITZ_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIEN_WESTBAHNHOF_STATION_ID,
    POLL_DURATION_MINUTES,
    RELEVANT_TRAIN_LINE,
    RELEVANT_SUBWAY_LINE,
)
from database import SessionLocal
from models import TrainObservation

logger = logging.getLogger(__name__)
TIMEOUT = httpx.Timeout(30.0)

# --- API helpers -----------------------------------------------------------

def _get(station_id: str, endpoint: str, extra_params: dict | None = None) -> list[dict]:
    url = f"{API_BASE_URL}/stops/{station_id}/{endpoint}"
    params = {"duration": POLL_DURATION_MINUTES, "bus": "false", "tram": "false", "ferry": "false"}
    if extra_params:
        params.update(extra_params)
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("isHafasError"):
                logger.warning("HAFAS error for %s/%s: %s", station_id, endpoint, data.get("message", ""))
                return []
            return data if isinstance(data, list) else data.get(endpoint, [])
    except Exception as e:
        logger.error("Failed to fetch %s for station %s: %s", endpoint, station_id, e)
        return []


# For Wien Meidling U6: must explicitly exclude all non-subway modes to avoid HAFAS errors
_SUBWAY_ONLY = {
    "national": "false",
    "nationalExpress": "false",
    "interregional": "false",
    "regional": "false",
    "suburban": "false",
}


# --- Filtering helpers -----------------------------------------------------

def _line_name(item: dict) -> str:
    return ((item.get("line") or {}).get("name") or "").upper()


def _direction(item: dict) -> str:
    return (item.get("direction") or item.get("provenance") or "").lower()


def _is_cjx(item: dict) -> bool:
    return _line_name(item).startswith(RELEVANT_TRAIN_LINE)


def _is_u6(item: dict) -> bool:
    return _line_name(item) == RELEVANT_SUBWAY_LINE


# CJX Wien-bound: trains going to Wien or Laa an der Thaya (via Wien)
# Exclude short-turns to Wr. Neustadt and southbound trains to Payerbach
_WIEN_BOUND_KEYWORDS = {"wien", "laa"}
_NOT_WIEN_BOUND_KEYWORDS = {"payerbach", "reichenau"}


def _cjx_is_wien_bound(item: dict) -> bool:
    dest = _direction(item)
    if any(kw in dest for kw in _NOT_WIEN_BOUND_KEYWORDS):
        return False
    return any(kw in dest for kw in _WIEN_BOUND_KEYWORDS)


# U6 direction at Wien Meidling
_U6_TO_WIEN = "floridsdorf"       # U6 northbound → passes Wien Westbahnhof
_U6_TO_TERNITZ = "siebenhirten"   # U6 southbound → passes Wien Westbahnhof on way south


# --- Parse & upsert --------------------------------------------------------

def _parse(item: dict, station_id: str, direction: str) -> dict | None:
    trip_id = item.get("tripId")
    planned_when = item.get("plannedWhen")
    if not trip_id or not planned_when:
        return None

    line = item.get("line") or {}
    remarks_raw = item.get("remarks") or []
    remarks = [{"type": r.get("type"), "text": r.get("text")} for r in remarks_raw] or None

    return {
        "trip_id": trip_id,
        "station_id": station_id,
        "direction": direction,
        "line_name": line.get("name"),
        "line_product": line.get("product"),
        "destination": item.get("direction") or (item.get("destination") or {}).get("name"),
        "planned_time": planned_when,
        "actual_time": item.get("when"),
        "delay_seconds": item.get("delay"),
        "cancelled": bool(item.get("cancelled")),
        "platform": item.get("platform"),
        "remarks": remarks,
    }


def _upsert(observations: list[dict]):
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
        logger.error("Upsert failed: %s", e)
    finally:
        db.close()


# --- Main collection -------------------------------------------------------

def collect_data():
    logger.info("Collecting commute data...")
    obs = []

    # -----------------------------------------------------------------------
    # LEG 1: CJX at Ternitz
    # -----------------------------------------------------------------------

    # to_wien: CJX departures from Ternitz heading towards Wien / Laa
    for item in _get(TERNITZ_STATION_ID, "departures"):
        if _is_cjx(item) and _cjx_is_wien_bound(item):
            o = _parse(item, TERNITZ_STATION_ID, "to_wien")
            if o:
                obs.append(o)

    # to_ternitz: CJX arrivals at Ternitz (coming from Wien direction)
    for item in _get(TERNITZ_STATION_ID, "arrivals"):
        if _is_cjx(item):
            o = _parse(item, TERNITZ_STATION_ID, "to_ternitz")
            if o:
                obs.append(o)

    # -----------------------------------------------------------------------
    # LEG 2: U6 at Wien Meidling
    # -----------------------------------------------------------------------

    # to_wien: U6 departing Meidling towards Floridsdorf (passes Westbahnhof)
    # to_ternitz: U6 departing Meidling towards Siebenhirten (away from Westbahnhof)
    for item in _get(WIEN_MEIDLING_STATION_ID, "departures", _SUBWAY_ONLY):
        if not _is_u6(item):
            continue
        dest = _direction(item)
        if _U6_TO_WIEN in dest:
            o = _parse(item, WIEN_MEIDLING_STATION_ID, "to_wien")
        elif _U6_TO_TERNITZ in dest:
            o = _parse(item, WIEN_MEIDLING_STATION_ID, "to_ternitz")
        else:
            continue
        if o:
            obs.append(o)

    # -----------------------------------------------------------------------
    # CJX at Wien Meidling (track delay buildup during the journey)
    # -----------------------------------------------------------------------

    # to_wien: CJX arriving at Wien Meidling from Ternitz direction
    for item in _get(WIEN_MEIDLING_STATION_ID, "arrivals"):
        if _is_cjx(item):
            o = _parse(item, WIEN_MEIDLING_STATION_ID, "to_wien")
            if o:
                obs.append(o)

    # to_ternitz: CJX departing Wien Meidling towards Ternitz
    for item in _get(WIEN_MEIDLING_STATION_ID, "departures"):
        if _is_cjx(item) and not _cjx_is_wien_bound(item):
            o = _parse(item, WIEN_MEIDLING_STATION_ID, "to_ternitz")
            if o:
                obs.append(o)

    # -----------------------------------------------------------------------
    # LEG 2: U6 at Wien Westbahnhof
    # -----------------------------------------------------------------------

    # to_ternitz: U6 departing Westbahnhof towards Siebenhirten (towards Meidling)
    for item in _get(WIEN_WESTBAHNHOF_STATION_ID, "departures"):
        if _is_u6(item) and _U6_TO_TERNITZ in _direction(item):
            o = _parse(item, WIEN_WESTBAHNHOF_STATION_ID, "to_ternitz")
            if o:
                obs.append(o)

    # to_wien: U6 arrivals at Westbahnhof coming from Meidling direction
    for item in _get(WIEN_WESTBAHNHOF_STATION_ID, "arrivals"):
        if _is_u6(item):
            o = _parse(item, WIEN_WESTBAHNHOF_STATION_ID, "to_wien")
            if o:
                obs.append(o)

    _upsert(obs)
    logger.info("Collection complete: %d observations", len(obs))
