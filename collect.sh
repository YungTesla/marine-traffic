#!/usr/bin/env bash
set -euo pipefail

HOURS=${1:?Gebruik: ./collect.sh <uren>}
SECONDS_TO_RUN=$(python3 -c "print(int(float($HOURS) * 3600))")

cleanup() {
    echo ""
    echo "Onderbroken. Container wordt gestopt..."
    docker compose stop -t 15 2>/dev/null || true
    docker compose down 2>/dev/null || true
    exit 1
}
trap cleanup INT TERM

echo "=== Marine Traffic Collector ==="
echo "AIS data verzamelen voor ${HOURS} uur (${SECONDS_TO_RUN}s)..."
echo ""

# Fase 1: Start collector
docker compose up -d --build
echo "Collector gestart."
echo ""

# Wacht de opgegeven duur
sleep "${SECONDS_TO_RUN}"

# Fase 2: Stop collector netjes (SIGTERM -> flush buffers)
echo "Tijd verstreken. Collector wordt gestopt..."
docker compose stop -t 15
echo "Collector gestopt."
echo ""

# Fase 3: Exporteer alle tabellen als CSV
echo "Database tabellen exporteren naar CSV..."
docker compose run --rm \
    -v "$(pwd):/output" \
    --no-deps \
    ais-collector \
    python scripts/export_tables.py /output

# Fase 4: Cleanup
docker compose down
echo ""
echo "=== Klaar ==="
echo "CSV bestanden:"
ls -lh ./*.csv 2>/dev/null || echo "(geen CSV bestanden gevonden)"
