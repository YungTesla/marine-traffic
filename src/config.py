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

# WebSocket reconnection backoff
RECONNECT_BASE_DELAY_S = 1.0    # Initial reconnection delay
RECONNECT_MAX_DELAY_S = 60.0    # Maximum reconnection delay (cap)
RECONNECT_JITTER_FACTOR = 0.3   # Jitter randomization (±30%)

# Database
DB_PATH = os.environ.get("DB_PATH", "encounters.db")

# Batch insert configuration
BATCH_SIZE = 100               # flush after N records
BATCH_FLUSH_INTERVAL_S = 5.0   # flush after N seconds

# Logging interval (seconds)
STATS_INTERVAL_S = 30

# Rijkswaterstaat Waterinfo API (ddapi20)
WATERINFO_BASE_URL = "https://ddapi20-waterwebservices.rijkswaterstaat.nl"
WATER_POLL_INTERVAL_S = 600  # 10 minuten (gelijk aan API update-frequentie)

WATERINFO_STATIONS = {
    "hoekvanholland": {"lat": 51.978, "lon": 4.121, "name": "Hoek van Holland"},
    "vlissingen":     {"lat": 51.440, "lon": 3.578, "name": "Vlissingen"},
    "denhelder":      {"lat": 52.963, "lon": 4.760, "name": "Den Helder"},
    "ijmuiden":       {"lat": 52.463, "lon": 4.555, "name": "IJmuiden"},
    "scheveningen":   {"lat": 52.103, "lon": 4.264, "name": "Scheveningen"},
    "harlingen":      {"lat": 53.175, "lon": 5.414, "name": "Harlingen"},
    "delfzijl":       {"lat": 53.335, "lon": 6.929, "name": "Delfzijl"},
    "rotterdam":      {"lat": 51.896, "lon": 4.486, "name": "Rotterdam"},
    "terneuzen":      {"lat": 51.335, "lon": 3.829, "name": "Terneuzen"},
    "europlatform":   {"lat": 52.002, "lon": 3.277, "name": "Europlatform"},
}
