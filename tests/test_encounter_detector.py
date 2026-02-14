"""
Unit tests for core encounter detection functions.

Tests cover:
- haversine distance calculations
- CPA/TCPA computations
- COLREGS encounter classification
"""

import math
import pytest
from src.encounter_detector import haversine, compute_cpa_tcpa, classify_encounter


class TestHaversine:
    """Test haversine distance calculations with known values."""

    def test_same_position(self):
        """Distance between same position should be zero."""
        dist = haversine(52.0, 4.0, 52.0, 4.0)
        assert dist == pytest.approx(0.0, abs=1.0)

    def test_short_distance(self):
        """Test short distance calculation (< 1 NM)."""
        # Amsterdam to ~1 NM north
        lat1, lon1 = 52.3676, 4.9041
        lat2, lon2 = 52.3856, 4.9041  # ~1.08 NM north
        dist = haversine(lat1, lon1, lat2, lon2)
        expected = 2000.0  # ~2000 meters
        assert dist == pytest.approx(expected, rel=0.05)

    def test_medium_distance(self):
        """Test medium distance calculation (1-10 NM)."""
        # Rotterdam to Hook of Holland (~25 km = ~13.6 NM)
        lat1, lon1 = 51.9225, 4.4792  # Rotterdam
        lat2, lon2 = 51.9775, 4.1217  # Hook of Holland
        dist = haversine(lat1, lon1, lat2, lon2)
        expected = 25_000.0  # ~25,000 meters
        assert dist == pytest.approx(expected, rel=0.10)

    def test_equator_distance(self):
        """Test distance along equator (simple case)."""
        # 1 degree longitude at equator ≈ 111.32 km
        lat1, lon1 = 0.0, 0.0
        lat2, lon2 = 0.0, 1.0
        dist = haversine(lat1, lon1, lat2, lon2)
        expected = 111_320.0  # meters
        assert dist == pytest.approx(expected, rel=0.01)

    def test_north_south_distance(self):
        """Test pure north-south distance."""
        # 1 degree latitude ≈ 111.32 km everywhere
        lat1, lon1 = 52.0, 4.0
        lat2, lon2 = 53.0, 4.0
        dist = haversine(lat1, lon1, lat2, lon2)
        expected = 111_320.0  # meters
        assert dist == pytest.approx(expected, rel=0.01)

    def test_symmetry(self):
        """Distance should be same in both directions."""
        lat1, lon1 = 52.0, 4.0
        lat2, lon2 = 53.5, 6.2
        dist1 = haversine(lat1, lon1, lat2, lon2)
        dist2 = haversine(lat2, lon2, lat1, lon1)
        assert dist1 == pytest.approx(dist2)

    def test_negative_coordinates(self):
        """Test with negative (southern/western) coordinates."""
        # São Paulo to Rio de Janeiro (~360 km)
        lat1, lon1 = -23.5505, -46.6333  # São Paulo
        lat2, lon2 = -22.9068, -43.1729  # Rio de Janeiro
        dist = haversine(lat1, lon1, lat2, lon2)
        expected = 360_000.0  # meters
        assert dist == pytest.approx(expected, rel=0.15)


