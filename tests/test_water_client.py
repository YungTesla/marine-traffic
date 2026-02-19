"""Unit tests voor src/water_client.py.

Test de parsing van RWS en PEGELONLINE API responses zonder echte HTTP calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.water_client import (
    _fetch_rws, _fetch_pegelonline, _fetch_hubeau, _fetch_imgw, _fetch_kiwis,
    _parse_rws_timestamp,
)
import src.water_client as water_client_mod


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
# Tests voor _fetch_rws()
# ---------------------------------------------------------------------------

VALID_RWS_RESPONSE = {
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
async def test_fetch_rws_success():
    """Normale response: pakt de LAATSTE meting uit MetingenLijst."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=_make_mock_response(200, VALID_RWS_RESPONSE))

    result = await _fetch_rws(mock_session, "hoekvanholland")

    assert result is not None
    assert result["value"] == -12.0
    assert result["timestamp"] == "2026-02-18T12:00:00Z"


@pytest.mark.asyncio
async def test_fetch_rws_http_204():
    """HTTP 204 No Content: return None (geen data beschikbaar)."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=_make_mock_response(204))

    result = await _fetch_rws(mock_session, "vlissingen")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_rws_empty_waarnemingen():
    """Lege WaarnemingenLijst: return None."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(
        return_value=_make_mock_response(200, {"Succesvol": True, "WaarnemingenLijst": []})
    )

    result = await _fetch_rws(mock_session, "denhelder")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_rws_empty_metingen():
    """Lege MetingenLijst: return None."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(
        return_value=_make_mock_response(
            200,
            {"Succesvol": True, "WaarnemingenLijst": [{"MetingenLijst": []}]},
        )
    )

    result = await _fetch_rws(mock_session, "ijmuiden")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_rws_missing_waarde():
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

    result = await _fetch_rws(mock_session, "rotterdam")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_rws_http_error():
    """HTTP client error wordt afgehandeld: return None (geen crash)."""
    import aiohttp

    mock_session = MagicMock()
    mock_resp = _make_mock_response(500)
    mock_resp.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=500)
    )
    mock_session.post = MagicMock(return_value=mock_resp)

    result = await _fetch_rws(mock_session, "scheveningen")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_rws_positive_value():
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

    result = await _fetch_rws(mock_session, "hoekvanholland")

    assert result is not None
    assert result["value"] == 285.0


# ---------------------------------------------------------------------------
# Tests voor _fetch_pegelonline()
# ---------------------------------------------------------------------------

VALID_PEGELONLINE_RESPONSE = {
    "timestamp": "2026-02-18T22:38:00+01:00",
    "value": 444.0,
    "stateMnwMhw": "unknown",
    "stateNswHsw": "unknown",
}


@pytest.mark.asyncio
async def test_fetch_pegelonline_success():
    """Normale PEGELONLINE response wordt correct geparsed."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, VALID_PEGELONLINE_RESPONSE)
    )

    result = await _fetch_pegelonline(mock_session, "CUXHAVEN STEUBENHÖFT")

    assert result is not None
    assert result["value"] == 444.0
    assert result["timestamp"] == "2026-02-18T21:38:00Z"  # CET -> UTC


@pytest.mark.asyncio
async def test_fetch_pegelonline_http_404():
    """HTTP 404 (station niet gevonden): return None."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=_make_mock_response(404))

    result = await _fetch_pegelonline(mock_session, "ONBEKEND STATION")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_pegelonline_missing_value():
    """Ontbrekende value in PEGELONLINE response: return None."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, {"timestamp": "2026-02-18T22:38:00+01:00"})
    )

    result = await _fetch_pegelonline(mock_session, "CUXHAVEN STEUBENHÖFT")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_pegelonline_http_error():
    """HTTP server error wordt afgehandeld: return None."""
    import aiohttp

    mock_session = MagicMock()
    mock_resp = _make_mock_response(500)
    mock_resp.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=500)
    )
    mock_session.get = MagicMock(return_value=mock_resp)

    result = await _fetch_pegelonline(mock_session, "CUXHAVEN STEUBENHÖFT")

    assert result is None


# ---------------------------------------------------------------------------
# Tests voor _fetch_hubeau()
# ---------------------------------------------------------------------------

VALID_HUBEAU_RESPONSE = {
    "count": 1,
    "data": [
        {
            "code_entite": "F700000103",
            "date_obs": "2026-02-18T22:20:00Z",
            "resultat_obs": 3435.0,
            "grandeur_hydro": "H",
        }
    ],
}


