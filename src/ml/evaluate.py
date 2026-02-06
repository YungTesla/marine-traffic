"""Evaluation and visualization utilities for all ML models."""

import argparse
import logging
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def plot_trajectory_predictions(model_path: str, db_path: str | None = None,
                                 n_samples: int = 5, output_dir: str = "plots"):
    """Plot predicted vs actual trajectories on a map."""
    import torch
    from src.ml.trajectory_model import TrajectoryLSTM
    from src.ml.data_extraction import extract_trajectories, trajectories_to_features
    from src.ml.train_trajectory import TrajectoryDataset

    device = torch.device("cpu")
    model = TrajectoryLSTM()
    model.load_state_dict(torch.load(model_path, weights_only=True, map_location=device))
    model.eval()

    segments = extract_trajectories(db_path)
    features = trajectories_to_features(segments)
    dataset = TrajectoryDataset(features)

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    indices = np.random.choice(len(dataset), min(n_samples, len(dataset)), replace=False)
    for idx in indices:
        x, y_true = dataset[idx]
        with torch.no_grad():
            y_pred = model(x.unsqueeze(0)).squeeze(0).numpy()
        y_true = y_true.numpy()

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # XY plot
        ax = axes[0]
        ax.plot(x[:, 0], x[:, 1], "b.-", label="Input", alpha=0.5)
        ax.plot(y_true[:, 0], y_true[:, 1], "g.-", label="Ground Truth")
        ax.plot(y_pred[:, 0], y_pred[:, 1], "r.--", label="Predicted")
        ax.set_xlabel("delta_x (m)")
        ax.set_ylabel("delta_y (m)")
        ax.legend()
        ax.set_title(f"Trajectory #{idx}")
        ax.set_aspect("equal")

        # Speed plot
        ax = axes[1]
        t_input = np.arange(len(x))
        t_pred = np.arange(len(x), len(x) + len(y_true))
        ax.plot(t_input, x[:, 2], "b.-", label="Input SOG")
        ax.plot(t_pred, y_true[:, 2], "g.-", label="True SOG")
        ax.plot(t_pred, y_pred[:, 2], "r.--", label="Pred SOG")
        ax.set_xlabel("Timestep")
        ax.set_ylabel("SOG (knots)")
        ax.legend()
        ax.set_title("Speed Over Ground")

        plt.tight_layout()
        plt.savefig(f"{output_dir}/trajectory_{idx}.png", dpi=150)
        plt.close()
        logger.info("Saved trajectory plot: %s/trajectory_%d.png", output_dir, idx)


