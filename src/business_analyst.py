"""Business Analyst & Monitoring Agent — Python analyse utility.

Geeft gestructureerde database-analyse output die de /business-analyst
Claude skill kan gebruiken. Kan ook standalone gedraaid worden.

Gebruik:
    python -m src.business_analyst              # Volledig rapport (tekst)
    python -m src.business_analyst --json       # JSON output
    python -m src.business_analyst kpis         # Alleen KPI's
    python -m src.business_analyst quality      # Datakwaliteit
    python -m src.business_analyst ml-readiness # ML gereedheid
"""

import argparse
import json
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.config import DB_PATH, BOUNDING_BOXES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DataVolumeMetrics:
    total_vessels: int = 0
    total_positions: int = 0
    total_encounters: int = 0
    completed_encounters: int = 0
    open_encounters: int = 0
    total_encounter_positions: int = 0
    avg_positions_per_encounter: float = 0.0
    db_size_mb: float = 0.0


@dataclass
class DataQualityMetrics:
    vessels_without_name: int = 0
    vessels_without_ship_type: int = 0
    vessels_without_dimensions: int = 0
    vessel_completeness_pct: float = 0.0
    encounters_without_end: int = 0
    encounters_without_min_distance: int = 0
    encounter_completeness_pct: float = 0.0
    avg_position_interval_s: float = 0.0


@dataclass
class TemporalMetrics:
    earliest_position: str = ""
    latest_position: str = ""
    collection_duration_hours: float = 0.0
    positions_per_hour: float = 0.0
    encounters_per_hour: float = 0.0
    active_hours: int = 0
    gap_hours: int = 0
    uptime_pct: float = 0.0


@dataclass
class EncounterDistribution:
    by_type: dict = field(default_factory=dict)
    by_risk: dict = field(default_factory=dict)
    distance_stats: dict = field(default_factory=dict)
    duration_stats: dict = field(default_factory=dict)


@dataclass
class MLReadiness:
    trajectory_segments: int = 0
    trajectory_ready: bool = False
    encounter_samples: int = 0
    encounter_ready: bool = False
    bc_pairs: int = 0
    bc_ready: bool = False
    encounter_type_balance: dict = field(default_factory=dict)
    risk_label_balance: dict = field(default_factory=dict)
    overall_ready: bool = False
    bottleneck: str = ""


@dataclass
class VesselAnalysis:
    unique_vessels: int = 0
    ship_type_distribution: dict = field(default_factory=dict)
    avg_positions_per_vessel: float = 0.0
    vessels_in_encounters: int = 0
    participation_pct: float = 0.0


@dataclass
class BusinessReport:
    generated_at: str = ""
    data_volume: DataVolumeMetrics = field(default_factory=DataVolumeMetrics)
    data_quality: DataQualityMetrics = field(default_factory=DataQualityMetrics)
    temporal: TemporalMetrics = field(default_factory=TemporalMetrics)
    encounters: EncounterDistribution = field(default_factory=EncounterDistribution)
    vessels: VesselAnalysis = field(default_factory=VesselAnalysis)
    ml_readiness: MLReadiness = field(default_factory=MLReadiness)


# ---------------------------------------------------------------------------
# AIS scheepstypes (vereenvoudigd)
# ---------------------------------------------------------------------------

SHIP_TYPE_NAMES = {
    0: "Niet beschikbaar", 30: "Visserij", 31: "Sleepboot",
    33: "Baggerschip", 35: "Militair", 36: "Zeilboot",
    37: "Pleziervaartuig", 40: "High speed craft", 50: "Loods",
    51: "Search & Rescue", 52: "Sleepboot", 60: "Passagiersschip",
    70: "Vrachtschip", 80: "Tanker", 90: "Overig",
}


