import os

# AISStream.io API
AISSTREAM_API_KEY = os.environ.get("AISSTREAM_API_KEY", "")
AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"

# Bounding box: NL/BE/DE/PL/FR kustwateren
# Format: [[lat_min, lon_min], [lat_max, lon_max]]
BOUNDING_BOXES = [[[43.0, -5.0], [55.5, 19.0]]]

# AIS message types to subscribe to
MESSAGE_TYPES = ["PositionReport", "ShipStaticData"]

# Encounter detection thresholds
ENCOUNTER_DISTANCE_NM = 3.0      # start encounter when < 3 NM apart
ENCOUNTER_END_DISTANCE_NM = 5.0  # end encounter when > 5 NM apart
MIN_SPEED_KN = 0.5               # ignore stationary vessels (< 0.5 knots)

# Stale vessel timeout (seconds) - remove from tracking if no update
VESSEL_TIMEOUT_S = 300  # 5 minutes

# Database
DB_PATH = os.environ.get("DB_PATH", "encounters.db")

# Logging interval (seconds)
STATS_INTERVAL_S = 30