@pytest.mark.asyncio
async def test_fetch_hubeau_success():
    """Hub'Eau response: mm waarde wordt correct naar cm geconverteerd."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, VALID_HUBEAU_RESPONSE)
    )

    result = await _fetch_hubeau(mock_session, "F700000103")

    assert result is not None
    assert result["value"] == 343.5  # 3435 mm → 343.5 cm
    assert result["timestamp"] == "2026-02-18T22:20:00Z"


@pytest.mark.asyncio
async def test_fetch_hubeau_empty_data():
    """Lege data array: return None."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, {"count": 0, "data": []})
    )

    result = await _fetch_hubeau(mock_session, "UNKNOWN")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_hubeau_http_error():
    """HTTP error wordt afgehandeld: return None."""
    import aiohttp

    mock_session = MagicMock()
    mock_resp = _make_mock_response(500)
    mock_resp.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=500)
    )
    mock_session.get = MagicMock(return_value=mock_resp)

    result = await _fetch_hubeau(mock_session, "F700000103")

    assert result is None


# ---------------------------------------------------------------------------
# Tests voor _fetch_imgw()
# ---------------------------------------------------------------------------

VALID_IMGW_RESPONSE = [
    {
        "id_stacji": "152210030",
        "stacja": "Szczecin",
        "rzeka": "Odra",
        "stan_wody": "486",
        "stan_wody_data_pomiaru": "2026-02-19 00:00",
    },
    {
        "id_stacji": "152200020",
        "stacja": "Kostrzyn",
        "rzeka": "Odra",
        "stan_wody": "354",
        "stan_wody_data_pomiaru": "2026-02-19 00:00",
    },
]


@pytest.mark.asyncio
async def test_fetch_imgw_success():
    """IMGW bulk-fetch: station wordt correct uit cache opgezocht."""
    # Reset cache
    water_client_mod._imgw_cache = None
    water_client_mod._imgw_cache_ts = 0.0

    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, VALID_IMGW_RESPONSE)
    )

    result = await _fetch_imgw(mock_session, "152210030")

    assert result is not None
    assert result["value"] == 486.0
    assert result["timestamp"] == "2026-02-19T00:00:00Z"

    # Cleanup
    water_client_mod._imgw_cache = None
    water_client_mod._imgw_cache_ts = 0.0


@pytest.mark.asyncio
async def test_fetch_imgw_station_not_found():
    """IMGW: onbekend station retourneert None."""
    water_client_mod._imgw_cache = None
    water_client_mod._imgw_cache_ts = 0.0

    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, VALID_IMGW_RESPONSE)
    )

    result = await _fetch_imgw(mock_session, "999999999")

    assert result is None

    water_client_mod._imgw_cache = None
    water_client_mod._imgw_cache_ts = 0.0


@pytest.mark.asyncio
async def test_fetch_imgw_http_error():
    """IMGW HTTP error: return None (lege cache)."""
    import aiohttp

    water_client_mod._imgw_cache = None
    water_client_mod._imgw_cache_ts = 0.0

    mock_session = MagicMock()
    mock_resp = _make_mock_response(500)
    mock_resp.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=500)
    )
    mock_session.get = MagicMock(return_value=mock_resp)

    result = await _fetch_imgw(mock_session, "152210030")

    assert result is None

    water_client_mod._imgw_cache = None
    water_client_mod._imgw_cache_ts = 0.0


# ---------------------------------------------------------------------------
# Tests voor _fetch_kiwis()
# ---------------------------------------------------------------------------

VALID_KIWIS_RESPONSE = {
    "data": [
        {
            "columns": ["Timestamp", "Value"],
            "rows": [
                ["2026-02-18T22:17:00+01:00", 2.045],
                ["2026-02-18T22:27:00+01:00", 2.145],
            ],
        }
    ]
}


@pytest.mark.asyncio
async def test_fetch_kiwis_success():
    """KiWIS response: meter waarde wordt correct naar cm geconverteerd."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, VALID_KIWIS_RESPONSE)
    )

    result = await _fetch_kiwis(mock_session, "0453986010")

    assert result is not None
    assert result["value"] == 214.5  # 2.145 m → 214.5 cm
    assert result["timestamp"] == "2026-02-18T21:27:00Z"  # CET → UTC


@pytest.mark.asyncio
async def test_fetch_kiwis_empty_rows():
    """Lege rows: return None."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=_make_mock_response(200, {"data": [{"rows": []}]})
    )

    result = await _fetch_kiwis(mock_session, "0453986010")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_kiwis_http_error():
    """KiWIS HTTP error: return None."""
    import aiohttp

    mock_session = MagicMock()
    mock_resp = _make_mock_response(500)
    mock_resp.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=500)
    )
    mock_session.get = MagicMock(return_value=mock_resp)

    result = await _fetch_kiwis(mock_session, "0453986010")

    assert result is None