def plot_encounter_map(db_path: str | None = None, output_path: str = "plots/encounters_map.html"):
    """Plot all encounters on an interactive Folium map."""
    try:
        import folium
    except ImportError:
        logger.error("Install 'folium' for map visualization: pip install folium")
        return

    import sqlite3
    from src.config import DB_PATH

    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row

    encounters = conn.execute(
        "SELECT * FROM encounters WHERE end_time IS NOT NULL LIMIT 200"
    ).fetchall()

    if not encounters:
        logger.warning("No encounters to plot.")
        conn.close()
        return

    # Center map on first encounter's position
    first_pos = conn.execute(
        "SELECT lat, lon FROM encounter_positions WHERE encounter_id = ? LIMIT 1",
        (encounters[0]["id"],),
    ).fetchone()

    center = [first_pos["lat"], first_pos["lon"]] if first_pos else [52.0, 4.0]
    m = folium.Map(location=center, zoom_start=8)

    color_map = {"head-on": "red", "crossing": "orange", "overtaking": "blue"}

    for enc in encounters:
        positions = conn.execute(
            "SELECT * FROM encounter_positions WHERE encounter_id = ? ORDER BY mmsi, timestamp",
            (enc["id"],),
        ).fetchall()

        if not positions:
            continue

        # Group by vessel
        vessels = {}
        for pos in positions:
            mmsi = pos["mmsi"]
            if mmsi not in vessels:
                vessels[mmsi] = []
            vessels[mmsi].append([pos["lat"], pos["lon"]])

        color = color_map.get(enc["encounter_type"], "gray")

        for mmsi, coords in vessels.items():
            if len(coords) >= 2:
                folium.PolyLine(
                    coords,
                    weight=2,
                    color=color,
                    opacity=0.7,
                    popup=f"Encounter {enc['id']}: {enc['encounter_type']}<br>"
                          f"Min dist: {enc['min_distance_m']:.0f}m<br>"
                          f"MMSI: {mmsi}",
                ).add_to(m)

        # Mark encounter point (midpoint)
        all_lats = [p["lat"] for p in positions]
        all_lons = [p["lon"] for p in positions]
        folium.CircleMarker(
            [np.mean(all_lats), np.mean(all_lons)],
            radius=4,
            color=color,
            fill=True,
            popup=f"Enc #{enc['id']}: {enc['encounter_type']}, "
                  f"CPA={enc['cpa_m']:.0f}m",
        ).add_to(m)

    conn.close()

    # Add legend
    legend_html = """
    <div style="position: fixed; bottom: 50px; left: 50px; z-index: 1000;
                background-color: white; padding: 10px; border: 2px solid grey;
                border-radius: 5px; font-size: 14px;">
        <b>Encounter Types</b><br>
        <span style="color: red;">&#9679;</span> Head-on<br>
        <span style="color: orange;">&#9679;</span> Crossing<br>
        <span style="color: blue;">&#9679;</span> Overtaking
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    m.save(output_path)
    logger.info("Encounter map saved to %s", output_path)


def data_summary(db_path: str | None = None):
    """Print summary statistics of the collected data."""
    import sqlite3
    from src.config import DB_PATH

    conn = sqlite3.connect(db_path or DB_PATH)

    counts = {
        "vessels": conn.execute("SELECT COUNT(*) FROM vessels").fetchone()[0],
        "positions": conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
        "encounters": conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0],
        "completed_encounters": conn.execute(
            "SELECT COUNT(*) FROM encounters WHERE end_time IS NOT NULL"
        ).fetchone()[0],
        "encounter_positions": conn.execute(
            "SELECT COUNT(*) FROM encounter_positions"
        ).fetchone()[0],
    }

    logger.info("\n=== DATA SUMMARY ===")
    for name, count in counts.items():
        logger.info("  %s: %d", name, count)

    # Encounter type distribution
    types = conn.execute(
        "SELECT encounter_type, COUNT(*) as cnt FROM encounters "
        "WHERE end_time IS NOT NULL GROUP BY encounter_type"
    ).fetchall()
    logger.info("\nEncounter types:")
    for t in types:
        logger.info("  %s: %d", t[0], t[1])

    # Distance distribution
    distances = conn.execute(
        "SELECT min_distance_m FROM encounters WHERE end_time IS NOT NULL AND min_distance_m IS NOT NULL"
    ).fetchall()
    if distances:
        dists = [d[0] for d in distances]
        logger.info("\nMin distance stats:")
        logger.info("  Mean: %.0f m", np.mean(dists))
        logger.info("  Median: %.0f m", np.median(dists))
        logger.info("  Min: %.0f m", np.min(dists))
        logger.info("  Max: %.0f m", np.max(dists))
        logger.info("  < 500m (HIGH risk): %d (%.1f%%)",
                     sum(1 for d in dists if d < 500),
                     100 * sum(1 for d in dists if d < 500) / len(dists))

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate ML models and visualize data")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("summary", help="Print data summary statistics")

    map_parser = sub.add_parser("map", help="Generate encounter map")
    map_parser.add_argument("--output", type=str, default="plots/encounters_map.html")

    traj_parser = sub.add_parser("trajectory", help="Plot trajectory predictions")
    traj_parser.add_argument("--model", type=str, required=True, help="Path to model file")
    traj_parser.add_argument("--samples", type=int, default=5)
    traj_parser.add_argument("--output-dir", type=str, default="plots")

    args = parser.parse_args()

    if args.command == "summary":
        data_summary(args.db)
    elif args.command == "map":
        plot_encounter_map(args.db, args.output)
    elif args.command == "trajectory":
        plot_trajectory_predictions(args.model, args.db, args.samples, args.output_dir)
    else:
        parser.print_help()
