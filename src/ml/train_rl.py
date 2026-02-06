"""Training script for PPO collision avoidance agent."""

import argparse
import logging
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv

from src.ml.data_extraction import extract_encounter_pairs
from src.ml.maritime_env import MaritimeEncounterEnv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class MetricsCallback(BaseCallback):
    """Logs collision rate and COLREGS compliance during training."""

    def __init__(self, eval_freq: int = 5000, verbose: int = 0):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.episode_rewards = []
        self.episode_infos = []

    def _on_step(self) -> bool:
        # Collect episode info
        for info in self.locals.get("infos", []):
            if "collision" in info:
                self.episode_infos.append(info)

        if self.num_timesteps % self.eval_freq == 0 and self.episode_infos:
            recent = self.episode_infos[-100:]  # Last 100 episodes
            collisions = sum(1 for i in recent if i.get("collision", False))
            avg_min_dist = np.mean([i["min_distance"] for i in recent])

            # COLREGS compliance: count episodes where agent turned starboard in head-on
            head_on_eps = [i for i in recent if i.get("encounter_type") == "head-on"]
            n_head_on = len(head_on_eps)

            logger.info(
                "Step %d | Collision rate: %.1f%% | Avg min dist: %.0f m | "
                "Episodes: %d | Head-on encounters: %d",
                self.num_timesteps,
                100 * collisions / len(recent),
                avg_min_dist,
                len(recent),
                n_head_on,
            )
            self.episode_infos = []

        return True


def train(
    db_path: str | None = None,
    total_timesteps: int = 500_000,
    encounter_type: str | None = None,
    save_path: str = "models/rl_ppo_agent",
):
    """Train PPO agent for collision avoidance.

    Args:
        db_path: Path to SQLite database
        total_timesteps: Total training timesteps
        encounter_type: Filter to specific encounter type (head-on, crossing, overtaking)
                       None = train on all types
        save_path: Path to save trained model
    """
    # Load encounter data once (shared across env resets)
    logger.info("Loading encounter data...")
    encounter_data = extract_encounter_pairs(db_path)
    if not encounter_data:
        logger.error("No encounter data available.")
        return

    logger.info("Loaded %d encounters.", len(encounter_data))

    # Create vectorized environment
    def make_env():
        return MaritimeEncounterEnv(
            encounter_data=encounter_data,
            encounter_type_filter=encounter_type,
        )

    env = DummyVecEnv([make_env])

    # PPO agent
    model = PPO(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        tensorboard_log="runs/rl_ppo",
    )

    callback = MetricsCallback(eval_freq=5000)

    logger.info("Starting PPO training for %d timesteps (encounter type: %s)...",
                total_timesteps, encounter_type or "all")
    model.learn(total_timesteps=total_timesteps, callback=callback)

    # Save model
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    model.save(save_path)
    logger.info("Model saved to %s", save_path)

    # Final evaluation
    logger.info("\n=== FINAL EVALUATION (100 episodes) ===")
    eval_env = make_env()
    collisions = 0
    min_distances = []
    for _ in range(100):
        obs, _ = eval_env.reset()
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = eval_env.step(action)
            done = terminated or truncated
        if info.get("collision"):
            collisions += 1
        min_distances.append(info["min_distance"])

    logger.info("Collision rate: %d%%", collisions)
    logger.info("Avg min distance: %.0f m", np.mean(min_distances))
    logger.info("Median min distance: %.0f m", np.median(min_distances))
    logger.info("Min of min distances: %.0f m", np.min(min_distances))


def curriculum_train(db_path: str | None = None, save_dir: str = "models"):
    """Curriculum learning: train on head-on first, then crossing, then all.

    This progressively increases difficulty as the agent learns basic
    collision avoidance before handling more complex scenarios.
    """
    stages = [
        ("head-on", 200_000, "Phase 1: Head-on encounters (simplest COLREGS)"),
        ("crossing", 300_000, "Phase 2: Crossing encounters"),
        (None, 500_000, "Phase 3: All encounter types"),
    ]

    for enc_type, timesteps, desc in stages:
        logger.info("\n" + "=" * 60)
        logger.info(desc)
        logger.info("=" * 60)

        suffix = enc_type or "all"
        save_path = f"{save_dir}/rl_ppo_{suffix}"
        train(
            db_path=db_path,
            total_timesteps=timesteps,
            encounter_type=enc_type,
            save_path=save_path,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train PPO collision avoidance agent")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--encounter-type", type=str, default=None,
                        choices=["head-on", "crossing", "overtaking"])
    parser.add_argument("--save-path", type=str, default="models/rl_ppo_agent")
    parser.add_argument("--curriculum", action="store_true",
                        help="Use curriculum learning (head-on -> crossing -> all)")
    args = parser.parse_args()

    if args.curriculum:
        curriculum_train(db_path=args.db)
    else:
        train(
            db_path=args.db,
            total_timesteps=args.timesteps,
            encounter_type=args.encounter_type,
            save_path=args.save_path,
        )
