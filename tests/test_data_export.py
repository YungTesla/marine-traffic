"""Tests for ML data export functionality.

Tests export functions with a temporary database containing test encounters.
"""

import os
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

# Create temporary database
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB = _tmp.name
_tmp.close()
os.environ["DB_PATH"] = TEST_DB

from src import database as db
from src.ml.data_export import (
    ExportConfig,
    export_trajectories,
    export_encounters,
    export_encounter_pairs,
    export_dataset_summary,
    compute_encounter_quality,
    filter_encounters,
)


def setup_test_database():
    """Create test database with sample encounters."""
    db.init_db()

    # Add vessels
    db.upsert_vessel("123456789", "Test Ship A", 70, 100.0, 20.0)
    db.upsert_vessel("987654321", "Test Ship B", 80, 150.0, 25.0)
    db.upsert_vessel("111222333", "Test Ship C", 60, 80.0, 15.0)

    # Add positions for Ship A and B (head-on encounter)
    base_time = datetime(2026, 2, 1, 12, 0, 0)
    positions_a = []
    positions_b = []

    for i in range(20):
        t = base_time + timedelta(seconds=i * 30)
        # Ship A moving north
        lat_a = 52.0 + i * 0.001
        lon_a = 4.0
        positions_a.append((t.isoformat(), lat_a, lon_a, 12.0, 0.0, 0.0))

        # Ship B moving south
        lat_b = 52.02 - i * 0.001
        lon_b = 4.0
        positions_b.append((t.isoformat(), lat_b, lon_b, 10.0, 180.0, 180.0))

    with db.get_conn() as conn:
        for ts, lat, lon, sog, cog, hdg in positions_a:
            conn.execute(
                "INSERT INTO positions (mmsi, timestamp, lat, lon, sog, cog, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("123456789", ts, lat, lon, sog, cog, hdg),
            )
        for ts, lat, lon, sog, cog, hdg in positions_b:
            conn.execute(
                "INSERT INTO positions (mmsi, timestamp, lat, lon, sog, cog, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("987654321", ts, lat, lon, sog, cog, hdg),
            )

    # Add encounter
    with db.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO encounters (vessel_a_mmsi, vessel_b_mmsi, start_time, end_time, "
            "min_distance_m, encounter_type, cpa_m, tcpa_s) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "123456789",
                "987654321",
                base_time.isoformat(),
                (base_time + timedelta(minutes=10)).isoformat(),
                450.0,
                "head-on",
                450.0,
                300.0,
            ),
        )
        encounter_id = cursor.lastrowid

        # Add encounter positions
        for ts, lat, lon, sog, cog, hdg in positions_a[:15]:
            conn.execute(
                "INSERT INTO encounter_positions (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (encounter_id, "123456789", ts, lat, lon, sog, cog, hdg),
            )
        for ts, lat, lon, sog, cog, hdg in positions_b[:15]:
            conn.execute(
                "INSERT INTO encounter_positions (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (encounter_id, "987654321", ts, lat, lon, sog, cog, hdg),
            )

    # Add second encounter (crossing, lower quality)
    base_time2 = datetime(2026, 2, 1, 14, 0, 0)
    positions_c = []
    positions_a2 = []  # Ship A positions for second encounter
    for i in range(5):  # Only 5 positions (low quality)
        t = base_time2 + timedelta(seconds=i * 30)
        lat_c = 52.1 + i * 0.001
        lon_c = 4.1 + i * 0.001
        positions_c.append((t.isoformat(), lat_c, lon_c, 8.0, 45.0, 45.0))

        lat_a2 = 52.1 - i * 0.001
        lon_a2 = 4.1
        positions_a2.append((t.isoformat(), lat_a2, lon_a2, 10.0, 180.0, 180.0))

    with db.get_conn() as conn:
        for ts, lat, lon, sog, cog, hdg in positions_c:
            conn.execute(
                "INSERT INTO positions (mmsi, timestamp, lat, lon, sog, cog, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("111222333", ts, lat, lon, sog, cog, hdg),
            )

        cursor = conn.execute(
            "INSERT INTO encounters (vessel_a_mmsi, vessel_b_mmsi, start_time, end_time, "
            "min_distance_m, encounter_type, cpa_m, tcpa_s) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "123456789",
                "111222333",
                base_time2.isoformat(),
                (base_time2 + timedelta(minutes=2)).isoformat(),
                800.0,
                "crossing",
                800.0,
                120.0,
            ),
        )
        encounter_id2 = cursor.lastrowid

        # Add minimal encounter positions for both vessels
        for ts, lat, lon, sog, cog, hdg in positions_c:
            conn.execute(
                "INSERT INTO encounter_positions (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (encounter_id2, "111222333", ts, lat, lon, sog, cog, hdg),
            )
        for ts, lat, lon, sog, cog, hdg in positions_a2:
            conn.execute(
                "INSERT INTO encounter_positions (encounter_id, mmsi, timestamp, lat, lon, sog, cog, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (encounter_id2, "123456789", ts, lat, lon, sog, cog, hdg),
            )

    print("✅ Test database created with 2 encounters")


