from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Station registry – single source of truth for all tracked stations.
#
# When adding a new station in the future:
#   1. Add its ID constant to config.py
#   2. Add it to KNOWN_STATIONS below
#   3. Add collection logic to collector.py
#   4. Extend journeys.py queries as needed
#
# No manual SQL required – ensure_stations() inserts missing rows on every
# app startup (ON CONFLICT DO NOTHING makes it fully idempotent).
# ---------------------------------------------------------------------------

KNOWN_STATIONS: dict[str, str] = {
    "1131839": "Ternitz",
    "1130165": "Baden bei Wien",
    "1130016": "Wiener Neustadt Hbf",
    "1191201": "Wien Meidling",
    "915006":  "Wien Westbahnhof (U6)",
}


def ensure_stations() -> None:
    """Insert any missing stations into the DB on startup.

    Safe to call on every restart – existing rows are left untouched.
    To add a future station: add it to KNOWN_STATIONS above and redeploy.
    """
    db = SessionLocal()
    try:
        for station_id, name in KNOWN_STATIONS.items():
            db.execute(
                text("INSERT INTO stations (id, name) VALUES (:id, :name) ON CONFLICT (id) DO NOTHING"),
                {"id": station_id, "name": name},
            )
        db.commit()
    finally:
        db.close()
