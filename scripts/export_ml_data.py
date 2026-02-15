#!/usr/bin/env python3
"""CLI tool for exporting ML training datasets from the encounter database.

Usage:
    python scripts/export_ml_data.py trajectories output/trajectories.csv
    python scripts/export_ml_data.py encounters output/encounters.parquet --format parquet
    python scripts/export_ml_data.py pairs output/pairs.csv --type crossing --quality 0.8
    python scripts/export_ml_data.py summary output/summary.csv --start 2026-01-01 --end 2026-12-31
"""

import argparse
import logging
import sys
from pathlib import Path

from src.ml.data_export import (
    ExportConfig,
    export_trajectories,
    export_encounters,
    export_encounter_pairs,
    export_dataset_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Export ML training datasets from encounter database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export all trajectories to CSV
  python scripts/export_ml_data.py trajectories output/trajectories.csv

  # Export high-quality encounters to Parquet
  python scripts/export_ml_data.py encounters output/encounters.parquet \\
      --format parquet --quality 0.9 --min-positions 20

  # Export crossing encounters from Q1 2026
  python scripts/export_ml_data.py pairs output/crossing_q1.csv \\
      --type crossing --start 2026-01-01 --end 2026-03-31

  # Generate dataset summary with quality metrics
  python scripts/export_ml_data.py summary output/summary.csv \\
      --quality 0.7 --min-duration 120

Export types:
  trajectories  - Trajectory segments for LSTM training
  encounters    - Encounter features for risk classification
  pairs         - State-action pairs for behavioral cloning/RL
  summary       - Dataset summary with quality metrics
        """,
    )

    parser.add_argument(
        "export_type",
        choices=["trajectories", "encounters", "pairs", "summary"],
        help="Type of data to export",
    )
    parser.add_argument(
        "output", type=str, help="Output file path (CSV or Parquet)"
    )

    # Format options
    parser.add_argument(
        "--format",
        choices=["csv", "parquet"],
        default="csv",
        help="Output format (default: csv)",
    )

    # Filtering options
    parser.add_argument(
        "--type",
        "--encounter-type",
        dest="encounter_types",
        action="append",
        choices=["head-on", "crossing", "overtaking"],
        help="Filter by encounter type (can be specified multiple times)",
    )
    parser.add_argument(
        "--start",
        "--start-date",
        dest="start_date",
        type=str,
        help="Start date filter (ISO format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        "--end-date",
        dest="end_date",
        type=str,
        help="End date filter (ISO format: YYYY-MM-DD)",
    )

    # Quality options
    parser.add_argument(
        "--quality",
        "--quality-threshold",
        dest="quality_threshold",
        type=float,
        default=0.7,
        help="Minimum quality threshold (0.0-1.0, default: 0.7)",
    )
    parser.add_argument(
        "--min-positions",
        dest="min_positions",
        type=int,
        default=10,
        help="Minimum positions per encounter (default: 10)",
    )
    parser.add_argument(
        "--min-duration",
        dest="min_duration_s",
        type=float,
        default=60.0,
        help="Minimum encounter duration in seconds (default: 60)",
    )

    # Database options
    parser.add_argument(
        "--db", "--db-path", dest="db_path", type=str, help="Database path (optional)"
    )

    # Dataset splitting (future enhancement)
    parser.add_argument(
        "--split",
        action="store_true",
        help="Split dataset into train/val/test (80/10/10)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for splitting (default: 42)"
    )

    args = parser.parse_args()

    # Validate output path
    output_path = Path(args.output)
    if args.format == "parquet" and not str(output_path).endswith(".parquet"):
        logger.warning(
            "Output file extension doesn't match format. Consider using .parquet extension."
        )

    # Build export config
    config = ExportConfig(
        encounter_types=args.encounter_types,
        start_date=args.start_date,
        end_date=args.end_date,
        min_positions=args.min_positions,
        min_duration_s=args.min_duration_s,
        quality_threshold=args.quality_threshold,
    )

    # Log configuration
    logger.info("Export configuration:")
    logger.info("  Type: %s", args.export_type)
    logger.info("  Output: %s", args.output)
    logger.info("  Format: %s", args.format)
    if config.encounter_types:
        logger.info("  Encounter types: %s", ", ".join(config.encounter_types))
    if config.start_date:
        logger.info("  Start date: %s", config.start_date)
    if config.end_date:
        logger.info("  End date: %s", config.end_date)
    logger.info("  Quality threshold: %.2f", config.quality_threshold)
    logger.info("  Min positions: %d", config.min_positions)
    logger.info("  Min duration: %.1fs", config.min_duration_s)

    # Execute export
    try:
        if args.export_type == "trajectories":
            export_trajectories(
                args.output, config, format=args.format, db_path=args.db_path
            )
        elif args.export_type == "encounters":
            export_encounters(
                args.output, config, format=args.format, db_path=args.db_path
            )
        elif args.export_type == "pairs":
            export_encounter_pairs(
                args.output, config, format=args.format, db_path=args.db_path
            )
        elif args.export_type == "summary":
            export_dataset_summary(args.output, config, db_path=args.db_path)

        logger.info("✅ Export completed successfully!")

        # Handle dataset splitting if requested
        if args.split:
            logger.info("Splitting dataset into train/val/test...")
            split_dataset(args.output, args.format, args.seed)

    except Exception as e:
        logger.error("❌ Export failed: %s", e, exc_info=True)
        sys.exit(1)


def split_dataset(file_path: str, format: str, seed: int = 42):
    """Split dataset into train/val/test sets (80/10/10).

    Args:
        file_path: Path to the dataset file
        format: File format (csv or parquet)
        seed: Random seed for reproducibility
    """
    import pandas as pd
    import numpy as np

    # Load dataset
    if format == "csv":
        df = pd.read_csv(file_path)
    elif format == "parquet":
        df = pd.read_parquet(file_path)
    else:
        raise ValueError(f"Unsupported format: {format}")

    # Shuffle and split
    np.random.seed(seed)
    indices = np.random.permutation(len(df))

    n_train = int(0.8 * len(df))
    n_val = int(0.1 * len(df))

    train_idx = indices[:n_train]
    val_idx = indices[n_train : n_train + n_val]
    test_idx = indices[n_train + n_val :]

    train_df = df.iloc[train_idx]
    val_df = df.iloc[val_idx]
    test_df = df.iloc[test_idx]

    # Save splits
    base_path = Path(file_path)
    ext = base_path.suffix
    stem = base_path.stem

    for split_name, split_df in [
        ("train", train_df),
        ("val", val_df),
        ("test", test_df),
    ]:
        split_path = base_path.parent / f"{stem}_{split_name}{ext}"
        if format == "csv":
            split_df.to_csv(split_path, index=False)
        elif format == "parquet":
            split_df.to_parquet(split_path, index=False)
        logger.info("  %s: %d rows -> %s", split_name, len(split_df), split_path)

    logger.info("✅ Dataset split completed!")


if __name__ == "__main__":
    main()