def _ship_type_name(code: int) -> str:
    if code is None:
        return "Onbekend"
    base = (code // 10) * 10
    return SHIP_TYPE_NAMES.get(code, SHIP_TYPE_NAMES.get(base, f"Type {code}"))


# ---------------------------------------------------------------------------
# Database connectie
# ---------------------------------------------------------------------------

def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Analyse functies
# ---------------------------------------------------------------------------

def analyze_data_volume(conn: sqlite3.Connection, db_path: str) -> DataVolumeMetrics:
    m = DataVolumeMetrics()
    m.total_vessels = conn.execute("SELECT COUNT(*) FROM vessels").fetchone()[0]
    m.total_positions = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    m.total_encounters = conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0]
    m.completed_encounters = conn.execute(
        "SELECT COUNT(*) FROM encounters WHERE end_time IS NOT NULL"
    ).fetchone()[0]
    m.open_encounters = m.total_encounters - m.completed_encounters
    m.total_encounter_positions = conn.execute(
        "SELECT COUNT(*) FROM encounter_positions"
    ).fetchone()[0]
    if m.total_encounters > 0:
        m.avg_positions_per_encounter = m.total_encounter_positions / m.total_encounters
    db_file = Path(db_path)
    if db_file.exists():
        m.db_size_mb = db_file.stat().st_size / (1024 * 1024)
    return m


def analyze_data_quality(conn: sqlite3.Connection) -> DataQualityMetrics:
    m = DataQualityMetrics()
    m.vessels_without_name = conn.execute(
        "SELECT COUNT(*) FROM vessels WHERE name IS NULL OR name = ''"
    ).fetchone()[0]
    m.vessels_without_ship_type = conn.execute(
        "SELECT COUNT(*) FROM vessels WHERE ship_type IS NULL OR ship_type = 0"
    ).fetchone()[0]
    m.vessels_without_dimensions = conn.execute(
        "SELECT COUNT(*) FROM vessels WHERE length IS NULL OR length = 0 "
        "OR width IS NULL OR width = 0"
    ).fetchone()[0]
    total_vessels = conn.execute("SELECT COUNT(*) FROM vessels").fetchone()[0]
    if total_vessels > 0:
        complete = conn.execute(
            "SELECT COUNT(*) FROM vessels WHERE name IS NOT NULL AND name != '' "
            "AND ship_type IS NOT NULL AND ship_type > 0 "
            "AND length IS NOT NULL AND length > 0"
        ).fetchone()[0]
        m.vessel_completeness_pct = round(100.0 * complete / total_vessels, 1)
    total_enc = conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0]
    m.encounters_without_end = conn.execute(
        "SELECT COUNT(*) FROM encounters WHERE end_time IS NULL"
    ).fetchone()[0]
    m.encounters_without_min_distance = conn.execute(
        "SELECT COUNT(*) FROM encounters WHERE min_distance_m IS NULL"
    ).fetchone()[0]
    if total_enc > 0:
        complete_enc = conn.execute(
            "SELECT COUNT(*) FROM encounters WHERE end_time IS NOT NULL "
            "AND min_distance_m IS NOT NULL AND cpa_m IS NOT NULL"
        ).fetchone()[0]
        m.encounter_completeness_pct = round(100.0 * complete_enc / total_enc, 1)
    return m


def analyze_temporal(conn: sqlite3.Connection) -> TemporalMetrics:
    m = TemporalMetrics()
    time_range = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM positions"
    ).fetchone()
    if time_range[0] is None:
        return m
    m.earliest_position = time_range[0]
    m.latest_position = time_range[1]
    try:
        t_min = pd.Timestamp(time_range[0])
        t_max = pd.Timestamp(time_range[1])
        m.collection_duration_hours = round((t_max - t_min).total_seconds() / 3600, 1)
    except Exception:
        return m
    if m.collection_duration_hours > 0:
        total_pos = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        total_enc = conn.execute(
            "SELECT COUNT(*) FROM encounters WHERE end_time IS NOT NULL"
        ).fetchone()[0]
        m.positions_per_hour = round(total_pos / m.collection_duration_hours, 0)
        m.encounters_per_hour = round(total_enc / m.collection_duration_hours, 1)
    hourly = conn.execute(
        "SELECT strftime('%Y-%m-%d %H', timestamp) AS hour, COUNT(*) "
        "FROM positions GROUP BY hour"
    ).fetchall()
    m.active_hours = len(hourly)
    total_hours = max(1, int(m.collection_duration_hours) + 1)
    m.gap_hours = max(0, total_hours - m.active_hours)
    m.uptime_pct = round(100.0 * m.active_hours / total_hours, 1)
    return m


