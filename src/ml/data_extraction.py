"""Data extraction from SQLite database for ML training.

Provides three main extraction functions:
- extract_trajectories() for trajectory prediction
- extract_encounters() for risk classification
- extract_encounter_pairs() for behavioral cloning / RL
"""

import sqlite3
import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.config import DB_PATH
from src.ml.features import (
    compute_derived_features,
    build_trajectory_features,
    build_encounter_features,
    build_bc_state,
)
from src.encounter_detector import haversine

logger = logging.getLogger(__name__)


def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 1. Trajectory extraction (for trajectory prediction LSTM)
# ---------------------------------------------------------------------------

def extract_trajectories(
    db_path: Optional[str] = None,
    min_segment_len: int = 20,
    max_gap_seconds: float = 300.0,
) -> list[pd.DataFrame]:
    """Extract continuous trajectory segments from the positions table.

    Groups positions by MMSI, splits at gaps > max_gap_seconds,
    and filters out segments shorter than min_segment_len.

    Returns list of DataFrames, each a continuous trajectory segment.
    """
    conn = _get_conn(db_path)
    df = pd.read_sql_query(
        "SELECT mmsi, timestamp, lat, lon, sog, cog, heading "
        "FROM positions ORDER BY mmsi, timestamp",
        conn,
    )
    conn.close()

    if df.empty:
        logger.warning("No positions found in database.")
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    segments = []
    for mmsi, group in df.groupby("mmsi"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        # Split at time gaps
        dt = group["timestamp"].diff().dt.total_seconds()
        split_points = dt[dt > max_gap_seconds].index.tolist()

        boundaries = [0] + split_points + [len(group)]
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            seg = group.iloc[start:end].reset_index(drop=True)
            if len(seg) >= min_segment_len:
                segments.append(seg)

    logger.info("Extracted %d trajectory segments from %d positions.",
                len(segments), len(df))
    return segments


def trajectories_to_features(segments: list[pd.DataFrame]) -> list[np.ndarray]:
    """Convert trajectory segments to feature arrays for the LSTM.

    Returns list of ndarray, each shape (seq_len, 10).
    """
    feature_arrays = []
    for seg in segments:
        seg = compute_derived_features(seg)
        features = build_trajectory_features(seg)
        feature_arrays.append(features)
    return feature_arrays


# ---------------------------------------------------------------------------
# 2. Encounter extraction (for risk classification)
# ---------------------------------------------------------------------------

def extract_encounters(db_path: Optional[str] = None) -> pd.DataFrame:
    """Extract encounter-level features for risk classification.

    Returns DataFrame with one row per encounter, including aggregated
    features and a risk_label column (LOW/MEDIUM/HIGH).
    """
    conn = _get_conn(db_path)

    encounters = pd.read_sql_query(
        "SELECT * FROM encounters WHERE end_time IS NOT NULL", conn
    )

    if encounters.empty:
        conn.close()
        logger.warning("No completed encounters found.")
        return pd.DataFrame()

    feature_rows = []
    for _, enc in encounters.iterrows():
        enc_dict = dict(enc)

        # Get positions for each vessel in this encounter
        pos_df = pd.read_sql_query(
            "SELECT * FROM encounter_positions WHERE encounter_id = ? ORDER BY timestamp",
            conn, params=(enc["id"],),
        )
        pos_a = pos_df[pos_df["mmsi"] == enc["vessel_a_mmsi"]]
        pos_b = pos_df[pos_df["mmsi"] == enc["vessel_b_mmsi"]]

        # Get vessel metadata
        vessel_a = dict(conn.execute(
            "SELECT * FROM vessels WHERE mmsi = ?", (enc["vessel_a_mmsi"],)
        ).fetchone() or {})
        vessel_b = dict(conn.execute(
            "SELECT * FROM vessels WHERE mmsi = ?", (enc["vessel_b_mmsi"],)
        ).fetchone() or {})

        features = build_encounter_features(enc_dict, pos_a, pos_b, vessel_a, vessel_b)
        features["encounter_id"] = enc["id"]
        feature_rows.append(features)

    conn.close()

    result = pd.DataFrame(feature_rows)

    # Add risk labels based on min_distance_m
    result["risk_label"] = pd.cut(
        result["min_distance_m"],
        bins=[-np.inf, 500, 1000, np.inf],
        labels=["HIGH", "MEDIUM", "LOW"],
    )

    logger.info("Extracted features for %d encounters.", len(result))
    return result


# ---------------------------------------------------------------------------
# 3. Encounter pairs (for behavioral cloning / RL)
# ---------------------------------------------------------------------------

def extract_encounter_pairs(db_path: Optional[str] = None) -> list[dict]:
    """Extract state-action pairs from encounter trajectories.

    For each encounter, extracts time-aligned observations for both vessels
    and computes the action (turn_rate, accel_rate) at each timestep.

    Returns list of dicts, each with:
        - encounter_id
        - encounter_type
        - states_a: ndarray (T, 19) - state vectors for vessel A
        - actions_a: ndarray (T-1, 2) - [turn_rate, accel_rate] for vessel A
        - states_b: ndarray (T, 19)
        - actions_b: ndarray (T-1, 2)
    """
    conn = _get_conn(db_path)

    encounters = pd.read_sql_query(
        "SELECT * FROM encounters WHERE end_time IS NOT NULL", conn
    )

    if encounters.empty:
        conn.close()
        logger.warning("No completed encounters found.")
        return []

    pairs = []
    for _, enc in encounters.iterrows():
        pos_df = pd.read_sql_query(
            "SELECT * FROM encounter_positions WHERE encounter_id = ? ORDER BY timestamp",
            conn, params=(enc["id"],),
        )
        pos_a = pos_df[pos_df["mmsi"] == enc["vessel_a_mmsi"]].sort_values("timestamp").reset_index(drop=True)
        pos_b = pos_df[pos_df["mmsi"] == enc["vessel_b_mmsi"]].sort_values("timestamp").reset_index(drop=True)

        if len(pos_a) < 3 or len(pos_b) < 3:
            continue

        # Vessel metadata
        vessel_a = dict(conn.execute(
            "SELECT * FROM vessels WHERE mmsi = ?", (enc["vessel_a_mmsi"],)
        ).fetchone() or {})
        vessel_b = dict(conn.execute(
            "SELECT * FROM vessels WHERE mmsi = ?", (enc["vessel_b_mmsi"],)
        ).fetchone() or {})

        enc_type = enc["encounter_type"]

        # Build states for vessel A (using B as the other vessel)
        states_a = []
        for i in range(len(pos_a)):
            # Find closest-in-time position of vessel B
            t_a = pd.Timestamp(pos_a.iloc[i]["timestamp"])
            b_times = pd.to_datetime(pos_b["timestamp"])
            closest_b_idx = (b_times - t_a).abs().argmin()

            own = dict(pos_a.iloc[i])
            other = dict(pos_b.iloc[closest_b_idx])
            state = build_bc_state(own, other, enc_type, vessel_a)
            states_a.append(state)

        # Build states for vessel B (using A as the other vessel)
        states_b = []
        for i in range(len(pos_b)):
            t_b = pd.Timestamp(pos_b.iloc[i]["timestamp"])
            a_times = pd.to_datetime(pos_a["timestamp"])
            closest_a_idx = (a_times - t_b).abs().argmin()

            own = dict(pos_b.iloc[i])
            other = dict(pos_a.iloc[closest_a_idx])
            state = build_bc_state(own, other, enc_type, vessel_b)
            states_b.append(state)

        # Extract actions (turn_rate, accel_rate) from consecutive positions
        def _extract_actions(pos: pd.DataFrame) -> np.ndarray:
            actions = []
            timestamps = pd.to_datetime(pos["timestamp"])
            for i in range(1, len(pos)):
                dt = (timestamps.iloc[i] - timestamps.iloc[i - 1]).total_seconds()
                if dt <= 0:
                    actions.append([0.0, 0.0])
                    continue
                dcog = pos.iloc[i]["cog"] - pos.iloc[i - 1]["cog"]
                dcog = ((dcog + 180) % 360) - 180  # normalize
                dsog = pos.iloc[i]["sog"] - pos.iloc[i - 1]["sog"]
                actions.append([dcog / dt, dsog / dt])
            return np.array(actions, dtype=np.float32)

        pairs.append({
            "encounter_id": enc["id"],
            "encounter_type": enc_type,
            "states_a": np.array(states_a, dtype=np.float32),
            "actions_a": _extract_actions(pos_a),
            "states_b": np.array(states_b, dtype=np.float32),
            "actions_b": _extract_actions(pos_b),
        })

    conn.close()
    logger.info("Extracted %d encounter pairs.", len(pairs))
    return pairs
