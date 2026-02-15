"""
End-to-end test: simuleert twee schepen die elkaar naderen, passeren en weer
uit elkaar varen.  Valideert de volledige pipeline zonder API key.

Scenario (Noordzee, voor de kust van Hoek van Holland):
  - Ship A vaart noordoost (COG 45°) met 12 knopen
  - Ship B vaart zuidwest (COG 225°) met 10 knopen
  → Head-on encounter, CPA ~0 m

Stappen:
  1. Database initialiseren (tijdelijk bestand)
  2. Vessel static data opslaan
  3. Positie-updates doorsturen naar EncounterDetector
  4. Controleren dat encounter correct gedetecteerd en opgeslagen wordt
  5. Schepen uit elkaar laten varen → encounter eindigt
  6. Database inhoud verifiëren
"""

import asyncio
import math
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta

# Gebruik een tijdelijke database
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
DB_FILE = _tmp.name
_tmp.close()
os.environ["DB_PATH"] = DB_FILE

from src.ais_client import VesselPosition, VesselStatic
from src.encounter_detector import EncounterDetector, haversine, compute_cpa_tcpa, classify_encounter
from src import database as db

KNOTS_TO_MS = 0.514444
NM_TO_METERS = 1852.0


def move_vessel(lat: float, lon: float, cog: float, sog_kn: float, seconds: float):
    """Beweeg een schip vanuit (lat, lon) met koers cog en snelheid sog voor t seconden."""
    speed_ms = sog_kn * KNOTS_TO_MS
    dist_m = speed_ms * seconds
    bearing_rad = math.radians(cog)
    lat_rad = math.radians(lat)

    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(lat_rad)

    new_lat = lat + (dist_m * math.cos(bearing_rad)) / m_per_deg_lat
    new_lon = lon + (dist_m * math.sin(bearing_rad)) / m_per_deg_lon
    return new_lat, new_lon


def make_pos(mmsi: str, lat: float, lon: float, sog: float, cog: float,
             ts: datetime, name: str = "") -> VesselPosition:
    return VesselPosition(
        mmsi=mmsi,
        timestamp=ts.isoformat(),
        lat=lat,
        lon=lon,
        sog=sog,
        cog=cog,
        heading=cog,
        name=name,
    )


def test_haversine():
    """Bekende afstand: Rotterdam - Amsterdam ≈ 57 km."""
    d = haversine(51.9225, 4.4792, 52.3676, 4.9041)
    assert 55_000 < d < 60_000, f"Haversine Rotterdam-Amsterdam verwacht ~57 km, kreeg {d/1000:.1f} km"
    print(f"  haversine Rotterdam-Amsterdam: {d/1000:.1f} km  OK")


def test_cpa_tcpa():
    """Twee schepen recht op elkaar af → CPA ≈ 0."""
    cpa, tcpa = compute_cpa_tcpa(
        52.0, 4.0, 10.0, 90.0,   # Ship A: oost
        52.0, 4.5, 10.0, 270.0,  # Ship B: west
    )
    assert cpa < 500, f"CPA verwacht ≈ 0, kreeg {cpa:.0f} m"
    assert tcpa > 0, f"TCPA verwacht > 0, kreeg {tcpa:.0f} s"
    print(f"  CPA head-on: {cpa:.0f} m, TCPA: {tcpa:.0f} s  OK")


def test_classify():
    """COLREGS classificatie."""
    assert classify_encounter(45.0, 225.0) == "head-on"
    assert classify_encounter(90.0, 80.0) == "overtaking"
    assert classify_encounter(0.0, 90.0) == "crossing"
    print("  COLREGS classificatie: head-on, overtaking, crossing  OK")


