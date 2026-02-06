import math
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.ais_client import VesselPosition
from src.config import (
    ENCOUNTER_DISTANCE_NM,
    ENCOUNTER_END_DISTANCE_NM,
    MIN_SPEED_KN,
    VESSEL_TIMEOUT_S,
)
from src import database as db

logger = logging.getLogger(__name__)

NM_TO_METERS = 1852.0
KNOTS_TO_MS = 0.514444
EARTH_RADIUS_M = 6_371_000.0


@dataclass
class ActiveEncounter:
    encounter_id: int
    vessel_a: str
    vessel_b: str
    min_distance_m: float
    last_update: float  # unix timestamp


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two lat/lon points."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(a))


def compute_cpa_tcpa(
    lat_a: float, lon_a: float, sog_a: float, cog_a: float,
    lat_b: float, lon_b: float, sog_b: float, cog_b: float,
) -> tuple[float, float]:
    """
    Compute CPA (meters) and TCPA (seconds) between two vessels.
    Uses flat-earth approximation for the local area (fine for < 50 NM).
    Returns (cpa_m, tcpa_s). TCPA < 0 means vessels are diverging.
    """
    mid_lat = math.radians((lat_a + lat_b) / 2)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(mid_lat)

    # Relative position (B relative to A) in meters
    dx = (lon_b - lon_a) * m_per_deg_lon
    dy = (lat_b - lat_a) * m_per_deg_lat

    # Velocity components (m/s)
    va_x = sog_a * KNOTS_TO_MS * math.sin(math.radians(cog_a))
    va_y = sog_a * KNOTS_TO_MS * math.cos(math.radians(cog_a))
    vb_x = sog_b * KNOTS_TO_MS * math.sin(math.radians(cog_b))
    vb_y = sog_b * KNOTS_TO_MS * math.cos(math.radians(cog_b))

    # Relative velocity (B relative to A)
    dvx = vb_x - va_x
    dvy = vb_y - va_y

    dv_sq = dvx * dvx + dvy * dvy
    if dv_sq < 1e-6:
        # Vessels moving at same speed/direction or both stationary
        return math.sqrt(dx * dx + dy * dy), 0.0

    # TCPA = -(rel_pos · rel_vel) / |rel_vel|^2
    tcpa = -(dx * dvx + dy * dvy) / dv_sq

    # CPA position
    cpa_x = dx + dvx * tcpa
    cpa_y = dy + dvy * tcpa
    cpa = math.sqrt(cpa_x * cpa_x + cpa_y * cpa_y)

    return cpa, tcpa


def classify_encounter(cog_a: float, cog_b: float) -> str:
    """
    Classify encounter based on COLREGS rules.
    Returns: 'head-on', 'crossing', or 'overtaking'.
    """
    # Relative bearing difference
    diff = abs(cog_a - cog_b) % 360
    if diff > 180:
        diff = 360 - diff

    if 170 <= diff <= 190 or diff >= 170:
        return "head-on"
    elif diff <= 67.5:
        return "overtaking"
    else:
        return "crossing"


def _encounter_key(mmsi_a: str, mmsi_b: str) -> tuple[str, str]:
    """Consistent key for a pair of vessels."""
    return (min(mmsi_a, mmsi_b), max(mmsi_a, mmsi_b))