def analyze_encounters(conn: sqlite3.Connection) -> EncounterDistribution:
    m = EncounterDistribution()
    types = conn.execute(
        "SELECT encounter_type, COUNT(*) AS cnt FROM encounters "
        "WHERE end_time IS NOT NULL GROUP BY encounter_type"
    ).fetchall()
    m.by_type = {row["encounter_type"]: row["cnt"] for row in types}
    risk_rows = conn.execute(
        "SELECT min_distance_m FROM encounters "
        "WHERE end_time IS NOT NULL AND min_distance_m IS NOT NULL"
    ).fetchall()
    if risk_rows:
        dists = [row["min_distance_m"] for row in risk_rows]
        m.by_risk = {
            "HIGH": sum(1 for d in dists if d < 500),
            "MEDIUM": sum(1 for d in dists if 500 <= d < 1000),
            "LOW": sum(1 for d in dists if d >= 1000),
        }
        m.distance_stats = {
            "min_m": round(float(np.min(dists))),
            "mean_m": round(float(np.mean(dists))),
            "median_m": round(float(np.median(dists))),
            "max_m": round(float(np.max(dists))),
        }
    duration_rows = conn.execute(
        "SELECT (julianday(end_time) - julianday(start_time)) * 86400 AS duration_s "
        "FROM encounters WHERE end_time IS NOT NULL AND start_time IS NOT NULL"
    ).fetchall()
    if duration_rows:
        durations = [r["duration_s"] for r in duration_rows if r["duration_s"] and r["duration_s"] > 0]
        if durations:
            m.duration_stats = {
                "min_min": round(float(np.min(durations)) / 60, 1),
                "mean_min": round(float(np.mean(durations)) / 60, 1),
                "median_min": round(float(np.median(durations)) / 60, 1),
                "max_min": round(float(np.max(durations)) / 60, 1),
            }
    return m


def analyze_vessels(conn: sqlite3.Connection) -> VesselAnalysis:
    m = VesselAnalysis()
    m.unique_vessels = conn.execute("SELECT COUNT(*) FROM vessels").fetchone()[0]
    type_rows = conn.execute(
        "SELECT ship_type, COUNT(*) AS cnt FROM vessels "
        "WHERE ship_type IS NOT NULL AND ship_type > 0 "
        "GROUP BY ship_type ORDER BY cnt DESC"
    ).fetchall()
    m.ship_type_distribution = {
        _ship_type_name(row["ship_type"]): row["cnt"] for row in type_rows
    }
    avg_row = conn.execute(
        "SELECT AVG(cnt) FROM (SELECT COUNT(*) AS cnt FROM positions GROUP BY mmsi)"
    ).fetchone()
    m.avg_positions_per_vessel = round(avg_row[0] or 0.0, 1)
    vessels_in_enc = conn.execute(
        "SELECT COUNT(DISTINCT mmsi) FROM ("
        "SELECT vessel_a_mmsi AS mmsi FROM encounters UNION "
        "SELECT vessel_b_mmsi AS mmsi FROM encounters)"
    ).fetchone()[0]
    m.vessels_in_encounters = vessels_in_enc
    if m.unique_vessels > 0:
        m.participation_pct = round(100.0 * vessels_in_enc / m.unique_vessels, 1)
    return m


