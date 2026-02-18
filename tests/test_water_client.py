"""Unit tests voor src/water_client.py.

Test de parsing van RWS Waterinfo API responses zonder echte HTTP calls.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.water_client import _fetch_latest_water_level, _parse_rws_timestamp


# ---------------------------------------------------------------------------
# Tests voor _parse_rws_timestamp()
# ---------------------------------------------------------------------------

def test_parse_rws_timestamp_cet():
    """Timestamp met CET offset (+01:00) wordt correct naar UTC geconverteerd."""
    result = _parse_rws_timestamp("2026-02-18T12:00:00.000+01:00")
    assert result == "2026-02-18T11:00:00Z"


def test_parse_rws_timestamp_utc():
    """Timestamp met UTC offset (+00:00) blijft ongewijzigd."""
    result = _parse_rws_timestamp("2026-02-18T10:00:00.000+00:00")
    assert result == "2026-02-18T10:00:00Z"


def test_parse_rws_timestamp_negative_offset():
    """Timestamp met negatieve offset wordt correct geconverteerd."""
    result = _parse_rws_timestamp("2026-02-18T00:00:00.000-05:00")
    assert result == "2026-02-18T05:00:00Z"


# ---------------------------------------------------------------------------
# Tests voor _fetch_latest_water_level()
# ---------------------------------------------------------------------------

VALID_RESPONSE = {
    "Succesvol": True,
    "WaarnemingenLijst": [
        {
            "Locatie": {"Code": "hoekvanholland", "Naam": "Hoek van Holland"},
            "MetingenLijst": [
                {
                    "Tijdstip": "2026-02-18T11:50:00.000+00:00",
                    "Meetwaarde": {"Waarde_Numeriek": -42},
                },
                {
                    "Tijdstip": "2026-02-18T12:00:00.000+00:00",
                    "Meetwaarde": {"Waarde_Numeriek": -12},
                },
            ],
        }
    ],
}


def _make_mock_response(status: int, json_data: dict | None = None) -> MagicMock:
    """Bouw een nep aiohttp response object."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=json_data or {})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


@pytest.mark.asyncio
async def test_fetch_latest_water_level_success():
    """Normale response: pakt de LAATSTE meting uit MetingenLijst."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=_make_mock_response(200, VALID_RESPONSE))

    result = await _fetch_latest_water_level(mock_session, "hoekvanholland")

    assert result is not None
    assert result["value"] == -12.0
    assert result["timestamp"] == "2026-02-18T12:00:00Z"


@pytest.mark.asyncio
async def test_fetch_latest_water_level_http_204():
    """HTTP 204 No Content: return None (geen data beschikbaar)."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=_make_mock_response(204))

    result = await _fetch_latest_water_level(mock_session, "vlissingen")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_latest_water_level_empty_waarnemingen():
    """Lege WaarnemingenLijst: return None."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(
        return_value=_make_mock_response(200, {"Succesvol": True, "WaarnemingenLijst": []})
    )

    result = await _fetch_latest_water_level(mock_session, "denhelder")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_latest_water_level_empty_metingen():
    """Lege MetingenLijst: return None."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(
        return_value=_make_mock_response(
            200,
            {"Succesvol": True, "WaarnemingenLijst": [{"MetingenLijst": []}]},
        )
    )

    result = await _fetch_latest_water_level(mock_session, "ijmuiden")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_latest_water_level_missing_waarde():
    """Ontbrekende Waarde_Numeriek: return None."""
    mock_session = MagicMock()
    response_data = {
        "Succesvol": True,
        "WaarnemingenLijst": [
            {
                "MetingenLijst": [
                    {"Tijdstip": "2026-02-18T12:00:00.000+00:00", "Meetwaarde": {}}
                ]
            }
        ],
    }
    mock_session.post = MagicMock(return_value=_make_mock_response(200, response_data))

    result = await _fetch_latest_water_level(mock_session, "rotterdam")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_latest_water_level_http_error():
    """HTTP client error wordt afgehandeld: return None (geen crash)."""
    import aiohttp

    mock_session = MagicMock()
    mock_resp = _make_mock_response(500)
    mock_resp.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=500)
    )
    mock_session.post = MagicMock(return_value=mock_resp)

    result = await _fetch_latest_water_level(mock_session, "scheveningen")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_latest_water_level_positive_value():
    """Positieve waterstand (stormvloed) wordt correct verwerkt."""
    response_data = {
        "Succesvol": True,
        "WaarnemingenLijst": [
            {
                "MetingenLijst": [
                    {
                        "Tijdstip": "2026-02-18T12:00:00.000+00:00",
                        "Meetwaarde": {"Waarde_Numeriek": 285},
                    }
                ]
            }
        ],
    }
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=_make_mock_response(200, response_data))

    result = await _fetch_latest_water_level(mock_session, "hoekvanholland")

    assert result is not None
    assert result["value"] == 285.0
