"""XGBoost risk classifier for ship encounters."""

import logging

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "min_distance_m", "cpa_m", "tcpa_s",
    "type_head_on", "type_crossing", "type_overtaking",
    "max_sog_a", "max_sog_b",
    "total_course_change_a", "total_course_change_b",
    "max_turn_rate_a", "max_turn_rate_b",
    "total_speed_change_a", "total_speed_change_b",
    "encounter_duration_s", "closure_rate",
    "ship_type_a", "ship_type_b",
    "length_a", "length_b",
]


def prepare_data(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, LabelEncoder]:
    """Prepare feature matrix and encoded labels from encounter DataFrame.

    Args:
        df: DataFrame from extract_encounters() with FEATURE_COLUMNS and risk_label.

    Returns:
        X: Feature matrix (n_samples, n_features)
        y: Encoded labels (n_samples,)
        le: Fitted LabelEncoder
    """
    X = df[FEATURE_COLUMNS].fillna(0).values.astype(np.float32)
    le = LabelEncoder()
    y = le.fit_transform(df["risk_label"].values)
    return X, y, le
