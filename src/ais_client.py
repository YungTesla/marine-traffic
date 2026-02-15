import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

import websockets

from src.config import (
    AISSTREAM_API_KEY,
    AISSTREAM_WS_URL,
    BOUNDING_BOXES,
    MESSAGE_TYPES,
    RECONNECT_BASE_DELAY_S,
    RECONNECT_MAX_DELAY_S,
    RECONNECT_JITTER_FACTOR,
)

logger = logging.getLogger(__name__)


@dataclass
class VesselPosition:
    mmsi: str
    timestamp: str
    lat: float
    lon: float
    sog: float  # speed over ground (knots)
    cog: float  # course over ground (degrees)
    heading: float  # true heading (degrees, -1 = unavailable)
    name: str = ""


@dataclass
class VesselStatic:
    mmsi: str
    name: str
    ship_type: int
    length: float
    width: float


def _parse_position(msg: dict) -> VesselPosition | None:
    try:
        meta = msg["MetaData"]
        report = msg["Message"]["PositionReport"]
        mmsi = str(meta["MMSI"])
        return VesselPosition(
            mmsi=mmsi,
            timestamp=meta.get("time_utc", datetime.now(timezone.utc).isoformat()),
            lat=report["Latitude"],
            lon=report["Longitude"],
            sog=report.get("Sog", 0.0),
            cog=report.get("Cog", 0.0),
            heading=float(report.get("TrueHeading", -1)),
            name=meta.get("ShipName", "").strip(),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.debug("Failed to parse PositionReport: %s", e)
        return None


def _parse_static(msg: dict) -> VesselStatic | None:
    try:
        meta = msg["MetaData"]
        static = msg["Message"]["ShipStaticData"]
        mmsi = str(meta["MMSI"])
        dim = static.get("Dimension", {})
        length = (dim.get("A", 0) or 0) + (dim.get("B", 0) or 0)
        width = (dim.get("C", 0) or 0) + (dim.get("D", 0) or 0)
        return VesselStatic(
            mmsi=mmsi,
            name=(static.get("Name") or meta.get("ShipName", "")).strip(),
            ship_type=static.get("Type", 0),
            length=float(length),
            width=float(width),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.debug("Failed to parse ShipStaticData: %s", e)
        return None


def _calculate_backoff(attempt: int) -> float:
    """Calculate exponential backoff delay with jitter.

    Args:
        attempt: Number of failed reconnection attempts (0-indexed)

    Returns:
        Delay in seconds with jitter applied
    """
    # Exponential backoff: base * 2^attempt, capped at max
    delay = min(RECONNECT_BASE_DELAY_S * (2 ** attempt), RECONNECT_MAX_DELAY_S)

    # Add jitter: randomize by ±RECONNECT_JITTER_FACTOR
    jitter = random.uniform(-RECONNECT_JITTER_FACTOR, RECONNECT_JITTER_FACTOR)
    delay_with_jitter = delay * (1 + jitter)

    # Ensure delay is never negative
    return max(0.1, delay_with_jitter)


async def stream_ais() -> AsyncIterator[VesselPosition | VesselStatic]:
    """Connect to AISStream.io and yield parsed messages. Reconnects on failure."""
    if not AISSTREAM_API_KEY:
        raise RuntimeError(
            "AISSTREAM_API_KEY not set. "
            "Get a free key at https://aisstream.io and set the env var."
        )

    subscribe_msg = json.dumps({
        "APIKey": AISSTREAM_API_KEY,
        "BoundingBoxes": BOUNDING_BOXES,
        "FilterMessageTypes": MESSAGE_TYPES,
    })

    attempt = 0  # Track reconnection attempts for exponential backoff

    while True:
        try:
            logger.info("Connecting to AISStream.io...")
            async with websockets.connect(AISSTREAM_WS_URL) as ws:
                await ws.send(subscribe_msg)
                logger.info("Subscribed. Streaming AIS data...")
                attempt = 0  # Reset backoff counter on successful connection

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("MessageType", "")

                    if msg_type == "PositionReport":
                        pos = _parse_position(msg)
                        if pos:
                            yield pos
                    elif msg_type == "ShipStaticData":
                        static = _parse_static(msg)
                        if static:
                            yield static

        except websockets.ConnectionClosed as e:
            logger.warning("WebSocket closed: %s. Reconnecting...", e)
        except OSError as e:
            logger.warning("Connection error: %s. Reconnecting...", e)

        # Exponential backoff with jitter
        delay = _calculate_backoff(attempt)
        logger.info("Reconnecting in %.1f seconds (attempt %d)...", delay, attempt + 1)
        await asyncio.sleep(delay)
        attempt += 1
