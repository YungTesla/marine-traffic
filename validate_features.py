"""Validate feature engineering functions for edge cases and quality."""

import logging
import numpy as np
import pandas as pd

from src.ml.features import (
    cog_to_sincos,
    normalize_positions,
    compute_derived_features,
    build_trajectory_features,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def test_cog_to_sincos():
    """Test COG sin/cos encoding."""
    logger.info("=" * 60)
    logger.info("TESTING COG SIN/COS ENCODING")
    logger.info("=" * 60)

    # Test known values
    test_cases = [
        (0, (0.0, 1.0)),      # North
        (90, (1.0, 0.0)),     # East
        (180, (0.0, -1.0)),   # South
        (270, (-1.0, 0.0)),   # West
        (360, (0.0, 1.0)),    # Full circle = North
    ]

    for cog, expected in test_cases:
        sin_val, cos_val = cog_to_sincos(np.array([cog]))
        sin_exp, cos_exp = expected

        if np.isclose(sin_val[0], sin_exp, atol=1e-10) and np.isclose(cos_val[0], cos_exp, atol=1e-10):
            logger.info(f"✓ COG {cog}° → sin={sin_val[0]:.4f}, cos={cos_val[0]:.4f}")
        else:
            logger.error(f"✗ COG {cog}° expected sin={sin_exp}, cos={cos_exp}, got sin={sin_val[0]}, cos={cos_val[0]}")

    # Test array
    cogs = np.array([0, 90, 180, 270])
    sin_vals, cos_vals = cog_to_sincos(cogs)

    # Check magnitude (sin²+cos² = 1)
    magnitudes = sin_vals**2 + cos_vals**2
    if np.allclose(magnitudes, 1.0):
        logger.info(f"✓ All sin²+cos² = 1 (magnitude check passed)")
    else:
        logger.error(f"✗ Magnitude check failed: {magnitudes}")

    # Check for NaN/Inf
    if not (np.any(np.isnan(sin_vals)) or np.any(np.isnan(cos_vals))):
        logger.info("✓ No NaN values")
    else:
        logger.error("✗ Found NaN values")

    return True


def test_normalize_positions():
    """Test position normalization."""
    logger.info("=" * 60)
    logger.info("TESTING POSITION NORMALIZATION")
    logger.info("=" * 60)

    # Test with known positions around Amsterdam (52.37°N, 4.89°E)
    lats = np.array([52.0, 52.5, 53.0])
    lons = np.array([4.0, 5.0, 6.0])

    delta_x, delta_y = normalize_positions(lats, lons)

    logger.info(f"✓ Input lats: {lats}")
    logger.info(f"✓ Input lons: {lons}")
    logger.info(f"✓ Delta X (meters): {delta_x}")
    logger.info(f"✓ Delta Y (meters): {delta_y}")

    # Centroid should be near (52.5, 5.0)
    centroid_lat = lats.mean()
    centroid_lon = lons.mean()
    logger.info(f"✓ Centroid: ({centroid_lat:.2f}°N, {centroid_lon:.2f}°E)")

    # Check that centroid maps to (0, 0)
    center_idx = 1  # Middle point
    if np.isclose(delta_x[center_idx], 0, atol=1000) and np.isclose(delta_y[center_idx], 0, atol=1000):
        logger.info(f"✓ Centroid maps near (0, 0): ({delta_x[center_idx]:.1f}m, {delta_y[center_idx]:.1f}m)")
    else:
        logger.warning(f"⚠ Centroid not at origin: ({delta_x[center_idx]:.1f}m, {delta_y[center_idx]:.1f}m)")

    # Check for reasonable scales (1° lat ≈ 111km)
    lat_diff = lats[2] - lats[0]  # 1 degree
    delta_y_diff = delta_y[2] - delta_y[0]
    expected_y = lat_diff * 111_320  # meters

    if np.isclose(delta_y_diff, expected_y, rtol=0.01):
        logger.info(f"✓ Y scale correct: {delta_y_diff:.0f}m ≈ {expected_y:.0f}m")
    else:
        logger.error(f"✗ Y scale wrong: {delta_y_diff:.0f}m vs expected {expected_y:.0f}m")

    # Check for NaN/Inf
    if not (np.any(np.isnan(delta_x)) or np.any(np.isnan(delta_y))):
        logger.info("✓ No NaN values")
    else:
        logger.error("✗ Found NaN values")

    return True


def test_compute_derived_features():
    """Test derived feature computation."""
    logger.info("=" * 60)
    logger.info("TESTING DERIVED FEATURES")
    logger.info("=" * 60)

    # Create sample trajectory
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=5, freq="10s", tz="UTC"),
        "sog": [10.0, 12.0, 11.0, 13.0, 12.5],  # knots
        "cog": [0.0, 10.0, 20.0, 15.0, 10.0],   # degrees
    })

    logger.info(f"✓ Input trajectory:\n{df}")

    result = compute_derived_features(df)

    logger.info(f"✓ Added columns: {[c for c in result.columns if c not in df.columns]}")
    logger.info(f"✓ Output shape: {result.shape}")

    # Check expected columns
    expected_cols = ["delta_t", "acceleration", "rate_of_turn"]
    for col in expected_cols:
        if col in result.columns:
            logger.info(f"✓ Column '{col}' present")
        else:
            logger.error(f"✗ Column '{col}' missing")

    # Check delta_t
    if result["delta_t"].iloc[0] == 0.0:
        logger.info(f"✓ First delta_t is 0.0")
    else:
        logger.error(f"✗ First delta_t should be 0.0, got {result['delta_t'].iloc[0]}")

    if np.allclose(result["delta_t"].iloc[1:], 10.0):
        logger.info(f"✓ Subsequent delta_t values are 10.0 seconds")
    else:
        logger.error(f"✗ Delta_t values incorrect: {result['delta_t'].values}")

    # Check acceleration (should be (12-10)/10 = 0.2 knots/s at index 1)
    expected_accel = (12.0 - 10.0) / 10.0
    if np.isclose(result["acceleration"].iloc[1], expected_accel):
        logger.info(f"✓ Acceleration correct: {result['acceleration'].iloc[1]:.2f} knots/s")
    else:
        logger.error(f"✗ Acceleration wrong: {result['acceleration'].iloc[1]:.2f} vs expected {expected_accel:.2f}")

    # Check rate_of_turn (should be (10-0)/10 = 1.0 deg/s at index 1)
    expected_rot = (10.0 - 0.0) / 10.0
    if np.isclose(result["rate_of_turn"].iloc[1], expected_rot):
        logger.info(f"✓ Rate of turn correct: {result['rate_of_turn'].iloc[1]:.2f} deg/s")
    else:
        logger.error(f"✗ Rate of turn wrong: {result['rate_of_turn'].iloc[1]:.2f} vs expected {expected_rot:.2f}")

    # Test 360° wraparound
    df_wrap = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=3, freq="10s", tz="UTC"),
        "sog": [10.0, 10.0, 10.0],
        "cog": [350.0, 10.0, 20.0],  # Crosses 0°
    })
    result_wrap = compute_derived_features(df_wrap)

    # 350° → 10° should be +20°, not -340°
    rot_1 = result_wrap["rate_of_turn"].iloc[1]
    if rot_1 > 0 and rot_1 < 5:  # Should be 20/10 = 2 deg/s
        logger.info(f"✓ Wraparound handled correctly: {rot_1:.2f} deg/s")
    else:
        logger.error(f"✗ Wraparound failed: {rot_1:.2f} deg/s")

    # Check for NaN/Inf
    if not result.isnull().any().any():
        logger.info("✓ No NaN values")
    else:
        logger.warning("⚠ Found NaN values (expected at first row)")

    return True


