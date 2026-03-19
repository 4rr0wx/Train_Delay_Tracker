import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tracker:tracker_secret@localhost:5432/train_tracker")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://oebb.macistry.com/api")
TERNITZ_STATION_ID = os.environ.get("TERNITZ_STATION_ID", "1131839")
WIEN_STATION_ID = os.environ.get("WIEN_STATION_ID", "1291501")
POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
POLL_DURATION_MINUTES = 120  # Look ahead 2 hours
