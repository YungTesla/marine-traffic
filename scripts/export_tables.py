#!/usr/bin/env python3
"""Export alle database tabellen als raw CSV bestanden."""

import csv
import os
import sqlite3
import sys

TABLES = ["vessels", "positions", "encounters", "encounter_positions", "water_levels"]


def export_all(db_path: str, output_dir: str):
    conn = sqlite3.connect(db_path)
    for table in TABLES:
        cursor = conn.execute(f"SELECT * FROM {table}")  # noqa: S608 - hardcoded table names
        columns = [desc[0] for desc in cursor.description]
        output_path = os.path.join(output_dir, f"{table}.csv")
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(cursor)
        row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
        print(f"  {table}: {row_count} rows -> {output_path}")
    conn.close()


if __name__ == "__main__":
    db_path = os.environ.get("DB_PATH", "/data/encounters.db")
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "/output"
    os.makedirs(output_dir, exist_ok=True)
    print("Exporting tables...")
    export_all(db_path, output_dir)
    print("Done.")