async def test_full_pipeline():
    """Simuleer twee schepen die elkaar passeren."""
    db.init_db()

    # Vessel static data
    db.upsert_vessel("211000001", name="TESTSHIP ALPHA", ship_type=70, length=120.0, width=20.0)
    db.upsert_vessel("211000002", name="TESTSHIP BRAVO", ship_type=70, length=95.0, width=16.0)

    detector = EncounterDetector()

    # Startposities: ~4 NM uit elkaar, varen naar elkaar toe
    # Ship A: start zuidwest, vaart noordoost (COG 45°)
    lat_a, lon_a = 51.95, 3.90
    cog_a, sog_a = 45.0, 12.0

    # Ship B: start noordoost, vaart zuidwest (COG 225°)
    lat_b, lon_b = 51.99, 3.96
    cog_b, sog_b = 225.0, 10.0

    t = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    step_seconds = 60  # elke minuut een positie-update

    encounter_started = False
    encounter_ended = False
    steps = 0
    max_steps = 120  # max 2 uur simulatie

    print(f"\n  Start: Ship A @ ({lat_a:.4f}, {lon_a:.4f}) COG {cog_a}° SOG {sog_a} kn")
    print(f"  Start: Ship B @ ({lat_b:.4f}, {lon_b:.4f}) COG {cog_b}° SOG {sog_b} kn")

    while steps < max_steps:
        t += timedelta(seconds=step_seconds)
        steps += 1

        # Beweeg schepen
        lat_a, lon_a = move_vessel(lat_a, lon_a, cog_a, sog_a, step_seconds)
        lat_b, lon_b = move_vessel(lat_b, lon_b, cog_b, sog_b, step_seconds)

        # Stuur positie-updates
        pos_a = make_pos("211000001", lat_a, lon_a, sog_a, cog_a, t, "TESTSHIP ALPHA")
        pos_b = make_pos("211000002", lat_b, lon_b, sog_b, cog_b, t, "TESTSHIP BRAVO")

        await detector.update(pos_a)
        await detector.update(pos_b)

        dist = haversine(lat_a, lon_a, lat_b, lon_b)

        if detector.active_encounters and not encounter_started:
            encounter_started = True
            print(f"  ✓ Encounter gedetecteerd na {steps} min (afstand: {dist:.0f} m / {dist/NM_TO_METERS:.2f} NM)")

        if encounter_started and not detector.active_encounters:
            encounter_ended = True
            print(f"  ✓ Encounter beëindigd na {steps} min (afstand: {dist:.0f} m / {dist/NM_TO_METERS:.2f} NM)")
            break

        # Na de encounter: laat schepen doorvaren tot ze > 5 NM uit elkaar zijn
        if encounter_started and dist > 5 * NM_TO_METERS + 1000:
            # Als encounter niet automatisch eindigt, forceer extra stappen
            pass

    assert encounter_started, "Encounter is nooit gestart!"
    assert encounter_ended, "Encounter is nooit geëindigd!"

    # Flush alle buffered data naar database
    await db.get_buffer().flush_all()

    # Verifieer database
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    vessels = conn.execute("SELECT * FROM vessels ORDER BY mmsi").fetchall()
    assert len(vessels) == 2, f"Verwacht 2 vessels, kreeg {len(vessels)}"
    print(f"\n  Database: {len(vessels)} vessels opgeslagen")
    for v in vessels:
        print(f"    {v['mmsi']}: {v['name']} (type {v['ship_type']}, {v['length']}m x {v['width']}m)")

    pos_count = conn.execute("SELECT COUNT(*) as c FROM positions").fetchone()["c"]
    assert pos_count > 0, "Geen posities opgeslagen!"
    print(f"  Database: {pos_count} posities opgeslagen")

    encounters = conn.execute("SELECT * FROM encounters").fetchall()
    assert len(encounters) >= 1, "Geen encounters opgeslagen!"
    enc = encounters[0]
    print(f"\n  Encounter #{enc['id']}:")
    print(f"    Schepen: {enc['vessel_a_mmsi']} <-> {enc['vessel_b_mmsi']}")
    print(f"    Type: {enc['encounter_type']}")
    print(f"    Start: {enc['start_time']}")
    print(f"    Eind:  {enc['end_time']}")
    print(f"    Min afstand: {enc['min_distance_m']:.0f} m ({enc['min_distance_m']/NM_TO_METERS:.2f} NM)")
    print(f"    CPA: {enc['cpa_m']:.0f} m")
    print(f"    TCPA: {enc['tcpa_s']:.0f} s")

    enc_pos_count = conn.execute("SELECT COUNT(*) as c FROM encounter_positions").fetchone()["c"]
    assert enc_pos_count > 0, "Geen encounter posities opgeslagen!"
    print(f"    Encounter posities: {enc_pos_count}")

    assert enc['end_time'] is not None, "Encounter heeft geen eind-tijd!"
    assert enc['min_distance_m'] < 3 * NM_TO_METERS, "Min afstand zou < 3 NM moeten zijn"

    conn.close()
    print("\n  Alle database checks geslaagd!")


def main():
    print("=" * 60)
    print("Marine Traffic Encounter Test")
    print("=" * 60)

    failed = 0

    print("\n[1/4] Haversine afstandsberekening")
    try:
        test_haversine()
    except AssertionError as e:
        print(f"  FAILED: {e}")
        failed += 1

    print("\n[2/4] CPA/TCPA berekening")
    try:
        test_cpa_tcpa()
    except AssertionError as e:
        print(f"  FAILED: {e}")
        failed += 1

    print("\n[3/4] COLREGS classificatie")
    try:
        test_classify()
    except AssertionError as e:
        print(f"  FAILED: {e}")
        failed += 1

    print("\n[4/4] Volledige pipeline simulatie")
    try:
        asyncio.run(test_full_pipeline())
    except AssertionError as e:
        print(f"  FAILED: {e}")
        failed += 1

    print("\n" + "=" * 60)
    if failed:
        print(f"RESULTAAT: {failed} test(s) gefaald!")
        sys.exit(1)
    else:
        print("RESULTAAT: Alle tests geslaagd!")
        print(f"\nTijdelijke database: {DB_FILE}")
        print("Bekijk met: sqlite3 " + DB_FILE)
    print("=" * 60)

    # Cleanup
    try:
        os.remove(DB_FILE)
        print("(Tijdelijke database opgeruimd)")
    except OSError:
        pass


if __name__ == "__main__":
    main()
