import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tracker:tracker_secret@localhost:5432/train_tracker")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://oebb.macistry.com/api")

# Station IDs (confirmed via ÖBB REST API)
TERNITZ_STATION_ID = os.environ.get("TERNITZ_STATION_ID", "1131839")
WIEN_MEIDLING_STATION_ID = os.environ.get("WIEN_MEIDLING_STATION_ID", "1191201")
WIEN_WESTBAHNHOF_STATION_ID = os.environ.get("WIEN_WESTBAHNHOF_STATION_ID", "915006")
BADEN_STATION_ID = os.environ.get("BADEN_STATION_ID", "1130165")  # Baden bei Wien (Südbahn)

POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
POLL_DURATION_MINUTES = 120  # Look ahead 2 hours

# Only these lines are relevant for the commute
RELEVANT_TRAIN_LINE = "CJX"   # Ternitz <-> Wien Meidling
RELEVANT_SUBWAY_LINE = "U6"   # Wien Meidling <-> Wien Westbahnhof

# User's specific commute departure times (HH:MM, local Vienna time)
# Morning: CJX from Ternitz, Evening: U6 from Wien Westbahnhof
MORNING_TRAINS = ["07:11", "07:40"]   # CJX ab Ternitz
EVENING_TRAIN = "16:15"               # U6 ab Wien Westbahnhof

# Tolerance in minutes for matching a train to a scheduled slot
COMMUTE_TIME_TOLERANCE_MINUTES = 2