def analyze_ml_readiness(conn: sqlite3.Connection) -> MLReadiness:
    m = MLReadiness()
    MIN_TRAJ = 100
    MIN_ENC = 50
    MIN_BC = 50

    vessel_counts = conn.execute(
        "SELECT COUNT(*) FROM (SELECT mmsi FROM positions GROUP BY mmsi HAVING COUNT(*) >= 20)"
    ).fetchone()[0]
    m.trajectory_segments = vessel_counts
    m.trajectory_ready = vessel_counts >= MIN_TRAJ

    m.encounter_samples = conn.execute(
        "SELECT COUNT(*) FROM encounters WHERE end_time IS NOT NULL AND min_distance_m IS NOT NULL"
    ).fetchone()[0]
    m.encounter_ready = m.encounter_samples >= MIN_ENC

    m.bc_pairs = conn.execute(
        "SELECT COUNT(*) FROM encounters e WHERE e.end_time IS NOT NULL "
        "AND (SELECT COUNT(*) FROM encounter_positions ep "
        "WHERE ep.encounter_id = e.id AND ep.mmsi = e.vessel_a_mmsi) >= 3 "
        "AND (SELECT COUNT(*) FROM encounter_positions ep "
        "WHERE ep.encounter_id = e.id AND ep.mmsi = e.vessel_b_mmsi) >= 3"
    ).fetchone()[0]
    m.bc_ready = m.bc_pairs >= MIN_BC

    types = conn.execute(
        "SELECT encounter_type, COUNT(*) AS cnt FROM encounters "
        "WHERE end_time IS NOT NULL GROUP BY encounter_type"
    ).fetchall()
    total = sum(r["cnt"] for r in types) if types else 0
    m.encounter_type_balance = {
        r["encounter_type"]: {"count": r["cnt"], "pct": round(100.0 * r["cnt"] / total, 1) if total else 0}
        for r in types
    }

    risk_rows = conn.execute(
        "SELECT min_distance_m FROM encounters "
        "WHERE end_time IS NOT NULL AND min_distance_m IS NOT NULL"
    ).fetchall()
    if risk_rows:
        labels = Counter()
        for r in risk_rows:
            d = r["min_distance_m"]
            labels["HIGH" if d < 500 else "MEDIUM" if d < 1000 else "LOW"] += 1
        total_l = sum(labels.values())
        m.risk_label_balance = {
            k: {"count": v, "pct": round(100.0 * v / total_l, 1)} for k, v in labels.items()
        }

    m.overall_ready = m.trajectory_ready and m.encounter_ready and m.bc_ready
    if not m.trajectory_ready:
        m.bottleneck = f"Trajectory: {m.trajectory_segments}/{MIN_TRAJ}"
    elif not m.encounter_ready:
        m.bottleneck = f"Encounters: {m.encounter_samples}/{MIN_ENC}"
    elif not m.bc_ready:
        m.bottleneck = f"BC paren: {m.bc_pairs}/{MIN_BC}"
    else:
        m.bottleneck = "Geen — alle modellen gereed"
    return m


# ---------------------------------------------------------------------------
# Rapport generatie
# ---------------------------------------------------------------------------

def generate_report(db_path: Optional[str] = None) -> BusinessReport:
    path = db_path or DB_PATH
    conn = _get_conn(path)
    report = BusinessReport()
    report.generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    report.data_volume = analyze_data_volume(conn, path)
    report.data_quality = analyze_data_quality(conn)
    report.temporal = analyze_temporal(conn)
    report.encounters = analyze_encounters(conn)
    report.vessels = analyze_vessels(conn)
    report.ml_readiness = analyze_ml_readiness(conn)
    conn.close()
    return report


# ---------------------------------------------------------------------------
# Output formattering
# ---------------------------------------------------------------------------

def _bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return f"[{'#' * filled}{'.' * (width - filled)}] {pct:.1f}%"


def print_kpis(report: BusinessReport):
    vol = report.data_volume
    temp = report.temporal
    qual = report.data_quality
    ml = report.ml_readiness

    print("\n=== KPI DASHBOARD ===\n")
    print(f"  {'Metric':<35} {'Waarde':>12}")
    print(f"  {'-' * 50}")
    print(f"  {'Totaal posities':<35} {vol.total_positions:>12,}")
    print(f"  {'Totaal schepen':<35} {vol.total_vessels:>12,}")
    print(f"  {'Voltooide encounters':<35} {vol.completed_encounters:>12,}")
    print(f"  {'Posities/uur':<35} {temp.positions_per_hour:>12,.0f}")
    print(f"  {'Encounters/uur':<35} {temp.encounters_per_hour:>12,.1f}")
    print(f"  {'Uptime':<35} {_bar(temp.uptime_pct):>12}")
    print(f"  {'Vessel completeness':<35} {_bar(qual.vessel_completeness_pct):>12}")
    print(f"  {'ML readiness':<35} {'GEREED' if ml.overall_ready else 'NIET GEREED':>12}")
    print(f"  {'Database grootte':<35} {vol.db_size_mb:>11.1f} MB")


