"""Waterstand polling client voor meerdere providers.

Ondersteunde providers:
- Rijkswaterstaat Waterinfo API (ddapi20) — NL kust + binnenwateren
- PEGELONLINE REST API (WSV Duitsland) — DE kust + binnenwateren
- Hub'Eau Hydrométrie (Frankrijk) — FR rivieren
- IMGW (Polen) — PL rivieren
- KiWIS / waterinfo.be (België, Vlaanderen) — BE kust + rivieren

Haalt elke WATER_POLL_INTERVAL_S seconden de meest recente waterstand op
voor alle geconfigureerde stations en slaat deze op in de database.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote

import aiohttp

from src.config import (
    RWS_BASE_URL, PEGELONLINE_BASE_URL, HUBEAU_BASE_URL,
    IMGW_HYDRO_URL, KIWIS_BASE_URL,
    WATER_STATIONS, WATER_POLL_INTERVAL_S,
)
from src import database as db

logger = logging.getLogger(__name__)

_RWS_LATEST_URL = (
    f"{RWS_BASE_URL}/ONLINEWAARNEMINGENSERVICES/OphalenLaatsteWaarnemingen"
)

_AQUO_METADATA = {
    "AquoMetadata": {
        "Grootheid": {"Code": "WATHTE"},
        "Eenheid": {"Code": "cm"},
        "Hoedanigheid": {"Code": "NAP"},
    }
}

# IMGW cache: bulk-fetch alle stations eenmaal per poll-cyclus
_imgw_cache: dict | None = None
_imgw_cache_ts: float = 0.0


def _parse_rws_timestamp(ts_str: str) -> str:
    """Converteer API timestamp naar UTC ISO format ('YYYY-MM-DDTHH:MM:SSZ').

    Werkt voor RWS, PEGELONLINE en KiWIS timestamps (ISO 8601 met offset).
    Verwacht format: '2026-02-18T12:00:00.000+01:00'
    """
    dt = datetime.fromisoformat(ts_str)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Provider: RWS (Nederland)
# ---------------------------------------------------------------------------

async def _fetch_rws(
    session: aiohttp.ClientSession, station_code: str
) -> dict | None:
    """Haal de meest recente waterstand op voor één RWS station.

    Returns dict met 'timestamp' (UTC ISO) en 'value' (float, cm NAP),
    of None als geen data beschikbaar is.
    """
    payload = {
        "Locatie": {"Code": station_code},
        "AquoPlusWaarnemingMetadata": _AQUO_METADATA,
    }
    try:
        async with session.post(_RWS_LATEST_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 204:
                logger.debug("Geen waterstanddata voor RWS station %s (HTTP 204)", station_code)
                return None

            resp.raise_for_status()
            data = await resp.json()

            waarnemingen = data.get("WaarnemingenLijst", [])
            if not waarnemingen:
                logger.debug("Lege WaarnemingenLijst voor RWS station %s", station_code)
                return None

            metingen = waarnemingen[0].get("MetingenLijst", [])
            if not metingen:
                logger.debug("Lege MetingenLijst voor RWS station %s", station_code)
                return None

            laatste = metingen[-1]
            waarde = laatste.get("Meetwaarde", {}).get("Waarde_Numeriek")
            tijdstip = laatste.get("Tijdstip")

            if waarde is None or tijdstip is None:
                logger.debug("Ontbrekende waarde of tijdstip voor RWS station %s", station_code)
                return None

            return {
                "timestamp": _parse_rws_timestamp(tijdstip),
                "value": float(waarde),
            }

    except aiohttp.ClientError as e:
        logger.warning("HTTP fout bij RWS station %s: %s", station_code, e)
        return None
    except (KeyError, IndexError, ValueError) as e:
        logger.warning("Parse fout RWS station %s: %s", station_code, e)
        return None


# ---------------------------------------------------------------------------
# Provider: PEGELONLINE (Duitsland)
# ---------------------------------------------------------------------------

async def _fetch_pegelonline(
    session: aiohttp.ClientSession, shortname: str
) -> dict | None:
    """Haal de meest recente waterstand op voor één PEGELONLINE station.

    Returns dict met 'timestamp' (UTC ISO) en 'value' (float, cm PNP),
    of None als geen data beschikbaar is.
    """
    url = f"{PEGELONLINE_BASE_URL}/stations/{quote(shortname)}/W/currentmeasurement.json"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 404:
                logger.debug("PEGELONLINE station niet gevonden: %s (HTTP 404)", shortname)
                return None

            resp.raise_for_status()
            data = await resp.json()

            value = data.get("value")
            timestamp = data.get("timestamp")

            if value is None or timestamp is None:
                logger.debug("Ontbrekende waarde of tijdstip voor PEGELONLINE station %s", shortname)
                return None

            return {
                "timestamp": _parse_rws_timestamp(timestamp),
                "value": float(value),
            }

    except aiohttp.ClientError as e:
        logger.warning("HTTP fout bij PEGELONLINE station %s: %s", shortname, e)
        return None
    except (KeyError, ValueError) as e:
        logger.warning("Parse fout PEGELONLINE station %s: %s", shortname, e)
        return None


# ---------------------------------------------------------------------------
# Provider: Hub'Eau (Frankrijk)
# ---------------------------------------------------------------------------

async def _fetch_hubeau(
    session: aiohttp.ClientSession, station_code: str
) -> dict | None:
    """Haal de meest recente waterstand op voor één Hub'Eau station.

    Returns dict met 'timestamp' (UTC ISO) en 'value' (float, cm IGN69),
    of None als geen data beschikbaar is.
    Hub'Eau levert mm — wordt hier geconverteerd naar cm.
    """
    url = (
        f"{HUBEAU_BASE_URL}/observations_tr"
        f"?code_entite={station_code}&grandeur_hydro=H&size=1&sort=desc"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            body = await resp.json()

            records = body.get("data", [])
            if not records:
                logger.debug("Geen data voor Hub'Eau station %s", station_code)
                return None

            obs = records[0]
            value_mm = obs.get("resultat_obs")
            timestamp = obs.get("date_obs")

            if value_mm is None or timestamp is None:
                logger.debug("Ontbrekende waarde of tijdstip voor Hub'Eau station %s", station_code)
                return None

            return {
                "timestamp": timestamp if timestamp.endswith("Z") else _parse_rws_timestamp(timestamp),
                "value": float(value_mm) / 10.0,  # mm → cm
            }

    except aiohttp.ClientError as e:
        logger.warning("HTTP fout bij Hub'Eau station %s: %s", station_code, e)
        return None
    except (KeyError, IndexError, ValueError) as e:
        logger.warning("Parse fout Hub'Eau station %s: %s", station_code, e)
        return None


# ---------------------------------------------------------------------------
# Provider: IMGW (Polen) — bulk-fetch met cache
# ---------------------------------------------------------------------------

async def _fetch_imgw_all(session: aiohttp.ClientSession) -> dict:
    """Fetch alle IMGW stations in één request, cache per poll-cyclus.

    Returns dict: station_code -> {"timestamp": ..., "value": ...}
    """
    global _imgw_cache, _imgw_cache_ts

    # Cache geldig voor 5 minuten
    if _imgw_cache is not None and (time.monotonic() - _imgw_cache_ts) < 300:
        return _imgw_cache

    try:
        async with session.get(IMGW_HYDRO_URL, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            stations = await resp.json()

        result = {}
        for s in stations:
            code = s.get("id_stacji")
            value_str = s.get("stan_wody")
            ts_str = s.get("stan_wody_data_pomiaru")

            if not code or not value_str or not ts_str:
                continue

            try:
                # IMGW timestamp: "2026-02-19 00:00" (lokale tijd Polen, CET/CEST)
                dt_local = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
                # Aannemen CET (+01:00) — IMGW timestamps zijn Poolse lokale tijd
                dt_utc = dt_local.replace(tzinfo=timezone.utc)  # Conservatief: als UTC behandelen
                ts_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

                result[code] = {
                    "timestamp": ts_utc,
                    "value": float(value_str),  # al in cm
                }
            except (ValueError, TypeError):
                continue

        _imgw_cache = result
        _imgw_cache_ts = time.monotonic()
        logger.debug("IMGW bulk-fetch: %d stations geladen", len(result))
        return result

    except aiohttp.ClientError as e:
        logger.warning("HTTP fout bij IMGW bulk-fetch: %s", e)
        return _imgw_cache or {}
    except (ValueError, KeyError) as e:
        logger.warning("Parse fout IMGW bulk-fetch: %s", e)
        return _imgw_cache or {}


async def _fetch_imgw(
    session: aiohttp.ClientSession, station_code: str
) -> dict | None:
    """Haal de meest recente waterstand op voor één IMGW station via bulk-cache.

    Returns dict met 'timestamp' (UTC ISO) en 'value' (float, cm PNP),
    of None als station niet gevonden.
    """
    all_data = await _fetch_imgw_all(session)
    return all_data.get(station_code)


# ---------------------------------------------------------------------------
# Provider: KiWIS / waterinfo.be (België)
# ---------------------------------------------------------------------------

async def _fetch_kiwis(
    session: aiohttp.ClientSession, ts_id: str
) -> dict | None:
    """Haal de meest recente waterstand op voor één KiWIS time series.

    Returns dict met 'timestamp' (UTC ISO) en 'value' (float, cm TAW),
    of None als geen data beschikbaar is.
    KiWIS levert meter — wordt hier geconverteerd naar cm.
    """
    url = (
        f"{KIWIS_BASE_URL}?type=queryServices&service=kisters"
        f"&request=getTimeseriesValues&ts_id={ts_id}"
        f"&period=PT1H&format=json"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            body = await resp.json()

            data_list = body.get("data", [])
            if not data_list:
                logger.debug("Geen data voor KiWIS ts_id %s", ts_id)
                return None

            rows = data_list[0].get("rows", [])
            if not rows:
                logger.debug("Lege rows voor KiWIS ts_id %s", ts_id)
                return None

            # Laatste meting
            last_row = rows[-1]
            timestamp_str = last_row[0]  # "2026-02-18T22:27:00+01:00"
            value_m = last_row[1]        # meter

            if value_m is None or timestamp_str is None:
                return None

            return {
                "timestamp": _parse_rws_timestamp(timestamp_str),
                "value": float(value_m) * 100.0,  # m → cm
            }

    except aiohttp.ClientError as e:
        logger.warning("HTTP fout bij KiWIS ts_id %s: %s", ts_id, e)
        return None
    except (KeyError, IndexError, ValueError, TypeError) as e:
        logger.warning("Parse fout KiWIS ts_id %s: %s", ts_id, e)
        return None


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------

async def poll_water_levels(shutdown_event: asyncio.Event) -> None:
    """Poll waterstanden voor alle providers elke WATER_POLL_INTERVAL_S seconden.

    Haalt de meest recente waterstand op voor alle WATER_STATIONS
    en slaat deze op via db.upsert_water_level().

    Stopt wanneer shutdown_event is gezet.
    """
    logger.info(
        "Waterstand polling gestart (%d stations, interval %ds)",
        len(WATER_STATIONS),
        WATER_POLL_INTERVAL_S,
    )

    async with aiohttp.ClientSession() as session:
        while not shutdown_event.is_set():
            try:
                # Invalidate IMGW cache aan begin van elke poll-cyclus
                global _imgw_cache_ts
                _imgw_cache_ts = 0.0

                success_count = 0
                for station_id, meta in WATER_STATIONS.items():
                    source = meta["source"]

                    if source == "rws":
                        rws_code = station_id.removeprefix("rws:")
                        result = await _fetch_rws(session, rws_code)
                    elif source == "pegelonline":
                        result = await _fetch_pegelonline(session, meta["shortname"])
                    elif source == "hubeau":
                        result = await _fetch_hubeau(session, meta["station_code"])
                    elif source == "imgw":
                        result = await _fetch_imgw(session, meta["station_code"])
                    elif source == "kiwis":
                        result = await _fetch_kiwis(session, meta["ts_id"])
                    else:
                        continue

                    if result is not None:
                        db.upsert_water_level(
                            station_id=station_id,
                            station_name=meta["name"],
                            timestamp=result["timestamp"],
                            water_level_cm=result["value"],
                            lat=meta["lat"],
                            lon=meta["lon"],
                            source=source,
                            reference_datum=meta["reference_datum"],
                        )
                        success_count += 1

                logger.info(
                    "Waterstand poll voltooid: %d/%d stations succesvol",
                    success_count,
                    len(WATER_STATIONS),
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
