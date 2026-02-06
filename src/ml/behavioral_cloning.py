"""MLP model for behavioral cloning of ship captain maneuver decisions."""

import torch
import torch.nn as nn


class ManeuverPolicy(nn.Module):
    """MLP that predicts captain actions (turn_rate, accel_rate) from state.

    Input (19 features):
        Own ship: sog, cog_sin, cog_cos, heading_sin, heading_cos, ship_type, length
        Other relative: rel_x, rel_y, rel_sog, rel_cog_sin, rel_cog_cos
        Situation: distance_m, bearing, cpa_m, tcpa_s, type_head_on, type_crossing, type_overtaking

    Output (2):
        turn_rate (deg/s), accel_rate (knots/s)
    """

    def __init__(self, input_dim: int = 19, hidden_dims: tuple[int, ...] = (256, 128)):
        super().__init__()
        layers = []
        prev_dim = input_dim
        for h in hidden_dims:
            layers.extend([nn.Linear(prev_dim, h), nn.ReLU()])
            prev_dim = h
        layers.append(nn.Linear(prev_dim, 2))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Predict action from state. Input: (batch, 19), Output: (batch, 2)."""
        return self.net(x)