class TestComputeCpaTcpa:
    """Test CPA/TCPA computations for various encounter scenarios."""

    def test_stationary_vessels(self):
        """Two stationary vessels should have CPA = current distance, TCPA = 0."""
        lat_a, lon_a = 52.0, 4.0
        sog_a, cog_a = 0.0, 0.0
        lat_b, lon_b = 52.01, 4.01  # ~1.5 km away
        sog_b, cog_b = 0.0, 0.0

        cpa, tcpa = compute_cpa_tcpa(lat_a, lon_a, sog_a, cog_a, lat_b, lon_b, sog_b, cog_b)

        # CPA should be approximately the current distance
        current_dist = haversine(lat_a, lon_a, lat_b, lon_b)
        assert cpa == pytest.approx(current_dist, rel=0.01)
        assert tcpa == 0.0

    def test_parallel_same_speed(self):
        """Vessels moving parallel at same speed maintain distance."""
        lat_a, lon_a = 52.0, 4.0
        sog_a, cog_a = 10.0, 0.0  # 10 knots north
        lat_b, lon_b = 52.0, 4.01  # ~700m east
        sog_b, cog_b = 10.0, 0.0  # 10 knots north

        cpa, tcpa = compute_cpa_tcpa(lat_a, lon_a, sog_a, cog_a, lat_b, lon_b, sog_b, cog_b)

        # CPA should be approximately current distance, TCPA should be 0
        current_dist = haversine(lat_a, lon_a, lat_b, lon_b)
        assert cpa == pytest.approx(current_dist, rel=0.05)
        assert tcpa == pytest.approx(0.0, abs=1.0)

    def test_head_on_collision_course(self):
        """Vessels on direct collision course."""
        lat_a, lon_a = 52.0, 4.0
        sog_a, cog_a = 10.0, 0.0  # 10 knots north
        lat_b, lon_b = 52.05, 4.0  # ~5.5 km north
        sog_b, cog_b = 10.0, 180.0  # 10 knots south

        cpa, tcpa = compute_cpa_tcpa(lat_a, lon_a, sog_a, cog_a, lat_b, lon_b, sog_b, cog_b)

        # CPA should be near zero (direct collision)
        assert cpa < 100.0  # Less than 100 meters
        # TCPA should be positive (approaching)
        assert tcpa > 0.0
        # TCPA should be roughly distance / combined_speed
        # ~5500m / (10kn + 10kn) = 5500 / (20 * 0.514 m/s) ≈ 535s
        assert tcpa == pytest.approx(535.0, rel=0.20)

    def test_crossing_90_degrees(self):
        """Vessels crossing at 90 degrees."""
        lat_a, lon_a = 52.0, 4.0
        sog_a, cog_a = 10.0, 90.0  # 10 knots east
        lat_b, lon_b = 52.01, 4.0  # ~1.1 km north
        sog_b, cog_b = 10.0, 180.0  # 10 knots south

        cpa, tcpa = compute_cpa_tcpa(lat_a, lon_a, sog_a, cog_a, lat_b, lon_b, sog_b, cog_b)

        # CPA will depend on when they cross
        assert cpa >= 0.0
        assert tcpa > 0.0  # They are approaching

    def test_overtaking(self):
        """Faster vessel overtaking slower vessel ahead."""
        lat_a, lon_a = 52.0, 4.0
        sog_a, cog_a = 15.0, 0.0  # 15 knots north (faster)
        lat_b, lon_b = 52.005, 4.0  # ~555m ahead
        sog_b, cog_b = 10.0, 0.0  # 10 knots north (slower)

        cpa, tcpa = compute_cpa_tcpa(lat_a, lon_a, sog_a, cog_a, lat_b, lon_b, sog_b, cog_b)

        # CPA should be small (overtaking on same track)
        assert cpa < 100.0
        # TCPA should be positive (catching up)
        assert tcpa > 0.0

    def test_diverging_vessels(self):
        """Vessels moving apart should have negative TCPA."""
        lat_a, lon_a = 52.0, 4.0
        sog_a, cog_a = 10.0, 180.0  # 10 knots south
        lat_b, lon_b = 52.01, 4.0  # ~1.1 km north
        sog_b, cog_b = 10.0, 0.0  # 10 knots north

        cpa, tcpa = compute_cpa_tcpa(lat_a, lon_a, sog_a, cog_a, lat_b, lon_b, sog_b, cog_b)

        # TCPA should be negative (diverging now)
        assert tcpa < 0.0
        # CPA is nearly zero because they were on a collision course in the past
        # (both on same longitude, moving in opposite directions)
        assert cpa < 100.0  # Very close approach in the past

    def test_perpendicular_miss(self):
        """Vessels on perpendicular courses that will miss."""
        lat_a, lon_a = 52.0, 4.0
        sog_a, cog_a = 10.0, 0.0  # 10 knots north
        lat_b, lon_b = 52.0, 4.02  # ~1.4 km east
        sog_b, cog_b = 10.0, 270.0  # 10 knots west

        cpa, tcpa = compute_cpa_tcpa(lat_a, lon_a, sog_a, cog_a, lat_b, lon_b, sog_b, cog_b)

        # CPA should be positive (they miss)
        assert cpa > 0.0
        # TCPA should be positive (approaching CPA)
        assert tcpa > 0.0


