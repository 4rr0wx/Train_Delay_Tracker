"""
Idempotent reference data for all static tables.

Called automatically on app startup via main.py lifespan.
Can also be run standalone: python seed.py

All inserts use ON CONFLICT DO NOTHING — safe to call on every restart.
"""

from __future__ import annotations

import logging
from datetime import time

from sqlalchemy.orm import Session

from database import SessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED_STATIONS = [
    {
        "id": "1131839",
        "name": "Ternitz",
        "short_name": "Ternitz",
        "station_type": "train",
        "latitude": 47.716500,
        "longitude": 16.033400,
    },
    {
        "id": "1130016",
        "name": "Wiener Neustadt Hbf",
        "short_name": "WNSt",
        "station_type": "train",
        "latitude": 47.812700,
        "longitude": 16.241500,
    },
    {
        "id": "1130165",
        "name": "Baden bei Wien",
        "short_name": "Baden",
        "station_type": "train",
        "latitude": 48.006700,
        "longitude": 16.231600,
    },
    {
        "id": "1191201",
        "name": "Wien Meidling",
        "short_name": "Meidling",
        "station_type": "mixed",
        "latitude": 48.173500,
        "longitude": 16.334100,
    },
    {
        "id": "915006",
        "name": "Wien Westbahnhof (U6)",
        "short_name": "WBhf U6",
        "station_type": "subway",
        "latitude": 48.196500,
        "longitude": 16.338000,
    },
]

SEED_LINES = [
    {
        "code": "CJX",
        "display_name": "CJX",
        "operator": "ÖBB",
        "product_type": "regional",
        "color_hex": "#E2001A",
    },
    {
        "code": "U6",
        "display_name": "U6",
        "operator": "Wiener Linien",
        "product_type": "subway",
        "color_hex": "#9B6D9F",
    },
]

# Routes reference lines by code; resolved to IDs at seed time
SEED_ROUTES = [
    {
        "name": "CJX Ternitz → Wien Meidling",
        "line_code": "CJX",
        "direction": "to_wien",
        "description": "CJX Regionalzug Ternitz nach Wien Meidling",
    },
    {
        "name": "CJX Wien Meidling → Ternitz",
        "line_code": "CJX",
        "direction": "to_ternitz",
        "description": "CJX Regionalzug Wien Meidling nach Ternitz",
    },
    {
        "name": "U6 Wien Meidling → Wien Westbahnhof",
        "line_code": "U6",
        "direction": "to_wien",
        "description": "U6 U-Bahn Wien Meidling nach Westbahnhof",
    },
    {
        "name": "U6 Wien Westbahnhof → Wien Meidling",
        "line_code": "U6",
        "direction": "to_ternitz",
        "description": "U6 U-Bahn Westbahnhof nach Wien Meidling",
    },
]

# Route legs: route_name → ordered list of stations
SEED_ROUTE_LEGS = [
    # CJX to_wien: Ternitz → WNSt → Baden → Meidling
    {"route_name": "CJX Ternitz → Wien Meidling", "stop_sequence": 1,
     "station_id": "1131839", "is_origin": True, "is_destination": False,
     "typical_travel_minutes_from_prev": None,
     "poll_window_before_minutes": 15, "poll_window_after_minutes": 45},
    {"route_name": "CJX Ternitz → Wien Meidling", "stop_sequence": 2,
     "station_id": "1130016", "is_origin": False, "is_destination": False,
     "typical_travel_minutes_from_prev": 15,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 30},
    {"route_name": "CJX Ternitz → Wien Meidling", "stop_sequence": 3,
     "station_id": "1130165", "is_origin": False, "is_destination": False,
     "typical_travel_minutes_from_prev": 25,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 30},
    {"route_name": "CJX Ternitz → Wien Meidling", "stop_sequence": 4,
     "station_id": "1191201", "is_origin": False, "is_destination": True,
     "typical_travel_minutes_from_prev": 30,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 30},

    # CJX to_ternitz: Meidling → Baden → WNSt → Ternitz
    {"route_name": "CJX Wien Meidling → Ternitz", "stop_sequence": 1,
     "station_id": "1191201", "is_origin": True, "is_destination": False,
     "typical_travel_minutes_from_prev": None,
     "poll_window_before_minutes": 15, "poll_window_after_minutes": 45},
    {"route_name": "CJX Wien Meidling → Ternitz", "stop_sequence": 2,
     "station_id": "1130165", "is_origin": False, "is_destination": False,
     "typical_travel_minutes_from_prev": 30,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 30},
    {"route_name": "CJX Wien Meidling → Ternitz", "stop_sequence": 3,
     "station_id": "1130016", "is_origin": False, "is_destination": False,
     "typical_travel_minutes_from_prev": 25,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 30},
    {"route_name": "CJX Wien Meidling → Ternitz", "stop_sequence": 4,
     "station_id": "1131839", "is_origin": False, "is_destination": True,
     "typical_travel_minutes_from_prev": 15,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 30},

    # U6 to_wien: Meidling → Westbahnhof
    {"route_name": "U6 Wien Meidling → Wien Westbahnhof", "stop_sequence": 1,
     "station_id": "1191201", "is_origin": True, "is_destination": False,
     "typical_travel_minutes_from_prev": None,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 20},
    {"route_name": "U6 Wien Meidling → Wien Westbahnhof", "stop_sequence": 2,
     "station_id": "915006", "is_origin": False, "is_destination": True,
     "typical_travel_minutes_from_prev": 7,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 20},

    # U6 to_ternitz: Westbahnhof → Meidling
    {"route_name": "U6 Wien Westbahnhof → Wien Meidling", "stop_sequence": 1,
     "station_id": "915006", "is_origin": True, "is_destination": False,
     "typical_travel_minutes_from_prev": None,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 20},
    {"route_name": "U6 Wien Westbahnhof → Wien Meidling", "stop_sequence": 2,
     "station_id": "1191201", "is_origin": False, "is_destination": True,
     "typical_travel_minutes_from_prev": 7,
     "poll_window_before_minutes": 10, "poll_window_after_minutes": 20},
]

