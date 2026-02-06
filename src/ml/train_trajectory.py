"""Training script for LSTM trajectory prediction model."""

import argparse
import logging
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split

from src.ml.data_extraction import extract_trajectories, trajectories_to_features
from src.ml.trajectory_model import TrajectoryLSTM

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class TrajectoryDataset(Dataset):
    """Sliding window dataset over trajectory segments."""

    def __init__(self, feature_arrays: list[np.ndarray], input_len: int = 20,
                 pred_len: int = 20):
        self.input_len = input_len
        self.pred_len = pred_len
        self.total_len = input_len + pred_len

        # Build index of all valid windows
        self.windows = []
        for seg_idx, seg in enumerate(feature_arrays):
            if len(seg) >= self.total_len:
                for start in range(len(seg) - self.total_len + 1):
                    self.windows.append((seg_idx, start))

        self.feature_arrays = feature_arrays

    def __len__(self):
        return len(self.windows)

    def __getitem__(self, idx):
        seg_idx, start = self.windows[idx]
        seq = self.feature_arrays[seg_idx][start:start + self.total_len]

        x = torch.tensor(seq[:self.input_len], dtype=torch.float32)
        # Target: first 4 features (delta_x, delta_y, sog, cog)
        y = torch.tensor(seq[self.input_len:, :4], dtype=torch.float32)
        return x, y


def linear_extrapolation_baseline(x: torch.Tensor, pred_len: int) -> torch.Tensor:
    """Constant velocity baseline: repeat last velocity for pred_len steps.

    Args:
        x: Input sequence (batch, seq_len, features)
        pred_len: Number of steps to predict

    Returns:
        Predictions (batch, pred_len, 4)
    """
    # Last position and velocity
    last_pos = x[:, -1, :2]  # delta_x, delta_y
    velocity = x[:, -1, :2] - x[:, -2, :2]  # approx velocity
    last_sog = x[:, -1, 2:3]
    last_cog_sin = x[:, -1, 3:4]

    preds = []
    pos = last_pos.clone()
    for _ in range(pred_len):
        pos = pos + velocity
        pred = torch.cat([pos, last_sog, last_cog_sin], dim=1)
        preds.append(pred.unsqueeze(1))
    return torch.cat(preds, dim=1)


def compute_ade_fde(pred: torch.Tensor, target: torch.Tensor) -> tuple[float, float]:
    """Compute Average Displacement Error and Final Displacement Error.

    Both pred and target have shape (batch, pred_len, >=2) where first 2 dims are x, y.
    """
    displacement = torch.sqrt(
        (pred[:, :, 0] - target[:, :, 0]) ** 2 +
        (pred[:, :, 1] - target[:, :, 1]) ** 2
    )
    ade = displacement.mean().item()
    fde = displacement[:, -1].mean().item()
    return ade, fde


def train(
    db_path: str | None = None,
    epochs: int = 50,
    batch_size: int = 64,
    lr: float = 1e-3,
    input_len: int = 20,
    pred_len: int = 20,
    hidden_dim: int = 128,
    save_path: str = "models/trajectory_lstm.pt",
):
    """Train the trajectory prediction model."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Using device: %s", device)

    # Extract data
    logger.info("Extracting trajectories...")
    segments = extract_trajectories(db_path)
    if not segments:
        logger.error("No trajectory segments found. Run the data collector first.")
        return

    feature_arrays = trajectories_to_features(segments)
    logger.info("Got %d feature arrays.", len(feature_arrays))

    # Create dataset
    dataset = TrajectoryDataset(feature_arrays, input_len=input_len, pred_len=pred_len)
    logger.info("Dataset has %d windows.", len(dataset))

    if len(dataset) < 10:
        logger.error("Not enough data windows. Need more trajectory data.")
        return

    # Split: 80% train, 10% val, 10% test
    n = len(dataset)
    n_train = int(0.8 * n)
    n_val = int(0.1 * n)
    n_test = n - n_train - n_val
    train_ds, val_ds, test_ds = random_split(dataset, [n_train, n_val, n_test])

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)
    test_loader = DataLoader(test_ds, batch_size=batch_size)

    # Model
    model = TrajectoryLSTM(
        hidden_dim=hidden_dim,
        pred_len=pred_len,
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    criterion = nn.MSELoss()

    # Training loop
    best_val_loss = float("inf")
    for epoch in range(epochs):
        # Teacher forcing ratio: decay from 1.0 to 0.0
        tf_ratio = max(0.0, 1.0 - epoch / (epochs * 0.7))

        # Train
        model.train()
        train_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            pred = model(x, teacher_forcing_ratio=tf_ratio, target=y)
            loss = criterion(pred, y)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * x.size(0)
        train_loss /= len(train_ds)

        # Validate
        model.eval()
        val_loss = 0.0
        val_ade, val_fde = 0.0, 0.0
        n_val_batches = 0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                pred = model(x)
                val_loss += criterion(pred, y).item() * x.size(0)
                ade, fde = compute_ade_fde(pred, y)
                val_ade += ade
                val_fde += fde
                n_val_batches += 1
        val_loss /= len(val_ds)
        val_ade /= n_val_batches
        val_fde /= n_val_batches

        scheduler.step(val_loss)

        logger.info(
            "Epoch %d/%d | Train Loss: %.6f | Val Loss: %.6f | "
            "Val ADE: %.2f m | Val FDE: %.2f m | TF: %.2f",
            epoch + 1, epochs, train_loss, val_loss, val_ade, val_fde, tf_ratio,
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), save_path)
            logger.info("Saved best model (val_loss=%.6f)", val_loss)

    # Test evaluation
    model.load_state_dict(torch.load(save_path, weights_only=True))
    model.eval()
    test_ade, test_fde = 0.0, 0.0
    baseline_ade, baseline_fde = 0.0, 0.0
    n_test_batches = 0
    with torch.no_grad():
        for x, y in test_loader:
            x, y = x.to(device), y.to(device)
            pred = model(x)
            ade, fde = compute_ade_fde(pred, y)
            test_ade += ade
            test_fde += fde

            # Baseline
            bl_pred = linear_extrapolation_baseline(x, pred_len).to(device)
            bl_ade, bl_fde = compute_ade_fde(bl_pred, y)
            baseline_ade += bl_ade
            baseline_fde += bl_fde
            n_test_batches += 1

    test_ade /= n_test_batches
    test_fde /= n_test_batches
    baseline_ade /= n_test_batches
    baseline_fde /= n_test_batches

    logger.info("=== TEST RESULTS ===")
    logger.info("LSTM  - ADE: %.2f m | FDE: %.2f m", test_ade, test_fde)
    logger.info("Baseline - ADE: %.2f m | FDE: %.2f m", baseline_ade, baseline_fde)
    logger.info("Improvement - ADE: %.1f%% | FDE: %.1f%%",
                (1 - test_ade / baseline_ade) * 100 if baseline_ade > 0 else 0,
                (1 - test_fde / baseline_fde) * 100 if baseline_fde > 0 else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train trajectory prediction LSTM")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--input-len", type=int, default=20)
    parser.add_argument("--pred-len", type=int, default=20)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--save-path", type=str, default="models/trajectory_lstm.pt")
    args = parser.parse_args()

    train(
        db_path=args.db,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        input_len=args.input_len,
        pred_len=args.pred_len,
        hidden_dim=args.hidden_dim,
        save_path=args.save_path,
    )