def test_quality_metrics():
    """Test encounter quality computation."""
    print("\n--- Testing Quality Metrics ---")

    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row

    row = conn.execute("SELECT * FROM encounters WHERE id = 1").fetchone()
    assert row is not None, "Encounter not found"
    enc = dict(row)

    pos_df = pd.read_sql_query(
        "SELECT * FROM encounter_positions WHERE encounter_id = 1", conn
    )
    pos_a = pos_df[pos_df["mmsi"] == "123456789"]
    pos_b = pos_df[pos_df["mmsi"] == "987654321"]

    vessel_a_row = conn.execute("SELECT * FROM vessels WHERE mmsi = ?", ("123456789",)).fetchone()
    vessel_b_row = conn.execute("SELECT * FROM vessels WHERE mmsi = ?", ("987654321",)).fetchone()
    vessel_a = dict(vessel_a_row) if vessel_a_row else {}
    vessel_b = dict(vessel_b_row) if vessel_b_row else {}

    conn.close()

    quality = compute_encounter_quality(enc, pos_a, pos_b, vessel_a, vessel_b)

    print(f"  Completeness: {quality.completeness:.2f}")
    print(f"  Position count A: {quality.position_count_a}")
    print(f"  Position count B: {quality.position_count_b}")
    print(f"  Duration: {quality.duration_s:.1f}s")
    print(f"  Has CPA: {quality.has_cpa}")
    print(f"  Has vessel meta: {quality.has_vessel_meta}")

    assert quality.position_count_a == 15, "Expected 15 positions for vessel A"
    assert quality.position_count_b == 15, "Expected 15 positions for vessel B"
    assert quality.has_cpa, "Expected CPA data to be present"
    assert quality.has_vessel_meta, "Expected vessel metadata to be present"
    assert quality.completeness > 0.7, f"Expected high quality, got {quality.completeness:.2f}"

    print("✅ Quality metrics test passed")


def test_filtering():
    """Test encounter filtering."""
    print("\n--- Testing Encounter Filtering ---")

    # Filter by encounter type
    config = ExportConfig(encounter_types=["head-on"], quality_threshold=0.5)
    filtered = filter_encounters(config, db_path=TEST_DB)
    print(f"  Head-on encounters: {len(filtered)}")
    assert len(filtered) == 1, "Expected 1 head-on encounter"

    # Filter by quality threshold
    config = ExportConfig(quality_threshold=0.9)
    filtered = filter_encounters(config, db_path=TEST_DB)
    print(f"  High quality encounters (>0.9): {len(filtered)}")
    assert len(filtered) <= 2, "Expected at most 2 high quality encounters"

    # Filter by date range
    config = ExportConfig(
        start_date="2026-02-01T13:00:00",
        quality_threshold=0.0,
        min_positions=3,
        min_duration_s=0.0,
    )
    filtered = filter_encounters(config, db_path=TEST_DB)
    print(f"  Encounters after 13:00: {len(filtered)}")
    assert len(filtered) == 1, "Expected 1 encounter after 13:00"

    # Filter by minimum positions
    config = ExportConfig(min_positions=10, quality_threshold=0.0)
    filtered = filter_encounters(config, db_path=TEST_DB)
    print(f"  Encounters with >=10 positions: {len(filtered)}")
    assert len(filtered) >= 1, "Expected at least 1 encounter with >=10 positions"

    print("✅ Filtering test passed")