SEED_COMMUTE_SLOTS = [
    {
        "name": "Morning CJX 07:11",
        "route_name": "CJX Ternitz → Wien Meidling",
        "direction": "to_wien",
        "anchor_time_local": time(7, 11),
        "anchor_station_id": "1131839",
        "time_tolerance_minutes": 2,
    },
    {
        "name": "Morning CJX 07:40",
        "route_name": "CJX Ternitz → Wien Meidling",
        "direction": "to_wien",
        "anchor_time_local": time(7, 40),
        "anchor_station_id": "1131839",
        "time_tolerance_minutes": 2,
    },
    {
        "name": "Evening U6 16:15",
        "route_name": "U6 Wien Westbahnhof → Wien Meidling",
        "direction": "to_ternitz",
        "anchor_time_local": time(16, 15),
        "anchor_station_id": "915006",
        "time_tolerance_minutes": 2,
    },
]


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------

def seed_reference_data(db: Session) -> None:
    """Insert all reference rows. Existing rows are left untouched (ON CONFLICT DO NOTHING)."""
    from sqlalchemy import text

    # 1. Stations
    for s in SEED_STATIONS:
        db.execute(
            text("""
                INSERT INTO stations (id, name, short_name, station_type, latitude, longitude)
                VALUES (:id, :name, :short_name, :station_type, :latitude, :longitude)
                ON CONFLICT (id) DO NOTHING
            """),
            s,
        )

    # 2. Lines
    for ln in SEED_LINES:
        db.execute(
            text("""
                INSERT INTO lines (code, display_name, operator, product_type, color_hex)
                VALUES (:code, :display_name, :operator, :product_type, :color_hex)
                ON CONFLICT (code) DO NOTHING
            """),
            ln,
        )

    # 3. Routes (resolve line_id by code)
    for r in SEED_ROUTES:
        db.execute(
            text("""
                INSERT INTO routes (name, line_id, direction, description)
                SELECT :name, l.id, :direction, :description
                FROM lines l WHERE l.code = :line_code
                ON CONFLICT (name) DO NOTHING
            """),
            r,
        )

    # 4. Route legs (resolve route_id by name)
    for leg in SEED_ROUTE_LEGS:
        db.execute(
            text("""
                INSERT INTO route_legs (
                    route_id, stop_sequence, station_id,
                    is_origin, is_destination,
                    typical_travel_minutes_from_prev,
                    poll_window_before_minutes, poll_window_after_minutes
                )
                SELECT r.id, :stop_sequence, :station_id,
                       :is_origin, :is_destination,
                       :typical_travel_minutes_from_prev,
                       :poll_window_before_minutes, :poll_window_after_minutes
                FROM routes r WHERE r.name = :route_name
                ON CONFLICT (route_id, stop_sequence) DO NOTHING
            """),
            leg,
        )

    # 5. Commute slots (resolve route_id by name)
    for slot in SEED_COMMUTE_SLOTS:
        db.execute(
            text("""
                INSERT INTO commute_slots (
                    name, route_id, direction, anchor_time_local,
                    anchor_station_id, time_tolerance_minutes
                )
                SELECT :name, r.id, :direction::trip_direction, :anchor_time_local,
                       :anchor_station_id, :time_tolerance_minutes
                FROM routes r WHERE r.name = :route_name
                ON CONFLICT (name) DO NOTHING
            """),
            slot,
        )

    db.commit()
    logger.info("Seed data applied (ON CONFLICT DO NOTHING).")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        seed_reference_data(db)
    print("Done.")
