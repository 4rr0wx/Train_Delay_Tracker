import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tracker:tracker_secret@localhost:5432/train_tracker")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://oebb.macistry.com/api")

# Station IDs (confirmed via ÖBB REST API)
TERNITZ_STATION_ID = os.environ.get("TERNITZ_STATION_ID", "1131839")
WIEN_MEIDLING_STATION_ID = os.environ.get("WIEN_MEIDLING_STATION_ID", "1191201")
WIEN_WESTBAHNHOF_STATION_ID = os.environ.get("WIEN_WESTBAHNHOF_STATION_ID", "915006")
WIENER_NEUSTADT_STATION_ID = os.environ.get("WIENER_NEUSTADT_STATION_ID", "1130016")  # Wiener Neustadt Hbf (Südbahn)
BADEN_STATION_ID = os.environ.get("BADEN_STATION_ID", "1130165")  # Baden bei Wien (Südbahn)

POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
POLL_DURATION_MINUTES = 120  # Look ahead 2 hours

# Only these lines are relevant for the commute
RELEVANT_TRAIN_LINE = "CJX"   # Ternitz <-> Wien Meidling
RELEVANT_SUBWAY_LINE = "U6"   # Wien Meidling <-> Wien Westbahnhof

# User's specific commute departure times (HH:MM, local Vienna time)
# Morning: CJX ab Ternitz + matching U6 connection ab Wien Meidling
# Evening: U6 ab Wien Westbahnhof + CJX connection ab Wien Meidling
MORNING_JOURNEYS = [
    {"cjx_dep": "07:11", "u6_dep": "08:01"},   # CJX 07:11 → Meidling ~08:00 → U6 08:01
    {"cjx_dep": "07:40", "u6_dep": "08:30"},   # CJX 07:40 → Meidling ~08:24 → U6 08:30
]
EVENING_JOURNEY = {"u6_dep": "16:15", "cjx_dep": "16:35"}  # U6 16:15 → Meidling ~16:21 → CJX 16:35

# Legacy aliases (used by some existing routes)
MORNING_TRAINS = [j["cjx_dep"] for j in MORNING_JOURNEYS]
EVENING_TRAIN = EVENING_JOURNEY["u6_dep"]

# Tolerance in minutes for matching a train to a scheduled slot
COMMUTE_TIME_TOLERANCE_MINUTES = 2
