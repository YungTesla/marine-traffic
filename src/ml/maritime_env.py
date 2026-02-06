"""Gymnasium environment for maritime collision avoidance RL training.

Replays real encounters from the database: the RL agent controls vessel A,
while vessel B follows its recorded trajectory.
"""

import math
import random
import logging

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from src.ml.data_extraction import extract_encounter_pairs
from src.encounter_detector import haversine, compute_cpa_tcpa, classify_encounter

logger = logging.getLogger(__name__)

# Ship dynamics constants
KNOTS_TO_MS = 0.514444
MAX_RUDDER_DEG = 35.0
RUDDER_TO_HEADING_RATE = 0.3  # deg/s per deg of rudder (simplified)
MAX_SPEED_KN = 25.0
DT = 10.0  # simulation timestep in seconds
M_PER_DEG_LAT = 111_320.0

# Action definitions (discrete)
ACTIONS = {
    0: ("hard_port", -MAX_RUDDER_DEG, 0.0),
    1: ("port", -15.0, 0.0),
    2: ("slight_port", -5.0, 0.0),
    3: ("steady", 0.0, 0.0),
    4: ("slight_stbd", 5.0, 0.0),
    5: ("stbd", 15.0, 0.0),
    6: ("hard_stbd", MAX_RUDDER_DEG, 0.0),
    7: ("speed_up", 0.0, 1.0),
    8: ("slow_down", 0.0, -1.0),
}


