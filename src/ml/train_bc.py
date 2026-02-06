"""Training script for behavioral cloning maneuver policy."""

import argparse
import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split

from src.ml.data_extraction import extract_encounter_pairs
from src.ml.behavioral_cloning import ManeuverPolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class ManeuverDataset(Dataset):
    """State-action pairs from encounter trajectories."""

    def __init__(self, pairs: list[dict]):
        self.states = []
        self.actions = []

        for pair in pairs:
            # Vessel A state-action pairs (skip first state which has no action)
            for i in range(len(pair["actions_a"])):
                self.states.append(pair["states_a"][i + 1])  # state after action
                self.actions.append(pair["actions_a"][i])

            # Vessel B state-action pairs
            for i in range(len(pair["actions_b"])):
                self.states.append(pair["states_b"][i + 1])
                self.actions.append(pair["actions_b"][i])

        self.states = np.array(self.states, dtype=np.float32)
        self.actions = np.array(self.actions, dtype=np.float32)

        # Normalize features for better training
        self.state_mean = self.states.mean(axis=0)
        self.state_std = self.states.std(axis=0) + 1e-8
        self.states_norm = (self.states - self.state_mean) / self.state_std

    def __len__(self):
        return len(self.states)

    def __getitem__(self, idx):
        return (
            torch.tensor(self.states_norm[idx], dtype=torch.float32),
            torch.tensor(self.actions[idx], dtype=torch.float32),
        )


def train(
    db_path: str | None = None,
    epochs: int = 100,
    batch_size: int = 128,
    lr: float = 1e-3,
    save_path: str = "models/bc_policy.pt",
):
    """Train behavioral cloning policy."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Using device: %s", device)

    # Extract data
    logger.info("Extracting encounter pairs...")
    pairs = extract_encounter_pairs(db_path)
    if not pairs:
        logger.error("No encounter pairs found.")
        return

    logger.info("Got %d encounters.", len(pairs))

    # Split encounters (not individual samples) into train/val
    np.random.seed(42)
    indices = np.random.permutation(len(pairs))
    split = int(0.8 * len(pairs))
    train_pairs = [pairs[i] for i in indices[:split]]
    val_pairs = [pairs[i] for i in indices[split:]]

    train_ds = ManeuverDataset(train_pairs)
    val_ds = ManeuverDataset(val_pairs)

    # Use training set normalization stats for validation
    val_ds.state_mean = train_ds.state_mean
    val_ds.state_std = train_ds.state_std
    val_ds.states_norm = (val_ds.states - val_ds.state_mean) / val_ds.state_std

    logger.info("Train: %d samples, Val: %d samples", len(train_ds), len(val_ds))

    if len(train_ds) < 10:
        logger.error("Not enough training samples.")
        return

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)

    # Model
    model = ManeuverPolicy().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)
    criterion = nn.MSELoss()

    best_val_loss = float("inf")
    for epoch in range(epochs):
        # Train
        model.train()
        train_loss = 0.0
        for states, actions in train_loader:
            states, actions = states.to(device), actions.to(device)
            pred = model(states)
            loss = criterion(pred, actions)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * states.size(0)
        train_loss /= len(train_ds)

        # Validate
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for states, actions in val_loader:
                states, actions = states.to(device), actions.to(device)
                pred = model(states)
                val_loss += criterion(pred, actions).item() * states.size(0)
        val_loss /= len(val_ds)

        scheduler.step(val_loss)

        if (epoch + 1) % 10 == 0 or val_loss < best_val_loss:
            logger.info("Epoch %d/%d | Train Loss: %.6f | Val Loss: %.6f",
                        epoch + 1, epochs, train_loss, val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "model_state_dict": model.state_dict(),
                "state_mean": train_ds.state_mean,
                "state_std": train_ds.state_std,
            }, save_path)

    logger.info("Best val loss: %.6f", best_val_loss)
    logger.info("Model saved to %s", save_path)

    # Report action statistics
    logger.info("\n=== ACTION STATISTICS ===")
    logger.info("Turn rate (deg/s) - mean: %.4f, std: %.4f",
                train_ds.actions[:, 0].mean(), train_ds.actions[:, 0].std())
    logger.info("Accel rate (kn/s) - mean: %.4f, std: %.4f",
                train_ds.actions[:, 1].mean(), train_ds.actions[:, 1].std())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train behavioral cloning policy")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--save-path", type=str, default="models/bc_policy.pt")
    args = parser.parse_args()

    train(db_path=args.db, epochs=args.epochs, batch_size=args.batch_size,
          lr=args.lr, save_path=args.save_path)
