"""Unit tests for ais_client module."""
import random

from src.ais_client import _calculate_backoff
from src.config import (
    RECONNECT_BASE_DELAY_S,
    RECONNECT_MAX_DELAY_S,
    RECONNECT_JITTER_FACTOR,
)


def test_backoff_progression():
    """Test that backoff follows exponential progression: 1s, 2s, 4s, 8s, etc."""
    # Set seed for reproducible jitter
    random.seed(42)

    # Expected base delays (without jitter): 1, 2, 4, 8, 16, 32, 60 (capped)
    delays = [_calculate_backoff(i) for i in range(7)]

    # Verify exponential growth pattern (with jitter tolerance)
    expected = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0]
    for i, (actual, exp) in enumerate(zip(delays, expected)):
        # Allow for jitter (±30%) plus small margin
        min_expected = exp * (1 - RECONNECT_JITTER_FACTOR) * 0.95
        max_expected = exp * (1 + RECONNECT_JITTER_FACTOR) * 1.05
        assert min_expected <= actual <= max_expected, (
            f"Attempt {i}: delay {actual:.2f}s outside expected range "
            f"[{min_expected:.2f}, {max_expected:.2f}]"
        )


def test_backoff_cap():
    """Test that backoff is capped at RECONNECT_MAX_DELAY_S."""
    # Even with very high attempt numbers, should cap at 60s
    for attempt in [10, 20, 50, 100]:
        delay = _calculate_backoff(attempt)
        assert delay <= RECONNECT_MAX_DELAY_S * (1 + RECONNECT_JITTER_FACTOR) * 1.05, (
            f"Attempt {attempt}: delay {delay:.2f}s exceeds max {RECONNECT_MAX_DELAY_S}s"
        )


def test_backoff_positive():
    """Test that backoff never returns negative or zero delays."""
    random.seed(999)  # Try different seed

    for attempt in range(20):
        delay = _calculate_backoff(attempt)
        assert delay > 0, f"Attempt {attempt}: delay {delay:.2f}s must be positive"
        assert delay >= 0.1, f"Attempt {attempt}: delay {delay:.2f}s too small (< 0.1s)"


def test_backoff_jitter_variance():
    """Test that jitter produces different values across multiple calls."""
    delays = [_calculate_backoff(5) for _ in range(10)]

    # All delays should be different (with very high probability)
    unique_delays = len(set(delays))
    assert unique_delays >= 8, (
        f"Only {unique_delays}/10 unique delays - jitter may not be working"
    )

    # All should be around 32s ± 30%
    expected = 32.0
    for delay in delays:
        min_expected = expected * (1 - RECONNECT_JITTER_FACTOR) * 0.9
        max_expected = expected * (1 + RECONNECT_JITTER_FACTOR) * 1.1
        assert min_expected <= delay <= max_expected, (
            f"Delay {delay:.2f}s outside jittered range for attempt 5"
        )


def test_backoff_first_attempt():
    """Test that first reconnection attempt is ~1 second."""
    random.seed(123)
    delay = _calculate_backoff(0)

    # Should be close to base delay (1s) with jitter
    min_expected = RECONNECT_BASE_DELAY_S * (1 - RECONNECT_JITTER_FACTOR) * 0.95
    max_expected = RECONNECT_BASE_DELAY_S * (1 + RECONNECT_JITTER_FACTOR) * 1.05
    assert min_expected <= delay <= max_expected, (
        f"First attempt delay {delay:.2f}s should be ~{RECONNECT_BASE_DELAY_S}s ± jitter"
    )


if __name__ == "__main__":
    # Run tests manually (no pytest dependency in CLAUDE.md conventions)
    test_backoff_progression()
    print("✓ test_backoff_progression")

    test_backoff_cap()
    print("✓ test_backoff_cap")

    test_backoff_positive()
    print("✓ test_backoff_positive")

    test_backoff_jitter_variance()
    print("✓ test_backoff_jitter_variance")

    test_backoff_first_attempt()
    print("✓ test_backoff_first_attempt")

    print("\nAll tests passed!")