class EncounterDetector:
    def __init__(self):
        # Latest known position per MMSI
        self.positions: dict[str, VesselPosition] = {}
        self.position_times: dict[str, float] = {}  # unix timestamp of last update
        # Active encounters keyed by (mmsi_a, mmsi_b) sorted pair
        self.active_encounters: dict[tuple[str, str], ActiveEncounter] = {}
        # Stats
        self.total_encounters = 0

    def update(self, pos: VesselPosition):
        """Process a new position update. Detect/update/end encounters."""
        now = datetime.now(timezone.utc).timestamp()

        # Skip stationary vessels
        if pos.sog < MIN_SPEED_KN:
            self.positions[pos.mmsi] = pos
            self.position_times[pos.mmsi] = now
            return

        # Store position in DB
        db.insert_position(
            pos.mmsi, pos.timestamp, pos.lat, pos.lon,
            pos.sog, pos.cog, pos.heading,
        )

        # Ensure vessel exists
        if pos.name:
            db.upsert_vessel(pos.mmsi, name=pos.name)

        # Update tracking
        self.positions[pos.mmsi] = pos
        self.position_times[pos.mmsi] = now

        # Check against all other active vessels
        self._check_encounters(pos, now)

        # Cleanup stale vessels
        self._cleanup_stale(now)

    def _check_encounters(self, pos: VesselPosition, now: float):
        threshold_m = ENCOUNTER_DISTANCE_NM * NM_TO_METERS
        end_threshold_m = ENCOUNTER_END_DISTANCE_NM * NM_TO_METERS

        for other_mmsi, other_pos in list(self.positions.items()):
            if other_mmsi == pos.mmsi:
                continue
            if other_pos.sog < MIN_SPEED_KN:
                continue

            # Check if position is stale
            other_time = self.position_times.get(other_mmsi, 0)
            if now - other_time > VESSEL_TIMEOUT_S:
                continue

            dist_m = haversine(pos.lat, pos.lon, other_pos.lat, other_pos.lon)
            key = _encounter_key(pos.mmsi, other_mmsi)

            if key in self.active_encounters:
                enc = self.active_encounters[key]
                if dist_m > end_threshold_m:
                    # End encounter
                    db.update_encounter(enc.encounter_id, end_time=pos.timestamp)
                    logger.info(
                        "Encounter ENDED: %s <-> %s (min dist: %.0f m)",
                        enc.vessel_a, enc.vessel_b, enc.min_distance_m,
                    )
                    del self.active_encounters[key]
                else:
                    # Update encounter
                    if dist_m < enc.min_distance_m:
                        enc.min_distance_m = dist_m
                        cpa, tcpa = compute_cpa_tcpa(
                            pos.lat, pos.lon, pos.sog, pos.cog,
                            other_pos.lat, other_pos.lon, other_pos.sog, other_pos.cog,
                        )
                        db.update_encounter(
                            enc.encounter_id,
                            min_distance_m=dist_m,
                            cpa_m=cpa,
                            tcpa_s=tcpa,
                        )
                    enc.last_update = now
                    # Store positions during encounter
                    db.insert_encounter_position(
                        enc.encounter_id, pos.mmsi, pos.timestamp,
                        pos.lat, pos.lon, pos.sog, pos.cog, pos.heading,
                    )

            elif dist_m < threshold_m:
                # New encounter
                cpa, tcpa = compute_cpa_tcpa(
                    pos.lat, pos.lon, pos.sog, pos.cog,
                    other_pos.lat, other_pos.lon, other_pos.sog, other_pos.cog,
                )
                enc_type = classify_encounter(pos.cog, other_pos.cog)

                encounter_id = db.create_encounter(
                    vessel_a=key[0],
                    vessel_b=key[1],
                    start_time=pos.timestamp,
                    distance_m=dist_m,
                    encounter_type=enc_type,
                    cpa_m=cpa,
                    tcpa_s=tcpa,
                )

                self.active_encounters[key] = ActiveEncounter(
                    encounter_id=encounter_id,
                    vessel_a=key[0],
                    vessel_b=key[1],
                    min_distance_m=dist_m,
                    last_update=now,
                )
                self.total_encounters += 1

                logger.info(
                    "Encounter STARTED: %s <-> %s (dist: %.0f m, type: %s, CPA: %.0f m)",
                    key[0], key[1], dist_m, enc_type, cpa,
                )

                # Store initial positions for both vessels
                db.insert_encounter_position(
                    encounter_id, pos.mmsi, pos.timestamp,
                    pos.lat, pos.lon, pos.sog, pos.cog, pos.heading,
                )
                db.insert_encounter_position(
                    encounter_id, other_mmsi, other_pos.timestamp,
                    other_pos.lat, other_pos.lon, other_pos.sog,
                    other_pos.cog, other_pos.heading,
                )

    def _cleanup_stale(self, now: float):
        stale = [
            mmsi for mmsi, t in self.position_times.items()
            if now - t > VESSEL_TIMEOUT_S
        ]
        for mmsi in stale:
            # End any active encounters involving this vessel
            for key in list(self.active_encounters.keys()):
                if mmsi in key:
                    enc = self.active_encounters[key]
                    db.update_encounter(
                        enc.encounter_id,
                        end_time=datetime.now(timezone.utc).isoformat(),
                    )
                    del self.active_encounters[key]
            del self.positions[mmsi]
            del self.position_times[mmsi]

    @property
    def stats(self) -> dict:
        return {
            "active_vessels": len(self.positions),
            "active_encounters": len(self.active_encounters),
            "total_encounters": self.total_encounters,
        }