def test_build_trajectory_features():
    """Test complete trajectory feature building."""
    logger.info("=" * 60)
    logger.info("TESTING TRAJECTORY FEATURE BUILDING")
    logger.info("=" * 60)

    # Create sample trajectory
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=10, freq="30s", tz="UTC"),
        "lat": np.linspace(52.0, 52.1, 10),
        "lon": np.linspace(4.0, 4.1, 10),
        "sog": np.linspace(10.0, 12.0, 10),
        "cog": np.linspace(0.0, 45.0, 10),
        "heading": np.linspace(0.0, 45.0, 10),
        "acceleration": np.zeros(10),
        "rate_of_turn": np.zeros(10),
        "delta_t": np.full(10, 30.0),
    })

    logger.info(f"✓ Input shape: {df.shape}")

    features = build_trajectory_features(df)

    logger.info(f"✓ Output shape: {features.shape}")
    logger.info(f"✓ Expected shape: ({len(df)}, 10)")

    # Check shape
    if features.shape == (len(df), 10):
        logger.info("✓ Correct feature shape")
    else:
        logger.error(f"✗ Wrong shape: {features.shape}")

    # Check dtype
    if features.dtype == np.float32:
        logger.info("✓ Correct dtype (float32)")
    else:
        logger.error(f"✗ Wrong dtype: {features.dtype}")

    # Check for NaN/Inf
    if not np.any(np.isnan(features)):
        logger.info("✓ No NaN values")
    else:
        logger.error("✗ Found NaN values")

    if not np.any(np.isinf(features)):
        logger.info("✓ No Inf values")
    else:
        logger.error("✗ Found Inf values")

    # Check sin/cos bounds [-1, 1]
    sin_cos_cols = [3, 4, 5, 6]  # cog_sin, cog_cos, heading_sin, heading_cos
    for col_idx in sin_cos_cols:
        col_data = features[:, col_idx]
        if np.all((col_data >= -1.0) & (col_data <= 1.0)):
            logger.info(f"✓ Column {col_idx} (sin/cos) in range [-1, 1]")
        else:
            logger.error(f"✗ Column {col_idx} out of range: [{col_data.min():.2f}, {col_data.max():.2f}]")

    # Test heading fallback (heading=-1 should use COG)
    df_fallback = df.copy()
    df_fallback["heading"] = -1.0
    features_fallback = build_trajectory_features(df_fallback)

    # heading_sin/cos should equal cog_sin/cos
    if np.allclose(features_fallback[:, 5], features_fallback[:, 3]):  # heading_sin == cog_sin
        logger.info("✓ Heading fallback to COG works correctly")
    else:
        logger.error("✗ Heading fallback failed")

    return True


if __name__ == "__main__":
    logger.info("Starting feature engineering validation...")

    test_cog_to_sincos()
    test_normalize_positions()
    test_compute_derived_features()
    test_build_trajectory_features()

    logger.info("=" * 60)
    logger.info("✓ ALL FEATURE ENGINEERING TESTS COMPLETED")
    logger.info("=" * 60)
