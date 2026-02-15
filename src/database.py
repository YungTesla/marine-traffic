import sqlite3
import logging
import asyncio
from contextlib import contextmanager
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from src.config import DB_PATH, BATCH_SIZE, BATCH_FLUSH_INTERVAL_S

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


class PositionBuffer:
    """
    Buffers position inserts and flushes in batches to reduce SQLite I/O.
    Thread-safe for asyncio use.
    """
    def __init__(self, batch_size: int = BATCH_SIZE):
        self.batch_size = batch_size
        self.position_buffer: deque = deque()
        self.encounter_position_buffer: deque = deque()
        self.first_buffered_time: Optional[float] = None
        self._lock = asyncio.Lock()

    async def add_position(self, mmsi: str, timestamp: str, lat: float, lon: float,
                           sog: float, cog: float, heading: float):
        """Add a position to the buffer. Auto-flush if batch size reached."""
        async with self._lock:
            if not self.first_buffered_time:
                self.first_buffered_time = datetime.now(timezone.utc).timestamp()

            self.position_buffer.append((mmsi, timestamp, lat, lon, sog, cog, heading))

            if len(self.position_buffer) >= self.batch_size:
                await self._flush_positions()

    async def add_encounter_position(self, encounter_id: int, mmsi: str, timestamp: str,
                                     lat: float, lon: float, sog: float,
                                     cog: float, heading: float):
        """Add an encounter position to the buffer. Auto-flush if batch size reached."""
        async with self._lock:
            if not self.first_buffered_time:
                self.first_buffered_time = datetime.now(timezone.utc).timestamp()

            self.encounter_position_buffer.append(
                (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading)
            )

            if len(self.encounter_position_buffer) >= self.batch_size:
                await self._flush_encounter_positions()

    async def _flush_positions(self):
        """Flush position buffer to database."""
        if not self.position_buffer:
            return

        batch = list(self.position_buffer)
        self.position_buffer.clear()

        try:
            with get_conn() as conn:
                conn.executemany(
                    """INSERT INTO positions (mmsi, timestamp, lat, lon, sog, cog, heading)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    batch,
                )
            logger.debug("Flushed %d positions to database", len(batch))
        except Exception as e:
            logger.error("Failed to flush positions: %s", e)
            # Re-add to buffer on failure
            self.position_buffer.extendleft(reversed(batch))
            raise

    async def _flush_encounter_positions(self):
        """Flush encounter position buffer to database."""
        if not self.encounter_position_buffer:
            return

        batch = list(self.encounter_position_buffer)
        self.encounter_position_buffer.clear()

        try:
            with get_conn() as conn:
                conn.executemany(
                    """INSERT INTO encounter_positions
                       (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    batch,
                )
            logger.debug("Flushed %d encounter positions to database", len(batch))
        except Exception as e:
            logger.error("Failed to flush encounter positions: %s", e)
            # Re-add to buffer on failure
            self.encounter_position_buffer.extendleft(reversed(batch))
            raise

    async def flush_all(self):
        """Flush all buffered data to database."""
        async with self._lock:
            await self._flush_positions()
            await self._flush_encounter_positions()
            self.first_buffered_time = None

    async def should_flush(self) -> bool:
        """Check if buffer should be flushed based on time."""
        if not self.first_buffered_time:
            return False

        now = datetime.now(timezone.utc).timestamp()
        elapsed = now - self.first_buffered_time

        return (elapsed >= BATCH_FLUSH_INTERVAL_S and
                (self.position_buffer or self.encounter_position_buffer))

    async def auto_flush_if_needed(self):
        """Flush if time threshold exceeded."""
        if await self.should_flush():
            await self.flush_all()


# Global buffer instance
_buffer: Optional[PositionBuffer] = None


def get_buffer() -> PositionBuffer:
    """Get or create the global position buffer."""
    global _buffer
    if _buffer is None:
        _buffer = PositionBuffer()
    return _buffer


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


async def insert_position(mmsi: str, timestamp: str, lat: float, lon: float,
                          sog: float, cog: float, heading: float):
    """Buffer a position insert. Flushes automatically based on batch size or time."""
    buffer = get_buffer()
    await buffer.add_position(mmsi, timestamp, lat, lon, sog, cog, heading)


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


async def insert_encounter_position(encounter_id: int, mmsi: str, timestamp: str,
                                    lat: float, lon: float, sog: float,
                                    cog: float, heading: float):
    """Buffer an encounter position insert. Flushes automatically based on batch size or time."""
    buffer = get_buffer()
    await buffer.add_encounter_position(encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading)