class TestClassifyEncounter:
    """Test COLREGS encounter classification."""

    def test_head_on_opposite_directions(self):
        """Vessels on exact opposite courses are head-on."""
        assert classify_encounter(0.0, 180.0) == "head-on"
        assert classify_encounter(90.0, 270.0) == "head-on"
        assert classify_encounter(180.0, 0.0) == "head-on"

    def test_head_on_boundary_170_degrees(self):
        """170° difference is the boundary for head-on."""
        assert classify_encounter(0.0, 170.0) == "head-on"
        assert classify_encounter(0.0, 190.0) == "head-on"  # 170° when normalized
        assert classify_encounter(45.0, 215.0) == "head-on"

    def test_head_on_near_boundary(self):
        """Test near the 170° boundary."""
        assert classify_encounter(0.0, 171.0) == "head-on"
        assert classify_encounter(0.0, 175.0) == "head-on"
        assert classify_encounter(0.0, 169.0) == "crossing"

    def test_overtaking_same_direction(self):
        """Vessels on same or very similar courses are overtaking."""
        assert classify_encounter(0.0, 0.0) == "overtaking"
        assert classify_encounter(90.0, 90.0) == "overtaking"
        assert classify_encounter(180.0, 180.0) == "overtaking"

    def test_overtaking_boundary_15_degrees(self):
        """15° difference is the boundary for overtaking."""
        assert classify_encounter(0.0, 15.0) == "overtaking"
        assert classify_encounter(90.0, 105.0) == "overtaking"
        assert classify_encounter(180.0, 195.0) == "overtaking"

    def test_overtaking_near_boundary(self):
        """Test near the 15° boundary."""
        assert classify_encounter(0.0, 14.0) == "overtaking"
        assert classify_encounter(0.0, 10.0) == "overtaking"
        assert classify_encounter(0.0, 16.0) == "crossing"

    def test_crossing_mid_range(self):
        """Vessels with intermediate course differences are crossing."""
        assert classify_encounter(0.0, 90.0) == "crossing"
        assert classify_encounter(0.0, 45.0) == "crossing"
        assert classify_encounter(0.0, 135.0) == "crossing"
        assert classify_encounter(90.0, 180.0) == "crossing"

    def test_crossing_boundaries(self):
        """Test crossing classification boundaries."""
        # Just above overtaking threshold
        assert classify_encounter(0.0, 16.0) == "crossing"
        assert classify_encounter(0.0, 30.0) == "crossing"
        # Just below head-on threshold
        assert classify_encounter(0.0, 169.0) == "crossing"
        assert classify_encounter(0.0, 150.0) == "crossing"

    def test_symmetry(self):
        """Classification should be same regardless of vessel order."""
        assert classify_encounter(0.0, 90.0) == classify_encounter(90.0, 0.0)
        assert classify_encounter(45.0, 180.0) == classify_encounter(180.0, 45.0)
        assert classify_encounter(270.0, 15.0) == classify_encounter(15.0, 270.0)

    def test_wraparound_360(self):
        """Test course differences that wrap around 360°."""
        # 350° and 10° are 20° apart
        assert classify_encounter(350.0, 10.0) == "crossing"
        # 355° and 5° are 10° apart (overtaking)
        assert classify_encounter(355.0, 5.0) == "overtaking"
        # 10° and 350° are 20° apart
        assert classify_encounter(10.0, 350.0) == "crossing"

    def test_various_angles(self):
        """Test a variety of course combinations."""
        # Head-on examples
        assert classify_encounter(0.0, 180.0) == "head-on"
        assert classify_encounter(45.0, 225.0) == "head-on"
        assert classify_encounter(270.0, 90.0) == "head-on"

        # Overtaking examples
        assert classify_encounter(100.0, 100.0) == "overtaking"
        assert classify_encounter(200.0, 210.0) == "overtaking"

        # Crossing examples
        assert classify_encounter(0.0, 60.0) == "crossing"
        assert classify_encounter(120.0, 200.0) == "crossing"
        assert classify_encounter(300.0, 50.0) == "crossing"
