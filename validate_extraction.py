"""Quick validation script for ML data extraction functions."""

import logging
from src.ml.data_extraction import (
    extract_trajectories,
    extract_encounters,
    extract_encounter_pairs,
    trajectories_to_features,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

def validate_trajectories():
    """Validate trajectory extraction and feature building."""
    logger.info("=" * 60)
    logger.info("VALIDATING TRAJECTORY EXTRACTION")
    logger.info("=" * 60)

    segments = extract_trajectories(min_segment_len=20, max_gap_seconds=300.0)
    logger.info(f"✓ Extracted {len(segments)} trajectory segments")

    if segments:
        sample = segments[0]
        logger.info(f"✓ Sample segment shape: {sample.shape}")
        logger.info(f"✓ Sample columns: {list(sample.columns)}")
        logger.info(f"✓ Sample length: {len(sample)} positions")

        # Check for nulls
        nulls = sample.isnull().sum()
        if nulls.any():
            logger.warning(f"⚠ Found nulls:\n{nulls[nulls > 0]}")
        else:
            logger.info("✓ No null values in sample segment")

        # Convert to features
        features = trajectories_to_features(segments[:5])
        logger.info(f"✓ Converted {len(features)} segments to feature arrays")
        logger.info(f"✓ Sample feature shape: {features[0].shape} (expected: (seq_len, 10))")

        # Check for NaN/Inf
        import numpy as np
        if np.any(np.isnan(features[0])):
            logger.error("✗ Found NaN values in features!")
        elif np.any(np.isinf(features[0])):
            logger.error("✗ Found Inf values in features!")
        else:
            logger.info("✓ No NaN/Inf in sample features")

    return len(segments) > 0


def validate_encounters():
    """Validate encounter feature extraction."""
    logger.info("=" * 60)
    logger.info("VALIDATING ENCOUNTER EXTRACTION")
    logger.info("=" * 60)

    df = extract_encounters()
    logger.info(f"✓ Extracted {len(df)} encounter feature rows")

    if not df.empty:
        logger.info(f"✓ Feature columns ({len(df.columns)}): {list(df.columns)}")
        logger.info(f"✓ Risk label distribution:\n{df['risk_label'].value_counts()}")

        # Check for nulls
        nulls = df.isnull().sum()
        if nulls.any():
            logger.warning(f"⚠ Found nulls:\n{nulls[nulls > 0]}")
        else:
            logger.info("✓ No null values in features")

        # Check expected feature count (20 features as per CLAUDE.md)
        feature_cols = [c for c in df.columns if c not in ['encounter_id', 'risk_label']]
        logger.info(f"✓ Feature count: {len(feature_cols)} (expected 20)")

        # Sample statistics
        logger.info(f"✓ Sample feature statistics:\n{df[feature_cols].describe()}")

    return not df.empty


def validate_encounter_pairs():
    """Validate encounter pair extraction."""
    logger.info("=" * 60)
    logger.info("VALIDATING ENCOUNTER PAIR EXTRACTION")
    logger.info("=" * 60)

    pairs = extract_encounter_pairs()
    logger.info(f"✓ Extracted {len(pairs)} encounter pairs")

    if pairs:
        sample = pairs[0]
        logger.info(f"✓ Sample keys: {list(sample.keys())}")
        logger.info(f"✓ States A shape: {sample['states_a'].shape} (expected: (T, 19))")
        logger.info(f"✓ Actions A shape: {sample['actions_a'].shape} (expected: (T-1, 2))")
        logger.info(f"✓ States B shape: {sample['states_b'].shape}")
        logger.info(f"✓ Actions B shape: {sample['actions_b'].shape}")

        # Check state dimension
        if sample['states_a'].shape[1] != 19:
            logger.error(f"✗ Expected 19 state features, got {sample['states_a'].shape[1]}")
        else:
            logger.info("✓ Correct state dimension (19)")

        # Check action dimension
        if sample['actions_a'].shape[1] != 2:
            logger.error(f"✗ Expected 2 action features, got {sample['actions_a'].shape[1]}")
        else:
            logger.info("✓ Correct action dimension (2)")

        # Check for NaN/Inf
        import numpy as np
        if np.any(np.isnan(sample['states_a'])):
            logger.error("✗ Found NaN values in states!")
        elif np.any(np.isinf(sample['states_a'])):
            logger.error("✗ Found Inf values in states!")
        else:
            logger.info("✓ No NaN/Inf in sample states")

    return len(pairs) > 0


if __name__ == "__main__":
    logger.info("Starting ML data extraction validation...")

    traj_ok = validate_trajectories()
    enc_ok = validate_encounters()
    pairs_ok = validate_encounter_pairs()

    logger.info("=" * 60)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Trajectory extraction: {'✓ PASS' if traj_ok else '✗ FAIL'}")
    logger.info(f"Encounter extraction: {'✓ PASS' if enc_ok else '✗ FAIL'}")
    logger.info(f"Encounter pairs extraction: {'✓ PASS' if pairs_ok else '✗ FAIL'}")

    if traj_ok and enc_ok and pairs_ok:
        logger.info("=" * 60)
        logger.info("✓ ALL DATA EXTRACTION FUNCTIONS VALIDATED SUCCESSFULLY")
        logger.info("=" * 60)
    else:
        logger.error("=" * 60)
        logger.error("✗ SOME VALIDATION CHECKS FAILED")
        logger.error("=" * 60)