class MaritimeEncounterEnv(gym.Env):
    """RL environment for ship collision avoidance.

    Observation (17D):
        Own ship: x, y, sog, cog_sin, cog_cos, heading_sin, heading_cos (7)
        Target relative: rel_x, rel_y, rel_sog, rel_cog_sin, rel_cog_cos (5)
        Situation: distance_m, bearing, cpa_m, tcpa_s, encounter_type_idx (5)

    Action (Discrete 9):
        0-6: rudder commands (hard port to hard starboard)
        7: speed up, 8: slow down
    """

    metadata = {"render_modes": ["human"]}

    def __init__(self, encounter_data: list[dict] | None = None,
                 db_path: str | None = None,
                 max_steps: int = 200,
                 collision_dist: float = 200.0,
                 encounter_type_filter: str | None = None):
        super().__init__()

        self.max_steps = max_steps
        self.collision_dist = collision_dist
        self.encounter_type_filter = encounter_type_filter

        # Load encounter data
        if encounter_data is not None:
            self.encounters = encounter_data
        else:
            self.encounters = extract_encounter_pairs(db_path)
            if not self.encounters:
                raise RuntimeError("No encounter data available. Run data collector first.")

        # Filter by encounter type if specified
        if self.encounter_type_filter:
            self.encounters = [e for e in self.encounters
                               if e["encounter_type"] == self.encounter_type_filter]
            if not self.encounters:
                raise RuntimeError(f"No encounters of type '{encounter_type_filter}' found.")

        logger.info("Maritime env loaded with %d encounters.", len(self.encounters))

        # Spaces
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf,
                                            shape=(17,), dtype=np.float32)
        self.action_space = spaces.Discrete(9)

        # State
        self.own_lat = 0.0
        self.own_lon = 0.0
        self.own_sog = 0.0
        self.own_cog = 0.0
        self.own_heading = 0.0
        self.own_rudder = 0.0
        self.target_trajectory = None
        self.target_step = 0
        self.encounter_type = "crossing"
        self.step_count = 0
        self.prev_distance = 0.0
        self.min_distance = float("inf")
        self.prev_rudder = 0.0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        # Pick random encounter
        enc = random.choice(self.encounters)
        self.encounter_type = enc["encounter_type"]

        # Initialize own ship from vessel A start position
        # states_a[0] = [sog, cog_sin, cog_cos, heading_sin, heading_cos, ship_type, length,
        #                 rel_x, rel_y, ..., distance, bearing, cpa, tcpa, ...]
        # We need original positions - reconstruct from states
        states_a = enc["states_a"]
        states_b = enc["states_b"]

        if len(states_a) < 2 or len(states_b) < 2:
            return self.reset(seed=seed)

        # Use the state vectors to initialize
        # Own ship: start at (0, 0), use SOG and COG from first state
        self.own_sog = float(states_a[0, 0])  # sog
        own_cog_sin, own_cog_cos = float(states_a[0, 1]), float(states_a[0, 2])
        self.own_cog = math.degrees(math.atan2(own_cog_sin, own_cog_cos)) % 360
        self.own_heading = self.own_cog
        self.own_lat = 0.0
        self.own_lon = 0.0
        self.own_rudder = 0.0

        # Target trajectory: relative positions from states (rel_x, rel_y at indices 7, 8)
        # Store as sequence of (lat_offset, lon_offset, sog, cog) in local coords
        self.target_trajectory = []
        for i in range(len(states_a)):
            rel_x = float(states_a[i, 7])  # meters east
            rel_y = float(states_a[i, 8])  # meters north
            target_sog = self.own_sog + float(states_a[i, 9])  # rel_sog + own_sog
            target_cog_sin = float(states_a[i, 10])
            target_cog_cos = float(states_a[i, 11])
            target_cog = (self.own_cog + math.degrees(
                math.atan2(target_cog_sin, target_cog_cos))) % 360
            self.target_trajectory.append({
                "rel_x": rel_x, "rel_y": rel_y,
                "sog": max(0, target_sog), "cog": target_cog,
            })

        self.target_step = 0
        self.step_count = 0
        self.prev_distance = float(states_a[0, 12])  # distance_m
        self.min_distance = self.prev_distance
        self.prev_rudder = 0.0

        obs = self._get_obs()
        return obs, {}

    def step(self, action: int):
        self.step_count += 1
        action_name, rudder_cmd, speed_cmd = ACTIONS[action]

        # Apply rudder command (simple first-order response)
        self.own_rudder = np.clip(rudder_cmd, -MAX_RUDDER_DEG, MAX_RUDDER_DEG)
        heading_rate = self.own_rudder * RUDDER_TO_HEADING_RATE  # deg/s
        self.own_heading = (self.own_heading + heading_rate * DT) % 360
        self.own_cog = self.own_heading  # simplified: COG = heading

        # Apply speed command
        self.own_sog = np.clip(self.own_sog + speed_cmd * 0.5, 0.0, MAX_SPEED_KN)

        # Update own position
        speed_ms = self.own_sog * KNOTS_TO_MS
        dx = speed_ms * math.sin(math.radians(self.own_cog)) * DT
        dy = speed_ms * math.cos(math.radians(self.own_cog)) * DT
        mid_lat = math.radians(self.own_lat)
        m_per_deg_lon = M_PER_DEG_LAT * math.cos(mid_lat) if abs(mid_lat) < math.pi / 2 else M_PER_DEG_LAT
        self.own_lon += dx / m_per_deg_lon if m_per_deg_lon > 0 else 0
        self.own_lat += dy / M_PER_DEG_LAT

        # Advance target
        self.target_step = min(self.target_step + 1, len(self.target_trajectory) - 1)

        # Compute current situation
        target = self.target_trajectory[self.target_step]
        # Target position in absolute coords (relative to own)
        target_lat = self.own_lat + target["rel_y"] / M_PER_DEG_LAT
        target_lon = self.own_lon + target["rel_x"] / (M_PER_DEG_LAT * math.cos(math.radians(self.own_lat)))

        distance = haversine(self.own_lat, self.own_lon, target_lat, target_lon)
        self.min_distance = min(self.min_distance, distance)

        # Compute reward
        reward = self._compute_reward(distance, action)

        # Check termination
        terminated = False
        truncated = False

        if distance < self.collision_dist:
            reward -= 100.0
            terminated = True
        elif self.step_count > 5 and distance > self.prev_distance and self.min_distance < 3000:
            # Successfully passed (distance increasing after close approach)
            reward += 10.0
            terminated = True
        elif self.step_count >= self.max_steps:
            truncated = True
        elif self.target_step >= len(self.target_trajectory) - 1:
            truncated = True

        self.prev_distance = distance
        self.prev_rudder = self.own_rudder

        obs = self._get_obs()
        info = {
            "distance": distance,
            "min_distance": self.min_distance,
            "encounter_type": self.encounter_type,
            "collision": distance < self.collision_dist,
        }

        return obs, reward, terminated, truncated, info

    def _compute_reward(self, distance: float, action: int) -> float:
        reward = 0.0

        # 1. Safety: exponential penalty for proximity
        if distance < 500:
            reward -= 10.0 * math.exp(-distance / 200)

        # 2. COLREGS compliance
        _, rudder_cmd, _ = ACTIONS[action]
        if self.encounter_type == "head-on":
            # Rule 14: alter course to starboard
            if rudder_cmd > 0:
                reward += 2.0
            elif rudder_cmd < -5:
                reward -= 5.0
        elif self.encounter_type == "crossing":
            # Rule 15: give-way vessel turns starboard
            if rudder_cmd > 0:
                reward += 1.0
            elif rudder_cmd < -5:
                reward -= 3.0

        # 3. Efficiency: penalize unnecessary maneuvers
        if rudder_cmd != 0:
            reward -= 0.05 * abs(rudder_cmd) / MAX_RUDDER_DEG

        # 4. Smoothness: penalize oscillation
        if (self.own_rudder > 0 and self.prev_rudder < 0) or \
           (self.own_rudder < 0 and self.prev_rudder > 0):
            reward -= 1.0

        # 5. Small time penalty to encourage efficiency
        reward -= 0.1

        return reward

    def _get_obs(self) -> np.ndarray:
        target = self.target_trajectory[self.target_step]

        cog_sin = math.sin(math.radians(self.own_cog))
        cog_cos = math.cos(math.radians(self.own_cog))
        h_sin = math.sin(math.radians(self.own_heading))
        h_cos = math.cos(math.radians(self.own_heading))

        # Target relative
        rel_x = target["rel_x"]
        rel_y = target["rel_y"]
        rel_sog = target["sog"] - self.own_sog
        dcog = math.radians(target["cog"] - self.own_cog)
        rel_cog_sin = math.sin(dcog)
        rel_cog_cos = math.cos(dcog)

        # Situation
        distance = math.sqrt(rel_x ** 2 + rel_y ** 2)
        bearing = math.degrees(math.atan2(rel_x, rel_y)) % 360

        # CPA/TCPA
        target_lat = self.own_lat + rel_y / M_PER_DEG_LAT
        m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(self.own_lat))
        target_lon = self.own_lon + rel_x / m_per_deg_lon if m_per_deg_lon > 0 else self.own_lon
        cpa, tcpa = compute_cpa_tcpa(
            self.own_lat, self.own_lon, self.own_sog, self.own_cog,
            target_lat, target_lon, target["sog"], target["cog"],
        )

        # Encounter type as index
        type_map = {"head-on": 0, "crossing": 1, "overtaking": 2}
        enc_type_idx = float(type_map.get(self.encounter_type, 1))

        return np.array([
            self.own_lat, self.own_lon, self.own_sog, cog_sin, cog_cos, h_sin, h_cos,
            rel_x, rel_y, rel_sog, rel_cog_sin, rel_cog_cos,
            distance, bearing, cpa, tcpa, enc_type_idx,
        ], dtype=np.float32)
