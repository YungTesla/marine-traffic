"""Feature engineering utilities for ML models.

Reuses haversine() and compute_cpa_tcpa() from encounter_detector.py.
"""

import math

import numpy as np
import pandas as pd

from src.encounter_detector import haversine, compute_cpa_tcpa

M_PER_DEG_LAT = 111_320.0


def cog_to_sincos(cog: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert course over ground (degrees) to sin/cos components."""
    rad = np.deg2rad(cog)
    return np.sin(rad), np.cos(rad)


def normalize_positions(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert lat/lon to meters relative to centroid (flat-earth approx)."""
    centroid_lat = lats.mean()
    centroid_lon = lons.mean()
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(centroid_lat))

    delta_x = (lons - centroid_lon) * m_per_deg_lon
    delta_y = (lats - centroid_lat) * M_PER_DEG_LAT
    return delta_x, delta_y


def compute_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived features: delta_t, acceleration, rate_of_turn.

    Expects columns: timestamp (datetime64), sog, cog.
    Returns a copy with new columns added.
    """
    df = df.copy()

    # Time delta in seconds between consecutive observations
    dt = df["timestamp"].diff().dt.total_seconds()
    df["delta_t"] = dt.fillna(0.0)

    # Acceleration (change in speed per second)
    dsog = df["sog"].diff().fillna(0.0)
    df["acceleration"] = np.where(df["delta_t"] > 0, dsog / df["delta_t"], 0.0)

    # Rate of turn (change in course per second, handling 360° wraparound)
    dcog = df["cog"].diff().fillna(0.0)
    # Normalize to [-180, 180]
    dcog = ((dcog + 180) % 360) - 180
    df["rate_of_turn"] = np.where(df["delta_t"] > 0, dcog / df["delta_t"], 0.0)

    return df


def build_trajectory_features(df: pd.DataFrame) -> np.ndarray:
    """Convert a trajectory DataFrame into a feature array for the LSTM.

    Expects columns: lat, lon, sog, cog, heading, delta_t, acceleration, rate_of_turn.
    Returns ndarray of shape (seq_len, 10):
        [delta_x, delta_y, sog, cog_sin, cog_cos, heading_sin, heading_cos,
         acceleration, rate_of_turn, delta_t]
    """
    delta_x, delta_y = normalize_positions(df["lat"].values, df["lon"].values)
    cog_sin, cog_cos = cog_to_sincos(df["cog"].values)

    heading = df["heading"].values.copy()
    heading = np.where(heading < 0, df["cog"].values, heading)  # fallback heading=-1
    heading_sin, heading_cos = cog_to_sincos(heading)

    features = np.column_stack([
        delta_x,
        delta_y,
        df["sog"].values,
        cog_sin,
        cog_cos,
        heading_sin,
        heading_cos,
        df["acceleration"].values,
        df["rate_of_turn"].values,
        df["delta_t"].values,
    ])
    return features.astype(np.float32)


def build_encounter_features(encounter: dict, positions_a: pd.DataFrame,
                              positions_b: pd.DataFrame,
                              vessel_a: dict, vessel_b: dict) -> dict:
    """Build feature dict for risk classification from encounter data.

    Args:
        encounter: dict with keys from encounters table
        positions_a/b: DataFrames of encounter_positions per vessel
        vessel_a/b: dict with vessel metadata
    """
    duration = 0.0
    if encounter.get("end_time") and encounter.get("start_time"):
        duration = (pd.Timestamp(encounter["end_time"])
                    - pd.Timestamp(encounter["start_time"])).total_seconds()

    def _agg_positions(pos_df):
        if pos_df.empty:
            return {"max_sog": 0, "total_course_change": 0,
                    "max_turn_rate": 0, "total_speed_change": 0}
        pos_df = pos_df.sort_values("timestamp")
        dcog = pos_df["cog"].diff().dropna()
        dcog = ((dcog + 180) % 360) - 180
        dsog = pos_df["sog"].diff().dropna()
        dt = pd.to_datetime(pos_df["timestamp"]).diff().dt.total_seconds().dropna()
        turn_rates = np.where(dt > 0, np.abs(dcog.values) / dt.values, 0)
        return {
            "max_sog": pos_df["sog"].max(),
            "total_course_change": np.abs(dcog).sum(),
            "max_turn_rate": turn_rates.max() if len(turn_rates) > 0 else 0,
            "total_speed_change": np.abs(dsog).sum(),
        }

    agg_a = _agg_positions(positions_a)
    agg_b = _agg_positions(positions_b)

    # Closure rate: distance change per second at start of encounter
    closure_rate = 0.0
    if len(positions_a) >= 2 and len(positions_b) >= 2:
        pa0, pa1 = positions_a.iloc[0], positions_a.iloc[1]
        pb0, pb1 = positions_b.iloc[0], positions_b.iloc[1]
        d0 = haversine(pa0["lat"], pa0["lon"], pb0["lat"], pb0["lon"])
        d1 = haversine(pa1["lat"], pa1["lon"], pb1["lat"], pb1["lon"])
        t0 = pd.Timestamp(pa0["timestamp"])
        t1 = pd.Timestamp(pa1["timestamp"])
        dt_s = (t1 - t0).total_seconds()
        if dt_s > 0:
            closure_rate = (d0 - d1) / dt_s

    # Encounter type one-hot
    enc_type = encounter.get("encounter_type", "crossing")
    type_head_on = 1.0 if enc_type == "head-on" else 0.0
    type_crossing = 1.0 if enc_type == "crossing" else 0.0
    type_overtaking = 1.0 if enc_type == "overtaking" else 0.0

    return {
        "min_distance_m": encounter.get("min_distance_m", 0),
        "cpa_m": encounter.get("cpa_m", 0),
        "tcpa_s": encounter.get("tcpa_s", 0),
        "type_head_on": type_head_on,
        "type_crossing": type_crossing,
        "type_overtaking": type_overtaking,
        "max_sog_a": agg_a["max_sog"],
        "max_sog_b": agg_b["max_sog"],
        "total_course_change_a": agg_a["total_course_change"],
        "total_course_change_b": agg_b["total_course_change"],
        "max_turn_rate_a": agg_a["max_turn_rate"],
        "max_turn_rate_b": agg_b["max_turn_rate"],
        "total_speed_change_a": agg_a["total_speed_change"],
        "total_speed_change_b": agg_b["total_speed_change"],
        "encounter_duration_s": duration,
        "closure_rate": closure_rate,
        "ship_type_a": vessel_a.get("ship_type", 0) or 0,
        "ship_type_b": vessel_b.get("ship_type", 0) or 0,
        "length_a": vessel_a.get("length", 0) or 0,
        "length_b": vessel_b.get("length", 0) or 0,
    }


def build_bc_state(own_pos: dict, other_pos: dict,
                   encounter_type: str, vessel_info: dict) -> np.ndarray:
    """Build state vector for behavioral cloning.

    Returns ndarray of shape (19,):
        Own: sog, cog_sin, cog_cos, heading_sin, heading_cos, ship_type, length
        Other relative: rel_x, rel_y, rel_sog, rel_cog_sin, rel_cog_cos
        Situation: distance_m, bearing, cpa_m, tcpa_s, type_head_on, type_crossing, type_overtaking
    """
    # Own ship features
    cog_s, cog_c = math.sin(math.radians(own_pos["cog"])), math.cos(math.radians(own_pos["cog"]))
    h = own_pos["heading"] if own_pos["heading"] >= 0 else own_pos["cog"]
    h_s, h_c = math.sin(math.radians(h)), math.cos(math.radians(h))

    # Relative position
    mid_lat = math.radians((own_pos["lat"] + other_pos["lat"]) / 2)
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(mid_lat)
    rel_x = (other_pos["lon"] - own_pos["lon"]) * m_per_deg_lon
    rel_y = (other_pos["lat"] - own_pos["lat"]) * M_PER_DEG_LAT

    # Relative speed
    rel_sog = other_pos["sog"] - own_pos["sog"]
    other_cog_s, other_cog_c = (math.sin(math.radians(other_pos["cog"])),
                                 math.cos(math.radians(other_pos["cog"])))
    # Relative course (difference encoded as sin/cos)
    dcog = math.radians(other_pos["cog"] - own_pos["cog"])
    rel_cog_sin, rel_cog_cos = math.sin(dcog), math.cos(dcog)

    # Situation
    dist = haversine(own_pos["lat"], own_pos["lon"], other_pos["lat"], other_pos["lon"])
    bearing = math.degrees(math.atan2(rel_x, rel_y)) % 360

    cpa, tcpa = compute_cpa_tcpa(
        own_pos["lat"], own_pos["lon"], own_pos["sog"], own_pos["cog"],
        other_pos["lat"], other_pos["lon"], other_pos["sog"], other_pos["cog"],
    )

    type_head_on = 1.0 if encounter_type == "head-on" else 0.0
    type_crossing = 1.0 if encounter_type == "crossing" else 0.0
    type_overtaking = 1.0 if encounter_type == "overtaking" else 0.0

    return np.array([
        own_pos["sog"], cog_s, cog_c, h_s, h_c,
        float(vessel_info.get("ship_type", 0) or 0),
        float(vessel_info.get("length", 0) or 0),
        rel_x, rel_y, rel_sog, rel_cog_sin, rel_cog_cos,
        dist, bearing, cpa, tcpa,
        type_head_on, type_crossing, type_overtaking,
    ], dtype=np.float32)
