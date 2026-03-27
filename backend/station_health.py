"""Daily station ID health check — auto-discovers replacement IDs on 404."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

import config
import collector as _collector

logger = logging.getLogger(__name__)
TIMEOUT = httpx.Timeout(15.0)

# config attribute name → (human name for /locations search, required product type)
_STATIONS: dict[str, tuple[str, str]] = {
    "TERNITZ_STATION_ID":          ("Ternitz",          "regional"),
    "WIENER_NEUSTADT_STATION_ID":  ("Wiener Neustadt",  "regional"),
    "BADEN_STATION_ID":            ("Baden bei Wien",   "regional"),
    "WIEN_MEIDLING_STATION_ID":    ("Wien Meidling",    "regional"),
    "WIEN_WESTBAHNHOF_STATION_ID": ("Wien Westbahnhof", "subway"),
}


def _is_valid(station_id: str) -> bool:
    """Return False only on a definitive 404; treat all other errors as valid."""
    url = f"{config.API_BASE_URL}/stops/{station_id}/departures"
    try:
        r = httpx.get(
            url,
            params={"duration": 5, "bus": "false", "tram": "false", "ferry": "false"},
            timeout=TIMEOUT,
        )
        return r.status_code != 404
    except Exception:
        return True  # network/timeout error ≠ invalid ID


def _find_id(name: str, required_product: str) -> str | None:
    """Search /locations for a station by name; return first ID with the required product type."""
    try:
        r = httpx.get(
            f"{config.API_BASE_URL}/locations",
            params={"query": name},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for item in r.json():
            if item.get("type") == "stop" and (item.get("products") or {}).get(required_product):
                return item["id"]
    except Exception as exc:
        logger.error("Location search failed for %r: %s", name, exc)
    return None


def _ensure_station_in_db(db: Session, station_id: str, name: str) -> None:
    from sqlalchemy import text
    db.execute(
        text(
            "INSERT INTO stations (id, name, station_type) "
            "VALUES (:id, :name, 'train') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": station_id, "name": name},
    )
    db.commit()


def check_and_update_station_ids(db: Session | None = None) -> None:
    """Probe all configured station IDs and auto-update any that return 404.

    Updates config module globals in-place and rebuilds the collector's
    _STOP_SEQUENCE so the next collection run uses the corrected IDs.
    Optionally inserts new station records into the DB if a session is provided.
    """
    updated = False
    for attr, (search_name, product) in _STATIONS.items():
        current_id = getattr(config, attr)
        if _is_valid(current_id):
            continue
        logger.warning(
            "Station %r (id=%s) returned 404 — searching for replacement",
            search_name, current_id,
        )
        new_id = _find_id(search_name, product)
        if not new_id or new_id == current_id:
            logger.error("No replacement found for station %r (id=%s)", search_name, current_id)
            continue
        logger.warning("Updating config.%s: %s → %s", attr, current_id, new_id)
        setattr(config, attr, new_id)
        if db:
            _ensure_station_in_db(db, new_id, search_name)
        updated = True

    if updated:
        _collector._STOP_SEQUENCE = _collector._build_stop_sequence()
        logger.info("Rebuilt _STOP_SEQUENCE with updated station IDs")
    else:
        logger.debug("All station IDs are valid")
