"""Data export module for ML training datasets.

Exports encounter data from SQLite to ML-ready formats (CSV/Parquet).
Supports filtering by encounter type, date range, and data quality.
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.config import DB_PATH
from src.ml.data_extraction import (
    extract_trajectories,
    extract_encounters,
    extract_encounter_pairs,
    trajectories_to_features,
)

logger = logging.getLogger(__name__)

FormatType = Literal["csv", "parquet"]


@dataclass
class ExportConfig:
    """Configuration for data export."""

    encounter_types: Optional[list[str]] = None  # ["head-on", "crossing", "overtaking"]
    start_date: Optional[str] = None  # ISO format: "2026-01-01"
    end_date: Optional[str] = None    # ISO format: "2026-12-31"
    min_positions: int = 10           # Minimum positions per encounter
    min_duration_s: float = 60.0      # Minimum encounter duration (seconds)
    quality_threshold: float = 0.7    # 0.0-1.0, minimum completeness score


@dataclass
class QualityMetrics:
    """Data quality metrics for an encounter."""

    completeness: float      # 0.0-1.0, fraction of expected fields present
    position_count_a: int    # Number of positions for vessel A
    position_count_b: int    # Number of positions for vessel B
    duration_s: float        # Encounter duration in seconds
    has_cpa: bool           # Has valid CPA/TCPA data
    has_vessel_meta: bool   # Has vessel metadata (name, type, dimensions)


def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get database connection."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def compute_encounter_quality(
    encounter: dict,
    pos_a: pd.DataFrame,
    pos_b: pd.DataFrame,
    vessel_a: dict,
    vessel_b: dict,
) -> QualityMetrics:
    """Compute quality metrics for an encounter.

    Args:
        encounter: Encounter record dict
        pos_a: Positions DataFrame for vessel A
        pos_b: Positions DataFrame for vessel B
        vessel_a: Vessel A metadata dict
        vessel_b: Vessel B metadata dict

    Returns:
        QualityMetrics with completeness score and counts
    """
    # Count positions
    n_pos_a = len(pos_a)
    n_pos_b = len(pos_b)

    # Compute duration
    start_time = pd.Timestamp(encounter["start_time"])
    end_time = pd.Timestamp(encounter["end_time"]) if encounter["end_time"] else start_time
    duration_s = (end_time - start_time).total_seconds()

    # Check CPA/TCPA
    has_cpa = (
        encounter.get("cpa_m") is not None
        and encounter.get("tcpa_s") is not None
        and encounter.get("min_distance_m") is not None
    )

    # Check vessel metadata completeness
    def _vessel_complete(v: dict) -> bool:
        return all(
            v.get(k) is not None
            for k in ["name", "ship_type", "length", "width"]
        )

    has_vessel_meta = _vessel_complete(vessel_a) and _vessel_complete(vessel_b)

    # Compute completeness score (0.0-1.0)
    score = 0.0
    score += 0.3 if n_pos_a >= 10 and n_pos_b >= 10 else 0.15 * (n_pos_a + n_pos_b) / 20
    score += 0.2 if has_cpa else 0.0
    score += 0.2 if has_vessel_meta else 0.0
    score += 0.15 if duration_s >= 60.0 else 0.0
    score += 0.15 if encounter.get("encounter_type") else 0.0

    return QualityMetrics(
        completeness=min(score, 1.0),
        position_count_a=n_pos_a,
        position_count_b=n_pos_b,
        duration_s=duration_s,
        has_cpa=has_cpa,
        has_vessel_meta=has_vessel_meta,
    )


def filter_encounters(
    config: ExportConfig,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Filter encounters based on export configuration.

    Args:
        config: ExportConfig with filtering criteria
        db_path: Optional database path

    Returns:
        List of encounter dicts that pass all filters
    """
    conn = _get_conn(db_path)

    # Build SQL query with filters
    where_clauses = ["end_time IS NOT NULL"]
    params = []

    if config.encounter_types:
        placeholders = ",".join("?" * len(config.encounter_types))
        where_clauses.append(f"encounter_type IN ({placeholders})")
        params.extend(config.encounter_types)

    if config.start_date:
        where_clauses.append("start_time >= ?")
        params.append(config.start_date)

    if config.end_date:
        where_clauses.append("start_time <= ?")
        params.append(config.end_date)

    where_sql = " AND ".join(where_clauses)
    query = f"SELECT * FROM encounters WHERE {where_sql} ORDER BY start_time"

    encounters = pd.read_sql_query(query, conn, params=params)

    if encounters.empty:
        conn.close()
        logger.warning("No encounters found matching filters.")
        return []

    # Apply quality filters
    filtered = []
    for _, enc in encounters.iterrows():
        enc_dict = dict(enc)

        # Get positions
        pos_df = pd.read_sql_query(
            "SELECT * FROM encounter_positions WHERE encounter_id = ? ORDER BY timestamp",
            conn,
            params=(enc["id"],),
        )
        pos_a = pos_df[pos_df["mmsi"] == enc["vessel_a_mmsi"]]
        pos_b = pos_df[pos_df["mmsi"] == enc["vessel_b_mmsi"]]

        # Get vessel metadata
        vessel_a = dict(
            conn.execute(
                "SELECT * FROM vessels WHERE mmsi = ?", (enc["vessel_a_mmsi"],)
            ).fetchone()
            or {}
        )
        vessel_b = dict(
            conn.execute(
                "SELECT * FROM vessels WHERE mmsi = ?", (enc["vessel_b_mmsi"],)
            ).fetchone()
            or {}
        )

        # Compute quality metrics
        quality = compute_encounter_quality(enc_dict, pos_a, pos_b, vessel_a, vessel_b)

        # Apply quality thresholds
        if quality.position_count_a < config.min_positions:
            continue
        if quality.position_count_b < config.min_positions:
            continue
        if quality.duration_s < config.min_duration_s:
            continue
        if quality.completeness < config.quality_threshold:
            continue

        # Store quality metrics with encounter
        enc_dict["_quality"] = quality
        filtered.append(enc_dict)

    conn.close()
    logger.info(
        "Filtered %d/%d encounters (quality >= %.2f, min_pos >= %d, min_duration >= %.1fs)",
        len(filtered),
        len(encounters),
        config.quality_threshold,
        config.min_positions,
        config.min_duration_s,
    )

    return filtered