def print_quality(report: BusinessReport):
    qual = report.data_quality
    print("\n=== DATAKWALITEIT ===\n")
    print(f"  Zonder naam:        {qual.vessels_without_name}")
    print(f"  Zonder scheepstype: {qual.vessels_without_ship_type}")
    print(f"  Zonder afmetingen:  {qual.vessels_without_dimensions}")
    print(f"  Volledigheid:       {_bar(qual.vessel_completeness_pct)}")
    print(f"  Open encounters:    {qual.encounters_without_end}")
    print(f"  Encounter compleet: {_bar(qual.encounter_completeness_pct)}")


def print_ml_readiness(report: BusinessReport):
    ml = report.ml_readiness
    print("\n=== ML READINESS ===\n")
    print(f"  Trajectory (LSTM):  {ml.trajectory_segments}/100 {'OK' if ml.trajectory_ready else 'ONVOLDOENDE'}")
    print(f"  Risk (XGBoost):     {ml.encounter_samples}/50 {'OK' if ml.encounter_ready else 'ONVOLDOENDE'}")
    print(f"  BC/RL (PPO):        {ml.bc_pairs}/50 {'OK' if ml.bc_ready else 'ONVOLDOENDE'}")
    print(f"  Overall:            {'GEREED' if ml.overall_ready else 'NIET GEREED'}")
    print(f"  Bottleneck:         {ml.bottleneck}")
    if ml.encounter_type_balance:
        print(f"\n  Type balans:")
        for t, info in ml.encounter_type_balance.items():
            print(f"    {t:<15} {info['count']:>5} ({info['pct']}%)")


def print_full_report(report: BusinessReport):
    vol = report.data_volume
    temp = report.temporal
    enc = report.encounters
    ves = report.vessels

    print(f"\n{'=' * 50}")
    print(f"  BUSINESS ANALYST RAPPORT")
    print(f"  {report.generated_at}")
    print(f"{'=' * 50}")

    print(f"\n--- DATA VOLUME ---")
    print(f"  Schepen:            {vol.total_vessels:,}")
    print(f"  Posities:           {vol.total_positions:,}")
    print(f"  Encounters:         {vol.completed_encounters:,} voltooid / {vol.open_encounters:,} open")
    print(f"  Enc. posities:      {vol.total_encounter_positions:,}")
    print(f"  Database:           {vol.db_size_mb:.1f} MB")

    print(f"\n--- TEMPOREEL ---")
    print(f"  Bereik:             {temp.earliest_position} — {temp.latest_position}")
    print(f"  Duur:               {temp.collection_duration_hours:.1f} uur")
    print(f"  Pos/uur:            {temp.positions_per_hour:,.0f}")
    print(f"  Enc/uur:            {temp.encounters_per_hour:.1f}")
    print(f"  Uptime:             {_bar(temp.uptime_pct)}")

    if enc.by_type:
        print(f"\n--- ENCOUNTERS ---")
        for t, c in enc.by_type.items():
            print(f"  {t:<15} {c:>5}")
        if enc.distance_stats:
            print(f"  Afstand: min={enc.distance_stats.get('min_m', 0)}m, "
                  f"gem={enc.distance_stats.get('mean_m', 0)}m, "
                  f"max={enc.distance_stats.get('max_m', 0)}m")

    if ves.ship_type_distribution:
        print(f"\n--- SCHEEPSTYPES (top 5) ---")
        for t, c in list(ves.ship_type_distribution.items())[:5]:
            print(f"  {t:<25} {c:>5}")

    print_kpis(report)
    print_ml_readiness(report)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Business Analyst — Marine Traffic Encounter Database"
    )
    parser.add_argument("--db", type=str, default=None, help="Pad naar SQLite database")
    parser.add_argument("--json", action="store_true", help="Output als JSON")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("report", help="Volledig rapport")
    sub.add_parser("kpis", help="KPI dashboard")
    sub.add_parser("quality", help="Datakwaliteit")
    sub.add_parser("ml-readiness", help="ML gereedheid")

    args = parser.parse_args()
    report = generate_report(args.db)

    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
        return

    if args.command == "kpis":
        print_kpis(report)
    elif args.command == "quality":
        print_quality(report)
    elif args.command == "ml-readiness":
        print_ml_readiness(report)
    else:
        print_full_report(report)


if __name__ == "__main__":
    main()
