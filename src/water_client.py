"""Waterstand polling client voor Rijkswaterstaat Waterinfo API (ddapi20).

Haalt elke WATER_POLL_INTERVAL_S seconden de meest recente waterstand op
voor alle geconfigureerde stations en slaat deze op in de database.

API referentie: https://ddapi20-waterwebservices.rijkswaterstaat.nl
Geen API-key vereist. Data update elke 10 minuten.
"""

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

from src.config import WATERINFO_BASE_URL, WATERINFO_STATIONS, WATER_POLL_INTERVAL_S
from src import database as db

logger = logging.getLogger(__name__)

_LATEST_URL = (
    f"{WATERINFO_BASE_URL}/ONLINEWAARNEMINGENSERVICES/OphalenLaatsteWaarnemingen"
)

_AQUO_METADATA = {
    "AquoMetadata": {
        "Grootheid": {"Code": "WATHTE"},
        "Eenheid": {"Code": "cm"},
        "Hoedanigheid": {"Code": "NAP"},
    }
}


def _parse_rws_timestamp(ts_str: str) -> str:
    """Converteer RWS API timestamp naar UTC ISO format ('YYYY-MM-DDTHH:MM:SSZ').

    Verwacht format: '2026-02-18T12:00:00.000+01:00'
    """
    dt = datetime.fromisoformat(ts_str)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _fetch_latest_water_level(
    session: aiohttp.ClientSession, station_id: str
) -> dict | None:
    """Haal de meest recente waterstand op voor één station.

    Returns dict met 'timestamp' (UTC ISO string) en 'value' (float, cm NAP),
    of None als geen data beschikbaar is.
    """
    payload = {
        "Locatie": {"Code": station_id},
        "AquoPlusWaarnemingMetadata": _AQUO_METADATA,
    }
    try:
        async with session.post(_LATEST_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 204:
                logger.debug("Geen waterstanddata voor station %s (HTTP 204)", station_id)
                return None

            resp.raise_for_status()
            data = await resp.json()

            waarnemingen = data.get("WaarnemingenLijst", [])
            if not waarnemingen:
                logger.debug("Lege WaarnemingenLijst voor station %s", station_id)
                return None

            metingen = waarnemingen[0].get("MetingenLijst", [])
            if not metingen:
                logger.debug("Lege MetingenLijst voor station %s", station_id)
                return None

            laatste = metingen[-1]
            waarde = laatste.get("Meetwaarde", {}).get("Waarde_Numeriek")
            tijdstip = laatste.get("Tijdstip")

            if waarde is None or tijdstip is None:
                logger.debug("Ontbrekende waarde of tijdstip voor station %s", station_id)
                return None

            return {
                "timestamp": _parse_rws_timestamp(tijdstip),
                "value": float(waarde),
            }

    except aiohttp.ClientError as e:
        logger.warning("HTTP fout bij waterstand poll station %s: %s", station_id, e)
        return None
    except (KeyError, IndexError, ValueError) as e:
        logger.warning("Parse fout waterstand station %s: %s", station_id, e)
        return None


async def poll_water_levels(shutdown_event: asyncio.Event) -> None:
    """Poll RWS Waterinfo API elke WATER_POLL_INTERVAL_S seconden.

    Haalt de meest recente waterstand op voor alle WATERINFO_STATIONS
    en slaat deze op via db.upsert_water_level().

    Stopt wanneer shutdown_event is gezet.
    """
    logger.info(
        "Waterstand polling gestart (%d stations, interval %ds)",
        len(WATERINFO_STATIONS),
        WATER_POLL_INTERVAL_S,
    )

    while not shutdown_event.is_set():
        try:
            async with aiohttp.ClientSession() as session:
                success_count = 0
                for station_id, meta in WATERINFO_STATIONS.items():
                    result = await _fetch_latest_water_level(session, station_id)
                    if result is not None:
                        db.upsert_water_level(
                            station_id=station_id,
                            station_name=meta["name"],
                            timestamp=result["timestamp"],
                            water_level_cm=result["value"],
                            lat=meta["lat"],
                            lon=meta["lon"],
                        )
                        success_count += 1

            logger.info(
                "Waterstand poll voltooid: %d/%d stations succesvol",
                success_count,
                len(WATERINFO_STATIONS),
            )
        except Exception as e:
            logger.warning("Onverwachte fout tijdens waterstand poll: %s", e)

        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=WATER_POLL_INTERVAL_S,
            )
        except asyncio.TimeoutError:
            pass  # Normaal: timeout verstreken, volgende poll