def export_trajectories(
    output_path: str,
    config: ExportConfig,
    format: FormatType = "csv",
    db_path: Optional[str] = None,
) -> None:
    """Export trajectory segments to file.

    Args:
        output_path: Output file path
        config: ExportConfig with filtering criteria
        format: Output format ("csv" or "parquet")
        db_path: Optional database path
    """
    logger.info("Extracting trajectory segments...")
    segments = extract_trajectories(db_path=db_path)

    if not segments:
        logger.warning("No trajectory segments to export.")
        return

    # Convert to feature arrays
    feature_arrays = trajectories_to_features(segments)

    # Combine all segments into a single DataFrame
    rows = []
    for seg_idx, (seg, features) in enumerate(zip(segments, feature_arrays)):
        for i in range(len(features)):
            row = {
                "segment_id": seg_idx,
                "mmsi": seg.iloc[i]["mmsi"],
                "timestamp": seg.iloc[i]["timestamp"],
                "lat": seg.iloc[i]["lat"],
                "lon": seg.iloc[i]["lon"],
                "sog": seg.iloc[i]["sog"],
                "cog": seg.iloc[i]["cog"],
                "heading": seg.iloc[i]["heading"],
            }
            # Add feature columns
            feature_names = [
                "delta_x",
                "delta_y",
                "sog",
                "cog_sin",
                "cog_cos",
                "heading_sin",
                "heading_cos",
                "acceleration",
                "rate_of_turn",
                "delta_t",
            ]
            for j, name in enumerate(feature_names):
                row[f"feat_{name}"] = features[i, j]

            rows.append(row)

    df = pd.DataFrame(rows)

    # Apply date filters if specified
    if config.start_date or config.end_date:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        if config.start_date:
            df = df[df["timestamp"] >= config.start_date]
        if config.end_date:
            df = df[df["timestamp"] <= config.end_date]

    # Save to file
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    if format == "csv":
        df.to_csv(output_path, index=False)
    elif format == "parquet":
        df.to_parquet(output_path, index=False)

    logger.info(
        "Exported %d trajectory rows (%d segments) to %s",
        len(df),
        len(segments),
        output_path,
    )


def export_encounters(
    output_path: str,
    config: ExportConfig,
    format: FormatType = "csv",
    db_path: Optional[str] = None,
) -> None:
    """Export encounter features for risk classification.

    Args:
        output_path: Output file path
        config: ExportConfig with filtering criteria
        format: Output format ("csv" or "parquet")
        db_path: Optional database path
    """
    logger.info("Extracting encounter features...")

    # Filter encounters
    filtered_encounters = filter_encounters(config, db_path=db_path)

    if not filtered_encounters:
        logger.warning("No encounters to export.")
        return

    # Extract features (reuses existing extract_encounters logic)
    df = extract_encounters(db_path=db_path)

    if df.empty:
        logger.warning("No encounter features extracted.")
        return

    # Filter by encounter IDs
    encounter_ids = [enc["id"] for enc in filtered_encounters]
    df = df[df["encounter_id"].isin(encounter_ids)]

    # Add quality metrics
    quality_data = []
    for enc in filtered_encounters:
        q = enc["_quality"]
        quality_data.append(
            {
                "encounter_id": enc["id"],
                "quality_completeness": q.completeness,
                "quality_pos_count_a": q.position_count_a,
                "quality_pos_count_b": q.position_count_b,
                "quality_duration_s": q.duration_s,
                "quality_has_cpa": q.has_cpa,
                "quality_has_vessel_meta": q.has_vessel_meta,
            }
        )

    quality_df = pd.DataFrame(quality_data)
    df = df.merge(quality_df, on="encounter_id", how="left")

    # Save to file
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    if format == "csv":
        df.to_csv(output_path, index=False)
    elif format == "parquet":
        df.to_parquet(output_path, index=False)

    logger.info("Exported %d encounter features to %s", len(df), output_path)