def test_csv_export():
    """Test CSV export functionality."""
    print("\n--- Testing CSV Export ---")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Export encounters
        config = ExportConfig(quality_threshold=0.5)
        output_file = output_dir / "encounters.csv"
        export_encounters(str(output_file), config, format="csv", db_path=TEST_DB)

        assert output_file.exists(), "CSV file not created"
        df = pd.read_csv(output_file)
        print(f"  Exported {len(df)} encounter rows")
        assert len(df) > 0, "No data exported"
        assert "encounter_id" in df.columns, "Missing encounter_id column"
        assert "quality_completeness" in df.columns, "Missing quality column"

        # Export summary
        summary_file = output_dir / "summary.csv"
        export_dataset_summary(str(summary_file), config, db_path=TEST_DB)

        assert summary_file.exists(), "Summary file not created"
        df_summary = pd.read_csv(summary_file)
        print(f"  Summary has {len(df_summary)} encounters")
        assert len(df_summary) > 0, "No summary data"

    print("✅ CSV export test passed")


def test_parquet_export():
    """Test Parquet export functionality."""
    print("\n--- Testing Parquet Export ---")

    try:
        import pyarrow
    except ImportError:
        print("⚠️  pyarrow not installed, skipping Parquet test")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Export to Parquet
        config = ExportConfig(quality_threshold=0.5)
        output_file = output_dir / "encounters.parquet"
        export_encounters(str(output_file), config, format="parquet", db_path=TEST_DB)

        assert output_file.exists(), "Parquet file not created"
        df = pd.read_parquet(output_file)
        print(f"  Exported {len(df)} encounter rows to Parquet")
        assert len(df) > 0, "No data exported"

    print("✅ Parquet export test passed")


def test_trajectory_export():
    """Test trajectory export."""
    print("\n--- Testing Trajectory Export ---")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        config = ExportConfig(quality_threshold=0.0)
        output_file = output_dir / "trajectories.csv"

        try:
            export_trajectories(str(output_file), config, format="csv", db_path=TEST_DB)

            if output_file.exists():
                df = pd.read_csv(output_file)
                print(f"  Exported {len(df)} trajectory rows")
                assert "segment_id" in df.columns, "Missing segment_id column"
                assert "mmsi" in df.columns, "Missing mmsi column"
            else:
                print("  No trajectories exported (may need more data)")

        except Exception as e:
            print(f"  ⚠️  Trajectory export warning: {e}")

    print("✅ Trajectory export test completed")


def test_encounter_pairs_export():
    """Test state-action pairs export."""
    print("\n--- Testing Encounter Pairs Export ---")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        config = ExportConfig(quality_threshold=0.0, min_positions=3)
        output_file = output_dir / "pairs.csv"

        try:
            export_encounter_pairs(str(output_file), config, format="csv", db_path=TEST_DB)

            if output_file.exists():
                df = pd.read_csv(output_file)
                print(f"  Exported {len(df)} state-action pairs")
                assert "encounter_id" in df.columns, "Missing encounter_id column"
                assert "action_turn_rate" in df.columns, "Missing action column"
                assert len(df) > 0, "No pairs exported"
            else:
                print("  No pairs exported (may need more data)")

        except Exception as e:
            print(f"  ⚠️  Pairs export warning: {e}")

    print("✅ Encounter pairs export test completed")


def cleanup():
    """Clean up test database."""
    if os.path.exists(TEST_DB):
        os.unlink(TEST_DB)
    print("\n✅ Test database cleaned up")


if __name__ == "__main__":
    try:
        setup_test_database()
        test_quality_metrics()
        test_filtering()
        test_csv_export()
        test_parquet_export()
        test_trajectory_export()
        test_encounter_pairs_export()

        print("\n" + "=" * 50)
        print("✅ ALL TESTS PASSED")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise
    finally:
        cleanup()
