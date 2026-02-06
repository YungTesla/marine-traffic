import sqlite3
import logging
from contextlib import contextmanager

from src.config import DB_PATH

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS vessels (
    mmsi TEXT PRIMARY KEY,
    name TEXT,
    ship_type INTEGER,
    length REAL,
    width REAL,
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    sog REAL,
    cog REAL,
    heading REAL,
    FOREIGN KEY (mmsi) REFERENCES vessels(mmsi)
);

CREATE INDEX IF NOT EXISTS idx_positions_mmsi_ts ON positions(mmsi, timestamp);

CREATE TABLE IF NOT EXISTS encounters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vessel_a_mmsi TEXT NOT NULL,
    vessel_b_mmsi TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    min_distance_m REAL,
    encounter_type TEXT,
    cpa_m REAL,
    tcpa_s REAL,
    FOREIGN KEY (vessel_a_mmsi) REFERENCES vessels(mmsi),
    FOREIGN KEY (vessel_b_mmsi) REFERENCES vessels(mmsi)
);

CREATE TABLE IF NOT EXISTS encounter_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id INTEGER NOT NULL,
    mmsi TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    sog REAL,
    cog REAL,
    heading REAL,
    FOREIGN KEY (encounter_id) REFERENCES encounters(id),
    FOREIGN KEY (mmsi) REFERENCES vessels(mmsi)
);

CREATE INDEX IF NOT EXISTS idx_enc_pos_encounter ON encounter_positions(encounter_id);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info("Database initialized at %s", DB_PATH)


def upsert_vessel(mmsi: str, name: str = None, ship_type: int = None,
                  length: float = None, width: float = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO vessels (mmsi, name, ship_type, length, width, updated_at)
               VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
               ON CONFLICT(mmsi) DO UPDATE SET
                   name = COALESCE(excluded.name, vessels.name),
                   ship_type = COALESCE(excluded.ship_type, vessels.ship_type),
                   length = COALESCE(excluded.length, vessels.length),
                   width = COALESCE(excluded.width, vessels.width),
                   updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            """,
            (mmsi, name, ship_type, length, width),
        )


def insert_position(mmsi: str, timestamp: str, lat: float, lon: float,
                     sog: float, cog: float, heading: float):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO positions (mmsi, timestamp, lat, lon, sog, cog, heading)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mmsi, timestamp, lat, lon, sog, cog, heading),
        )


def create_encounter(vessel_a: str, vessel_b: str, start_time: str,
                     distance_m: float, encounter_type: str,
                     cpa_m: float, tcpa_s: float) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO encounters
               (vessel_a_mmsi, vessel_b_mmsi, start_time, min_distance_m,
                encounter_type, cpa_m, tcpa_s)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vessel_a, vessel_b, start_time, distance_m, encounter_type,
             cpa_m, tcpa_s),
        )
        return cur.lastrowid


def update_encounter(encounter_id: int, end_time: str = None,
                     min_distance_m: float = None, cpa_m: float = None,
                     tcpa_s: float = None):
    updates = []
    params = []
    if end_time is not None:
        updates.append("end_time = ?")
        params.append(end_time)
    if min_distance_m is not None:
        updates.append("min_distance_m = ?")
        params.append(min_distance_m)
    if cpa_m is not None:
        updates.append("cpa_m = ?")
        params.append(cpa_m)
    if tcpa_s is not None:
        updates.append("tcpa_s = ?")
        params.append(tcpa_s)
    if not updates:
        return
    params.append(encounter_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE encounters SET {', '.join(updates)} WHERE id = ?",
            params,
        )


def insert_encounter_position(encounter_id: int, mmsi: str, timestamp: str,
                               lat: float, lon: float, sog: float,
                               cog: float, heading: float):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO encounter_positions
               (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading),
        )