def export_encounter_pairs(
    output_path: str,
    config: ExportConfig,
    format: FormatType = "csv",
    db_path: Optional[str] = None,
) -> None:
    """Export state-action pairs for behavioral cloning/RL.

    Args:
        output_path: Output file path
        config: ExportConfig with filtering criteria
        format: Output format ("csv" or "parquet")
        db_path: Optional database path
    """
    logger.info("Extracting encounter pairs...")

    # Filter encounters
    filtered_encounters = filter_encounters(config, db_path=db_path)

    if not filtered_encounters:
        logger.warning("No encounters to export.")
        return

    # Extract pairs (reuses existing extract_encounter_pairs logic)
    pairs = extract_encounter_pairs(db_path=db_path)

    if not pairs:
        logger.warning("No encounter pairs extracted.")
        return

    # Filter by encounter IDs
    encounter_ids = {enc["id"] for enc in filtered_encounters}
    pairs = [p for p in pairs if p["encounter_id"] in encounter_ids]

    # Convert to DataFrame format
    # Each row is a state-action pair at a timestep
    rows = []
    for pair in pairs:
        enc_id = pair["encounter_id"]
        enc_type = pair["encounter_type"]

        # Vessel A pairs
        states_a = pair["states_a"]
        actions_a = pair["actions_a"]
        for i in range(len(actions_a)):
            row = {"encounter_id": enc_id, "encounter_type": enc_type, "vessel": "A"}
            for j, val in enumerate(states_a[i]):
                row[f"state_{j}"] = val
            row["action_turn_rate"] = actions_a[i][0]
            row["action_accel_rate"] = actions_a[i][1]
            rows.append(row)

        # Vessel B pairs
        states_b = pair["states_b"]
        actions_b = pair["actions_b"]
        for i in range(len(actions_b)):
            row = {"encounter_id": enc_id, "encounter_type": enc_type, "vessel": "B"}
            for j, val in enumerate(states_b[i]):
                row[f"state_{j}"] = val
            row["action_turn_rate"] = actions_b[i][0]
            row["action_accel_rate"] = actions_b[i][1]
            rows.append(row)

    df = pd.DataFrame(rows)

    # Save to file
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    if format == "csv":
        df.to_csv(output_path, index=False)
    elif format == "parquet":
        df.to_parquet(output_path, index=False)

    logger.info(
        "Exported %d state-action pairs (%d encounters) to %s",
        len(df),
        len(pairs),
        output_path,
    )


def export_dataset_summary(
    output_path: str,
    config: ExportConfig,
    db_path: Optional[str] = None,
) -> None:
    """Export dataset summary with quality metrics.

    Args:
        output_path: Output file path (CSV)
        config: ExportConfig with filtering criteria
        db_path: Optional database path
    """
    logger.info("Generating dataset summary...")

    filtered_encounters = filter_encounters(config, db_path=db_path)

    if not filtered_encounters:
        logger.warning("No encounters to summarize.")
        return

    rows = []
    for enc in filtered_encounters:
        q = enc["_quality"]
        rows.append(
            {
                "encounter_id": enc["id"],
                "vessel_a_mmsi": enc["vessel_a_mmsi"],
                "vessel_b_mmsi": enc["vessel_b_mmsi"],
                "start_time": enc["start_time"],
                "end_time": enc["end_time"],
                "encounter_type": enc["encounter_type"],
                "min_distance_m": enc["min_distance_m"],
                "cpa_m": enc.get("cpa_m"),
                "tcpa_s": enc.get("tcpa_s"),
                "quality_completeness": q.completeness,
                "quality_pos_count_a": q.position_count_a,
                "quality_pos_count_b": q.position_count_b,
                "quality_duration_s": q.duration_s,
                "quality_has_cpa": q.has_cpa,
                "quality_has_vessel_meta": q.has_vessel_meta,
            }
        )

    df = pd.DataFrame(rows)

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    logger.info("Exported dataset summary (%d encounters) to %s", len(df), output_path)
